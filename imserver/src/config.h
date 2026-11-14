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
  /// 本节点标识(#288 多实例)。空 = 单实例,不写 owner 键、不订阅跨节点频道。
  /// 由 `IM_INSTANCE_ID` 提供;缺省取 hostname(容器里就是容器 id)。
  std::string instance_id;
  std::string jwt_secret;
  std::string internal_secret;
  std::string migrations_dir = "/usr/local/share/imserver/migrations";
  std::vector<std::string> allowed_origins;
  // 可信代理网段:只有直连对端命中这些地址,才采信它带来的 X-Real-IP(L9)
  std::vector<std::string> trusted_proxies{"127.0.0.1", "::1"};
  // 内部管理接口(/internal/*)允许的来源网段(H-1)。容器部署下 Django 的源地址
  // 不是回环,只写回环会让 user_sig/配对/封禁全部 403;这里显式配置来源网段,
  // 仍保留 HMAC 校验。默认只允许本机,与旧行为一致。
  std::vector<std::string> internal_allow{"127.0.0.1", "::1"};
  // 监听非回环地址必须显式开启(默认只允许 127.0.0.1 / ::1)
  bool allow_public_bind = false;
  int io_threads = 2;
  int db_threads = 4;
  int db_pool = 8;
  int db_idle_ping_ms = 5000;
  /// 启动时连不上 MySQL 的最长等待(毫秒)。>0 表示在这段时间内每 2 秒重试一次,
  /// 避免 DB 尚未就绪时进程直接退出、陷入 Docker 指数退避的 crash loop(P1-3)。
  int db_connect_wait_ms = 60000;
  int max_conn_per_ip = 20;
  double auth_rate_per_sec = 1.0;
  double auth_burst = 60.0;
  // 单账号每分钟发送上限(跨连接共享,Redis 计数);<=0 表示关闭
  int send_per_minute = 120;
  std::size_t max_frame = 8192;
  std::size_t text_max = 2000;
  /// 聊天文字敏感词表路径(批次 Q)。空 / 文件不存在 = 不启用(只打 warning)。
  std::string sensitive_words_file = "/usr/local/share/imserver/data/sensitive_words.txt";
  // 聊天图片 URL 前缀(例:https://<host>/media/chat/);必填,缺失则启动失败
  std::string media_prefix;
  // 聊天图片签名密钥与有效期;密钥为空 = 不签名(仅开发环境)
  std::string media_sign_secret;
  int media_sign_ttl = 86400;
  /// 离线新消息推送的目标地址(Django 内部事件入口)。空 = 关闭(C-1)。
  /// 例:`http://127.0.0.1:8000/internal/push/new-message`
  std::string push_url;
  /// 单次推送事件的 HTTP 超时(毫秒)。
  int push_timeout_ms = 2000;
  /// 推送事件队列长度;满了就丢(绝不反压发送路径)。
  std::size_t push_queue = 256;

  static Config from_env();
  static Config from_map(const std::map<std::string, std::string>& env);
};
