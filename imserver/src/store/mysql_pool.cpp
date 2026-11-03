#include "store/mysql_pool.h"

#include <chrono>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>

#include "store/stmt.h"
#include "util/log.h"
#include "util/metrics.h"

namespace {

int64_t now_ms() {
  return std::chrono::duration_cast<std::chrono::milliseconds>(
             std::chrono::system_clock::now().time_since_epoch())
      .count();
}

/// 连接级错误:出现这些错误码说明 socket 已经不可用,必须换一条连接。
bool is_connection_error(int code) {
  return code == 2006 || code == 2013 || code == 2055;
}

MYSQL* connect_one(const MysqlDsn& dsn) {
  MYSQL* conn = mysql_init(nullptr);
  if (conn == nullptr) {
    throw std::runtime_error("mysql_init failed");
  }
  mysql_options(conn, MYSQL_SET_CHARSET_NAME, "utf8mb4");
  if (mysql_real_connect(conn, dsn.host.c_str(), dsn.user.c_str(), dsn.password.c_str(),
                         dsn.database.c_str(), dsn.port, nullptr, 0) == nullptr) {
    const std::string error = mysql_error(conn);
    mysql_close(conn);
    throw std::runtime_error("mysql connect failed: " + error);
  }
  return conn;
}

}  // namespace

MysqlPool::MysqlPool(const MysqlDsn& dsn, int size, int64_t idle_ping_ms,
                     int64_t connect_wait_ms)
    : dsn_(dsn), idle_ping_ms_(idle_ping_ms), connect_wait_ms_(connect_wait_ms), size_(size) {
  if (size_ <= 0) {
    throw std::invalid_argument("mysql pool size must be positive");
  }
  idle_.reserve(static_cast<std::size_t>(size_));
  // 启动时 DB 还没就绪是常态(容器一起拉起、MySQL 正在崩溃恢复)。
  // 直接抛会让进程退出,而 Docker 的重启退避会一路涨到 60s —— DB 恢复后还要再等一个
  // 退避周期才起得来(2026-11-01 压测实测多等 47s)。这里在窗口内重试,窗口内恢复即启动。
  const int64_t wait_ms = connect_wait_ms_ > 0 ? connect_wait_ms_ : 0;
  const auto deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(wait_ms);
  try {
    for (int i = 0; i < size_; ++i) {
      idle_.push_back(Slot{connect_until(deadline), now_ms()});
    }
  } catch (...) {
    // 构造失败时析构函数不会执行,已建好的连接要自己关掉。
    for (const Slot& slot : idle_) {
      if (slot.conn != nullptr) {
        clear_stmt_cache(slot.conn);
        mysql_close(slot.conn);
      }
    }
    idle_.clear();
    throw;
  }
}

MysqlPool::~MysqlPool() {
  std::vector<Slot> to_close;
  {
    const std::lock_guard<std::mutex> lock(mutex_);
    closed_ = true;
    to_close.swap(idle_);
  }
  for (const Slot& slot : to_close) {
    if (slot.conn == nullptr) {
      continue;
    }
    clear_stmt_cache(slot.conn);
    mysql_close(slot.conn);
  }
}

MysqlPool::Lease MysqlPool::acquire() {
  const auto wait_start = std::chrono::steady_clock::now();
  MYSQL* conn = nullptr;
  {
    std::unique_lock<std::mutex> lock(mutex_);
    cv_.wait(lock, [this] { return closed_ || !idle_.empty(); });
    if (closed_) {
      throw std::runtime_error("mysql pool closed");
    }
    Slot slot = idle_.back();
    idle_.pop_back();
    lock.unlock();

    conn = slot.conn;
    if (conn == nullptr) {
      // 上一次重连失败的槽位:这里再试。
      conn = connect_with_retry(3);
    } else if (idle_ping_ms_ >= 0 && now_ms() - slot.last_used_ms >= idle_ping_ms_) {
      // MySQL 的 wait_timeout(默认 8h)会掐掉空闲连接;池里的死连接必须先 ping 掉,
      // 否则第一条 SQL 必然报 "Lost connection",而且之后每次都失败。
      if (mysql_ping(conn) != 0) {
        log_error("mysql_reconnect", {{"reason", mysql_error(conn)}});
        discard(conn);
        conn = connect_with_retry(3);
      }
    }
  }
  // 池等待时间:并发打满时这个值会先涨,是「DB 侧瓶颈」的早期信号。
  const auto waited_us = std::chrono::duration_cast<std::chrono::microseconds>(
                             std::chrono::steady_clock::now() - wait_start)
                             .count();
  metrics::db_wait_count.fetch_add(1, std::memory_order_relaxed);
  metrics::db_wait_us.fetch_add(static_cast<uint64_t>(waited_us),
                                std::memory_order_relaxed);
  return Lease(*this, conn);
}

MYSQL* MysqlPool::connect_until(std::chrono::steady_clock::time_point deadline) {
  int attempt = 0;
  for (;;) {
    try {
      return connect_one(dsn_);
    } catch (const std::exception& error) {
      ++attempt;
      if (std::chrono::steady_clock::now() >= deadline) {
        throw std::runtime_error(std::string("mysql connect failed after ") +
                                 std::to_string(attempt) + " attempts: " + error.what());
      }
      log_error("mysql_connect_retry",
                {{"attempt", std::to_string(attempt)}, {"error", error.what()}});
      std::this_thread::sleep_for(std::chrono::milliseconds(2000));
    }
  }
}

MYSQL* MysqlPool::connect_with_retry(int attempts) {
  for (int attempt = 0; attempt < attempts; ++attempt) {
    try {
      return connect_one(dsn_);
    } catch (const std::exception& error) {
      log_error("mysql_connect_failed",
                {{"attempt", std::to_string(attempt + 1)}, {"error", error.what()}});
      std::this_thread::sleep_for(std::chrono::milliseconds(50 * (attempt + 1)));
    }
  }
  // 返回空连接:调用方拿到空 lease 后,任何 SQL 都会立刻失败并走 50001 分支,
  // 既不会把死连接塞回池里,也不会让异常逃出 DB 线程池。
  return nullptr;
}

void MysqlPool::discard(MYSQL* conn) {
  if (conn == nullptr) {
    return;
  }
  clear_stmt_cache(conn);
  mysql_close(conn);
}

void MysqlPool::release(MYSQL* conn) {
  {
    const std::lock_guard<std::mutex> lock(mutex_);
    if (closed_) {
      if (conn != nullptr) {
        clear_stmt_cache(conn);
        mysql_close(conn);
      }
      return;
    }
    idle_.push_back(Slot{conn, now_ms()});
  }
  cv_.notify_one();
}

MysqlPool::Lease::Lease(MysqlPool& pool, MYSQL* conn) : pool_(&pool), conn_(conn) {}

MysqlPool::Lease::~Lease() { release(); }

MysqlPool::Lease::Lease(Lease&& other) noexcept
    : pool_(other.pool_), conn_(other.conn_) {
  other.pool_ = nullptr;
  other.conn_ = nullptr;
}

MysqlPool::Lease& MysqlPool::Lease::operator=(Lease&& other) noexcept {
  if (this != &other) {
    release();
    pool_ = other.pool_;
    conn_ = other.conn_;
    other.pool_ = nullptr;
    other.conn_ = nullptr;
  }
  return *this;
}

void MysqlPool::Lease::release() {
  if (pool_ != nullptr) {
    pool_->release(conn_);
  }
  pool_ = nullptr;
  conn_ = nullptr;
}

MYSQL_RES* MysqlPool::Lease::query(const std::string& sql) {
  if (conn_ == nullptr) {
    throw MysqlError(2006, "mysql lease has no live connection");
  }
  if (mysql_real_query(conn_, sql.data(), sql.size()) != 0) {
    const int code = mysql_errno(conn_);
    const std::string message = mysql_error(conn_);
    if (is_connection_error(code)) {
      // 连接已死:立刻销毁,让下一次 acquire 建新连接(而不是把死连接放回池里)。
      pool_->discard(conn_);
      conn_ = nullptr;
    }
    throw MysqlError(code, "mysql query failed: " + message);
  }
  return mysql_store_result(conn_);
}

std::string MysqlPool::Lease::escape(const std::string& input) const {
  if (conn_ == nullptr) {
    throw MysqlError(2006, "mysql lease has no live connection");
  }
  std::string output(input.size() * 2 + 1, '\0');
  const auto length = mysql_real_escape_string(
      conn_, output.data(), input.data(), static_cast<unsigned long>(input.size()));
  output.resize(length);
  return output;
}

void MysqlPool::Lease::begin() { query("START TRANSACTION"); }
void MysqlPool::Lease::commit() { query("COMMIT"); }
void MysqlPool::Lease::rollback() { query("ROLLBACK"); }
