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
* 文件名称          src/migrate.cpp
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

#include "migrate.h"

#include <chrono>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <string>

#include "store/mysql_pool.h"
#include "util/log.h"

namespace {

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     取当前墙钟时间的毫秒时间戳
// 参数说明     无
// 返回参数     int64_t          自 Unix 纪元起的毫秒数
// 使用示例     const int64_t ts = now_ms();
// 备注信息     写入 im_schema_version.applied_at 供人工排查 不用于耗时统计
//-------------------------------------------------------------------------------------------------------------------
int64_t now_ms() {
  return std::chrono::duration_cast<std::chrono::milliseconds>(
             std::chrono::system_clock::now().time_since_epoch())
      .count();
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     读取整个迁移 SQL 文件的内容
// 参数说明     path             迁移 SQL 文件的完整路径
// 返回参数     std::string      文件全文 原样返回
// 使用示例     const std::string sql = read_file("/usr/local/share/imserver/migrations/001_init.sql");
// 备注信息     文件打不开抛 std::runtime_error 异常冒泡到 main 以非 0 退出
//-------------------------------------------------------------------------------------------------------------------
std::string read_file(const std::string& path) {
  std::ifstream input(path);
  if (!input) {
    throw std::runtime_error("cannot open migration file: " + path);
  }
  std::ostringstream buffer;
  buffer << input.rdbuf();
  return buffer.str();
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     判断某个迁移版本是否已登记
// 参数说明     lease            MySQL 连接租约
//              version          迁移版本号 从 1 开始
// 返回参数     bool             im_schema_version 中已有该版本返回 true
// 使用示例     version_applied(lease, 3);
// 备注信息     查询失败按未应用处理 宁可重跑也不静默跳过
//-------------------------------------------------------------------------------------------------------------------
bool version_applied(MysqlPool::Lease& lease, int version) {
  auto* result = lease.query("SELECT version FROM im_schema_version");
  if (result == nullptr) {
    return false;
  }
  bool found = false;
  while (MYSQL_ROW row = mysql_fetch_row(result)) {
    if (row[0] != nullptr && std::stoi(row[0]) == version) {
      found = true;
    }
  }
  mysql_free_result(result);
  return found;
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     按分号切分并逐条执行 SQL 文本
// 参数说明     lease            MySQL 连接租约
//              sql              迁移文件的完整文本
// 返回参数     void             无返回值
// 使用示例     apply_sql(lease, read_file(path));
// 备注信息     只按分号粗切 不支持存储过程等含分号的语句 空片段跳过 失败即抛异常
//-------------------------------------------------------------------------------------------------------------------
void apply_sql(MysqlPool::Lease& lease, const std::string& sql) {
  std::size_t start = 0;
  while (start < sql.size()) {
    const auto end = sql.find(';', start);
    const auto chunk = sql.substr(start, end == std::string::npos ? std::string::npos : end - start);
    const auto first = chunk.find_first_not_of(" \t\r\n");
    if (first != std::string::npos) {
      lease.query(chunk.substr(first));
    }
    if (end == std::string::npos) {
      break;
    }
    start = end + 1;
  }
}

/// 一条迁移:版本号 + SQL 文件名(相对 IM_MIGRATIONS_DIR)。
struct Migration {
  int version;
  const char* file;
};

/// 新增迁移只在这里加一行;版本号单调递增,已应用的跳过。
constexpr Migration kMigrations[] = {
    {1, "001_init.sql"},
    {2, "002_search_index.sql"},
    {3, "003_session_version.sql"},
    {4, "004_pair.sql"},
    {5, "005_device_session.sql"},
    {6, "006_quote.sql"},
    {7, "007_conversation_flags.sql"},
    {8, "008_message_hidden.sql"},
};

}  // namespace

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     执行所有未应用的迁移并登记版本
// 参数说明     cfg              配置对象 使用 mysql_dsn 与 migrations_dir
// 返回参数     void             无返回值
// 使用示例     run_migrations(cfg);
// 备注信息     先建 im_schema_version 表 已应用版本打 skipped 日志跳过 新增迁移只需在 kMigrations 加一行
//-------------------------------------------------------------------------------------------------------------------
void run_migrations(const Config& cfg) {
  MysqlPool pool(parse_mysql_dsn(cfg.mysql_dsn), 1);
  auto lease = pool.acquire();
  lease.query(
      "CREATE TABLE IF NOT EXISTS im_schema_version ("
      "version INT NOT NULL PRIMARY KEY, applied_at BIGINT NOT NULL"
      ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4");

  for (const auto& migration : kMigrations) {
    const std::string version = std::to_string(migration.version);
    if (version_applied(lease, migration.version)) {
      log_info("migrated", {{"version", version}, {"skipped", "true"}});
      continue;
    }
    apply_sql(lease, read_file(cfg.migrations_dir + "/" + migration.file));
    lease.query("INSERT INTO im_schema_version (version, applied_at) VALUES (" + version + ", " +
                std::to_string(now_ms()) + ")");
    log_info("migrated", {{"version", version}});
  }
}
