#pragma once
#include <mysql/mysql.h>

#include <stdexcept>
#include <string>
#include <vector>

class MysqlError : public std::runtime_error {
 public:
  MysqlError(int code, const std::string& message) : std::runtime_error(message), code_(code) {}
  int code() const { return code_; }

 private:
  int code_;
};

/// 关闭某条连接上缓存的所有 prepared statement(连接销毁前调用)。
void clear_stmt_cache(MYSQL* conn);

class Stmt {
 public:
  Stmt(MYSQL* conn, const std::string& sql);
  ~Stmt();
  Stmt(const Stmt&) = delete;
  Stmt& operator=(const Stmt&) = delete;

  void bind_uint(int index, uint64_t value);
  void bind_int(int index, int value);
  void bind_string(int index, const std::string& value);
  void bind_null(int index);

  void execute();
  uint64_t insert_id() const;
  uint64_t affected_rows() const;

 private:
  void ensure(int index);

  MYSQL_STMT* stmt_ = nullptr;
  std::vector<MYSQL_BIND> binds_;
  std::vector<uint64_t> u64_;
  std::vector<int> i32_;
  std::vector<std::string> strings_;
  std::vector<unsigned long> lengths_;
  std::vector<char> nulls_;
};
