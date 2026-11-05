#pragma once
#include <hiredis/hiredis.h>

#include <mutex>
#include <optional>
#include <string>

/// Redis 连接参数,由 `redis://[user][:password]@host:port/db` 解析而来。
///
/// E-6②:此前不支持口令,生产只能让 Redis 裸奔(任何能连到 6379 的进程都能改数据)。
/// 现在支持两种写法:
///   - `redis://:pass@host:6379/2`      —— 默认用户 + 口令(最常见)
///   - `redis://user:pass@host:6379/2`  —— Redis 6 ACL 用户名 + 口令
/// 口令里的特殊字符用百分号编码(如 `@` 写成 `%40`),解析时会解码。
struct RedisUrlParts {
  std::string host;
  int port = 6379;
  int db = 0;
  std::string user;
  std::string password;
};

/// 解析 Redis URL。非法格式抛 ``std::invalid_argument``。
///
/// Args:
///   url: 形如 ``redis://host:6379/0`` 的地址。
///
/// Returns:
///   解析结果(未给口令时 ``password`` 为空,构造函数不会发 ``AUTH``)。
RedisUrlParts parse_redis_url(const std::string& url);

class RedisClient {
 public:
  explicit RedisClient(const std::string& url);
  ~RedisClient();
  RedisClient(const RedisClient&) = delete;
  RedisClient& operator=(const RedisClient&) = delete;

  bool setex(const std::string& key, int ttl_seconds, const std::string& value);
  std::optional<std::string> get(const std::string& key);
  bool del(const std::string& key);
  long long incr(const std::string& key);
  bool ping();

 private:
  redisContext* ctx_ = nullptr;
  std::mutex mutex_;
};
