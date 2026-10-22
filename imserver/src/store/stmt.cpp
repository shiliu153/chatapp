#include "store/stmt.h"

#include <mutex>
#include <unordered_map>
#include <utility>

namespace {

// 每条写语句原本要 prepare + execute + close 三次往返。连接是独占租用的,
// 所以按 (连接, SQL) 缓存 prepared statement,热路径只剩 execute 一次往返。
std::mutex g_cache_mu;
std::unordered_map<MYSQL*, std::unordered_map<std::string, MYSQL_STMT*>> g_cache;

MYSQL_STMT* acquire_stmt(MYSQL* conn, const std::string& sql) {
  const std::lock_guard<std::mutex> lock(g_cache_mu);
  auto& per_conn = g_cache[conn];
  const auto it = per_conn.find(sql);
  if (it != per_conn.end()) {
    return it->second;
  }
  MYSQL_STMT* stmt = mysql_stmt_init(conn);
  if (stmt == nullptr) {
    throw MysqlError(0, "mysql_stmt_init failed");
  }
  if (mysql_stmt_prepare(stmt, sql.data(), static_cast<unsigned long>(sql.size())) != 0) {
    const int code = mysql_stmt_errno(stmt);
    const std::string message = mysql_stmt_error(stmt);
    mysql_stmt_close(stmt);
    throw MysqlError(code, "mysql_stmt_prepare failed: " + message);
  }
  per_conn.emplace(sql, stmt);
  return stmt;
}

}  // namespace

void clear_stmt_cache(MYSQL* conn) {
  const std::lock_guard<std::mutex> lock(g_cache_mu);
  const auto it = g_cache.find(conn);
  if (it == g_cache.end()) {
    return;
  }
  for (auto& [sql, stmt] : it->second) {
    (void)sql;
    mysql_stmt_close(stmt);
  }
  g_cache.erase(it);
}

Stmt::Stmt(MYSQL* conn, const std::string& sql) : stmt_(acquire_stmt(conn, sql)) {
  binds_.reserve(16);
  u64_.reserve(16);
  i32_.reserve(16);
  strings_.reserve(16);
  lengths_.reserve(16);
  nulls_.reserve(16);
}

Stmt::~Stmt() = default;

void Stmt::ensure(int index) {
  const auto size = static_cast<std::size_t>(index + 1);
  if (binds_.size() < size) {
    binds_.resize(size);
    u64_.resize(size);
    i32_.resize(size);
    strings_.resize(size);
    lengths_.resize(size);
    nulls_.resize(size);
  }
  binds_[static_cast<std::size_t>(index)] = MYSQL_BIND{};
  nulls_[static_cast<std::size_t>(index)] = 0;
}

void Stmt::bind_uint(int index, uint64_t value) {
  ensure(index);
  auto& bind = binds_[static_cast<std::size_t>(index)];
  u64_[static_cast<std::size_t>(index)] = value;
  bind.buffer_type = MYSQL_TYPE_LONGLONG;
  bind.buffer = &u64_[static_cast<std::size_t>(index)];
  bind.is_unsigned = 1;
  bind.is_null = reinterpret_cast<bool*>(&nulls_[static_cast<std::size_t>(index)]);
}

void Stmt::bind_int(int index, int value) {
  ensure(index);
  auto& bind = binds_[static_cast<std::size_t>(index)];
  i32_[static_cast<std::size_t>(index)] = value;
  bind.buffer_type = MYSQL_TYPE_LONG;
  bind.buffer = &i32_[static_cast<std::size_t>(index)];
  bind.is_null = reinterpret_cast<bool*>(&nulls_[static_cast<std::size_t>(index)]);
}

void Stmt::bind_string(int index, const std::string& value) {
  ensure(index);
  auto& bind = binds_[static_cast<std::size_t>(index)];
  strings_[static_cast<std::size_t>(index)] = value;
  lengths_[static_cast<std::size_t>(index)] =
      static_cast<unsigned long>(strings_[static_cast<std::size_t>(index)].size());
  bind.buffer_type = MYSQL_TYPE_STRING;
  bind.buffer = strings_[static_cast<std::size_t>(index)].data();
  bind.buffer_length = lengths_[static_cast<std::size_t>(index)];
  bind.length = &lengths_[static_cast<std::size_t>(index)];
  bind.is_null = reinterpret_cast<bool*>(&nulls_[static_cast<std::size_t>(index)]);
}

void Stmt::bind_null(int index) {
  ensure(index);
  nulls_[static_cast<std::size_t>(index)] = 1;
  binds_[static_cast<std::size_t>(index)].is_null =
      reinterpret_cast<bool*>(&nulls_[static_cast<std::size_t>(index)]);
}

void Stmt::execute() {
  mysql_stmt_free_result(stmt_);
  if (mysql_stmt_bind_param(stmt_, binds_.data()) != 0) {
    throw MysqlError(mysql_stmt_errno(stmt_), mysql_stmt_error(stmt_));
  }
  if (mysql_stmt_execute(stmt_) != 0) {
    throw MysqlError(mysql_stmt_errno(stmt_), mysql_stmt_error(stmt_));
  }
}

uint64_t Stmt::insert_id() const { return mysql_stmt_insert_id(stmt_); }

uint64_t Stmt::affected_rows() const { return mysql_stmt_affected_rows(stmt_); }
