#include "migrate.h"

#include <chrono>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <string>

#include "store/mysql_pool.h"
#include "util/log.h"

namespace {

int64_t now_ms() {
  return std::chrono::duration_cast<std::chrono::milliseconds>(
             std::chrono::system_clock::now().time_since_epoch())
      .count();
}

std::string read_file(const std::string& path) {
  std::ifstream input(path);
  if (!input) {
    throw std::runtime_error("cannot open migration file: " + path);
  }
  std::ostringstream buffer;
  buffer << input.rdbuf();
  return buffer.str();
}

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

}  // namespace

void run_migrations(const Config& cfg) {
  MysqlPool pool(parse_mysql_dsn(cfg.mysql_dsn), 1);
  auto lease = pool.acquire();
  lease.query(
      "CREATE TABLE IF NOT EXISTS im_schema_version ("
      "version INT NOT NULL PRIMARY KEY, applied_at BIGINT NOT NULL"
      ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4");

  if (version_applied(lease, 1)) {
    log_info("migrated", {{"version", "1"}, {"skipped", "true"}});
    return;
  }

  const std::string path = cfg.migrations_dir + "/001_init.sql";
  apply_sql(lease, read_file(path));
  lease.query("INSERT INTO im_schema_version (version, applied_at) VALUES (1, " +
              std::to_string(now_ms()) + ")");
  log_info("migrated", {{"version", "1"}});
}
