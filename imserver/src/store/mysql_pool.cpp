#include "store/mysql_pool.h"

#include <stdexcept>
#include <utility>

namespace {

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

MysqlPool::MysqlPool(const MysqlDsn& dsn, int size) : dsn_(dsn), size_(size) {
  if (size_ <= 0) {
    throw std::invalid_argument("mysql pool size must be positive");
  }
  idle_.reserve(static_cast<std::size_t>(size_));
  for (int i = 0; i < size_; ++i) {
    idle_.push_back(connect_one(dsn_));
  }
}

MysqlPool::~MysqlPool() {
  std::vector<MYSQL*> to_close;
  {
    const std::lock_guard<std::mutex> lock(mutex_);
    closed_ = true;
    to_close.swap(idle_);
  }
  for (MYSQL* conn : to_close) {
    mysql_close(conn);
  }
}

MysqlPool::Lease MysqlPool::acquire() {
  std::unique_lock<std::mutex> lock(mutex_);
  cv_.wait(lock, [this] { return closed_ || !idle_.empty(); });
  if (closed_) {
    throw std::runtime_error("mysql pool closed");
  }
  MYSQL* conn = idle_.back();
  idle_.pop_back();
  return Lease(*this, conn);
}

void MysqlPool::release(MYSQL* conn) {
  if (conn == nullptr) {
    return;
  }
  {
    const std::lock_guard<std::mutex> lock(mutex_);
    if (closed_) {
      mysql_close(conn);
      return;
    }
    idle_.push_back(conn);
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
  if (pool_ != nullptr && conn_ != nullptr) {
    pool_->release(conn_);
  }
  pool_ = nullptr;
  conn_ = nullptr;
}

MYSQL_RES* MysqlPool::Lease::query(const std::string& sql) {
  if (conn_ == nullptr) {
    throw std::runtime_error("mysql lease is empty");
  }
  if (mysql_real_query(conn_, sql.data(), sql.size()) != 0) {
    throw std::runtime_error(std::string("mysql query failed: ") + mysql_error(conn_));
  }
  return mysql_store_result(conn_);
}

void MysqlPool::Lease::begin() { query("START TRANSACTION"); }

void MysqlPool::Lease::commit() { query("COMMIT"); }

void MysqlPool::Lease::rollback() { query("ROLLBACK"); }
