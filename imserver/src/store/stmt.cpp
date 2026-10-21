#include "store/stmt.h"

#include <utility>

Stmt::Stmt(MYSQL* conn, const std::string& sql) {
  stmt_ = mysql_stmt_init(conn);
  if (stmt_ == nullptr) {
    throw MysqlError(0, "mysql_stmt_init failed");
  }
  if (mysql_stmt_prepare(stmt_, sql.data(), static_cast<unsigned long>(sql.size())) != 0) {
    const int code = mysql_stmt_errno(stmt_);
    const std::string message = mysql_stmt_error(stmt_);
    mysql_stmt_close(stmt_);
    stmt_ = nullptr;
    throw MysqlError(code, "mysql_stmt_prepare failed: " + message);
  }
  binds_.reserve(16);
  u64_.reserve(16);
  i32_.reserve(16);
  strings_.reserve(16);
  lengths_.reserve(16);
  nulls_.reserve(16);
}

Stmt::~Stmt() {
  if (stmt_ != nullptr) {
    mysql_stmt_close(stmt_);
  }
}

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
  if (mysql_stmt_bind_param(stmt_, binds_.data()) != 0) {
    throw MysqlError(mysql_stmt_errno(stmt_), mysql_stmt_error(stmt_));
  }
  if (mysql_stmt_execute(stmt_) != 0) {
    throw MysqlError(mysql_stmt_errno(stmt_), mysql_stmt_error(stmt_));
  }
}

uint64_t Stmt::insert_id() const { return mysql_stmt_insert_id(stmt_); }

uint64_t Stmt::affected_rows() const { return mysql_stmt_affected_rows(stmt_); }
