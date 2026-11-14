/*********************************************************************************************************************
* chat_app 自建 IM 服务端（imserver）是本项目唯一的 IM 后端，C++20 实现，对外提供 WebSocket :9100 与 HTTP :9101
* Copyright (c) 2026 shiliu153
*
* 本文件是 chat_app 自建 IM 服务端的一部分
*
* 额外注明：
* 本文件使用 MIT 开源许可证协议 许可申明英文版见仓库根目录 LICENSE 文件
* 欢迎各位使用并传播本程序 但修改内容时必须保留作者的版权声明（即本声明）
*
* 文件名称          src/store/stmt.cpp
* 项目名称          chat_app / imserver
* 公司名称          个人项目（shiliu153）
* 版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
* 开发环境          CMake 3.22 + g++ (C++20) Linux x86_64
* 适用平台          Linux x86_64 服务端
* 仓库地址          https://github.com/shiliu153/chatapp
*
* 修改记录
* 日期              作者               备注
* 2026-11-14        shiliu153          补齐文件头与函数注释
********************************************************************************************************************/
#include "store/stmt.h"

#include <mutex>
#include <unordered_map>
#include <utility>

namespace {

// 每条写语句原本要 prepare + execute + close 三次往返。连接是独占租用的,
// 所以按 (连接, SQL) 缓存 prepared statement,热路径只剩 execute 一次往返。
std::mutex g_cache_mu;
std::unordered_map<MYSQL*, std::unordered_map<std::string, MYSQL_STMT*>> g_cache;

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     按连接与 SQL 取或新建预编译语句
// 参数说明     conn             独占连接
//              sql              带占位符的 SQL 文本
// 返回参数     MYSQL_STMT*      缓存的语句句柄
// 使用示例     MYSQL_STMT* stmt = acquire_stmt(conn, "DELETE FROM im_user WHERE user_id=?");
// 备注信息     全局锁内完成查找与 prepare 失败抛 MysqlError 首次成功后按 (连接,SQL) 缓存
//-------------------------------------------------------------------------------------------------------------------
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     关闭某条连接上缓存的所有 prepared statement
// 参数说明     conn             即将销毁的连接
// 返回参数     void             无返回值
// 使用示例     clear_stmt_cache(conn);
// 备注信息     加全局锁 逐条 mysql_stmt_close 后删除该连接条目 连接不在缓存时直接返回
//-------------------------------------------------------------------------------------------------------------------
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     构造预编译语句 命中缓存则复用
// 参数说明     conn             独占使用的连接
//              sql              带 ? 占位符的 SQL
// 返回参数     void             无返回值
// 使用示例     Stmt stmt(lease.get(), "DELETE FROM im_user WHERE user_id=?");
// 备注信息     各参数缓冲预留 16 个槽位 超过后按需扩容 构造期间可能抛 MysqlError
//-------------------------------------------------------------------------------------------------------------------
Stmt::Stmt(MYSQL* conn, const std::string& sql) : stmt_(acquire_stmt(conn, sql)) {
  binds_.reserve(16);
  u64_.reserve(16);
  i32_.reserve(16);
  strings_.reserve(16);
  lengths_.reserve(16);
  nulls_.reserve(16);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     析构语句对象 不关闭底层 statement
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     { Stmt stmt(conn, sql); }
// 备注信息     = default 底层 MYSQL_STMT 由 clear_stmt_cache 统一关闭
//-------------------------------------------------------------------------------------------------------------------
Stmt::~Stmt() = default;

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     扩容参数缓冲并重置指定位置
// 参数说明     index            从 0 开始的占位符序号
// 返回参数     void             无返回值
// 使用示例     ensure(0);  // 仅在类内部调用
// 备注信息     六个 vector 同步 resize 到 index+1 并把该位置的 MYSQL_BIND 与 null 标记清零
//-------------------------------------------------------------------------------------------------------------------
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     绑定无符号 64 位整数参数
// 参数说明     index            从 0 开始的占位符序号
//              value            参数值
// 返回参数     void             无返回值
// 使用示例     stmt.bind_uint(0, uid);
// 备注信息     按 MYSQL_TYPE_LONGLONG 加 is_unsigned 绑定 缓冲区指向对象内部 vector
//-------------------------------------------------------------------------------------------------------------------
void Stmt::bind_uint(int index, uint64_t value) {
  ensure(index);
  auto& bind = binds_[static_cast<std::size_t>(index)];
  u64_[static_cast<std::size_t>(index)] = value;
  bind.buffer_type = MYSQL_TYPE_LONGLONG;
  bind.buffer = &u64_[static_cast<std::size_t>(index)];
  bind.is_unsigned = 1;
  bind.is_null = reinterpret_cast<bool*>(&nulls_[static_cast<std::size_t>(index)]);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     绑定有符号 32 位整数参数
// 参数说明     index            从 0 开始的占位符序号
//              value            参数值
// 返回参数     void             无返回值
// 使用示例     stmt.bind_int(0, level);
// 备注信息     按 MYSQL_TYPE_LONG 绑定 缓冲区指向对象内部 vector
//-------------------------------------------------------------------------------------------------------------------
void Stmt::bind_int(int index, int value) {
  ensure(index);
  auto& bind = binds_[static_cast<std::size_t>(index)];
  i32_[static_cast<std::size_t>(index)] = value;
  bind.buffer_type = MYSQL_TYPE_LONG;
  bind.buffer = &i32_[static_cast<std::size_t>(index)];
  bind.is_null = reinterpret_cast<bool*>(&nulls_[static_cast<std::size_t>(index)]);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     绑定字符串参数
// 参数说明     index            从 0 开始的占位符序号
//              value            参数值
// 返回参数     void             无返回值
// 使用示例     stmt.bind_string(1, "小明");
// 备注信息     值拷贝进对象内部 vector 长度另存 覆盖 execute 全生命周期
//-------------------------------------------------------------------------------------------------------------------
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     把参数绑定为 SQL NULL
// 参数说明     index            从 0 开始的占位符序号
// 返回参数     void             无返回值
// 使用示例     stmt.bind_null(2);
// 备注信息     只置 is_null 标记 覆盖此前对该位置的 bind
//-------------------------------------------------------------------------------------------------------------------
void Stmt::bind_null(int index) {
  ensure(index);
  nulls_[static_cast<std::size_t>(index)] = 1;
  binds_[static_cast<std::size_t>(index)].is_null =
      reinterpret_cast<bool*>(&nulls_[static_cast<std::size_t>(index)]);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     绑定全部参数并执行语句
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     stmt.execute();
// 备注信息     先 mysql_stmt_free_result 清上次结果 绑定或执行失败抛 MysqlError 并带 mysql_stmt_errno
//-------------------------------------------------------------------------------------------------------------------
void Stmt::execute() {
  mysql_stmt_free_result(stmt_);
  if (mysql_stmt_bind_param(stmt_, binds_.data()) != 0) {
    throw MysqlError(mysql_stmt_errno(stmt_), mysql_stmt_error(stmt_));
  }
  if (mysql_stmt_execute(stmt_) != 0) {
    throw MysqlError(mysql_stmt_errno(stmt_), mysql_stmt_error(stmt_));
  }
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     取自增主键回填值
// 参数说明     无
// 返回参数     uint64_t         最后插入行的 AUTO_INCREMENT
// 使用示例     uint64_t id = stmt.insert_id();
// 备注信息     仅 INSERT 有意义 非自增表返回 0
//-------------------------------------------------------------------------------------------------------------------
uint64_t Stmt::insert_id() const { return mysql_stmt_insert_id(stmt_); }

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     取上次执行影响的行数
// 参数说明     无
// 返回参数     uint64_t         受影响行数
// 使用示例     uint64_t n = stmt.affected_rows();
// 备注信息     UPDATE 未改变值时默认返回 0 行
//-------------------------------------------------------------------------------------------------------------------
uint64_t Stmt::affected_rows() const { return mysql_stmt_affected_rows(stmt_); }
