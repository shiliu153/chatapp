#include "store/mysql_pool.h"

#include <chrono>
#include <stdexcept>
#include <thread>
#include <utility>

#include "store/stmt.h"
#include "util/log.h"

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

MysqlPool::MysqlPool(const MysqlDsn& dsn, int size, int64_t idle_ping_ms)
    : dsn_(dsn), idle_ping_ms_(idle_ping_ms), size_(size) {
  if (size_ <= 0) {
    throw std::invalid_argument("mysql pool size must be positive");
  }
  idle_.reserve(static_cast<std::size_t>(size_));
  for (int i = 0; i < size_; ++i) {
    idle_.push_back(Slot{connect_one(dsn_), now_ms()});
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
  return Lease(*this, conn);
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
