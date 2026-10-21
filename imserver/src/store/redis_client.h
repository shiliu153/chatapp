#pragma once
#include <hiredis/hiredis.h>

#include <mutex>
#include <optional>
#include <string>

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
