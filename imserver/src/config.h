#pragma once
#include <cstddef>
#include <map>
#include <string>
#include <vector>

struct MysqlDsn {
  std::string user;
  std::string password;
  std::string host = "127.0.0.1";
  int port = 3306;
  std::string database;
};

MysqlDsn parse_mysql_dsn(const std::string& dsn);

struct Config {
  std::string listen_ws = "127.0.0.1:9100";
  std::string listen_http = "127.0.0.1:9101";
  std::string mysql_dsn;
  std::string redis_url = "redis://127.0.0.1:6379/2";
  std::string jwt_secret;
  std::string internal_secret;
  std::string migrations_dir = "/usr/local/share/imserver/migrations";
  std::vector<std::string> allowed_origins;
  int io_threads = 2;
  int db_threads = 4;
  int db_pool = 8;
  int db_idle_ping_ms = 5000;
  int max_conn_per_ip = 20;
  double auth_rate_per_sec = 1.0;
  double auth_burst = 60.0;
  // 单账号每分钟发送上限(跨连接共享,Redis 计数);<=0 表示关闭
  int send_per_minute = 120;
  std::size_t max_frame = 8192;
  std::size_t text_max = 2000;
  // 聊天图片 URL 前缀(例:https://<host>/media/chat/);必填,缺失则启动失败
  std::string media_prefix;
  // 聊天图片签名密钥与有效期;密钥为空 = 不签名(仅开发环境)
  std::string media_sign_secret;
  int media_sign_ttl = 86400;

  static Config from_env();
  static Config from_map(const std::map<std::string, std::string>& env);
};
