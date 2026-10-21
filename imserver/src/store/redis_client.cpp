#include "store/redis_client.h"

#include <stdexcept>
#include <string>

namespace {

struct UrlParts {
  std::string host;
  int port = 6379;
  int db = 0;
};

UrlParts parse_redis_url(const std::string& url) {
  constexpr const char* kPrefix = "redis://";
  if (url.rfind(kPrefix, 0) != 0) {
    throw std::invalid_argument("redis url must start with redis://");
  }
  auto rest = url.substr(std::string(kPrefix).size());
  UrlParts parts;

  const auto slash = rest.find('/');
  if (slash != std::string::npos) {
    const auto db_text = rest.substr(slash + 1);
    if (!db_text.empty()) {
      try {
        parts.db = std::stoi(db_text);
      } catch (const std::exception&) {
        throw std::invalid_argument("invalid redis db");
      }
    }
    rest = rest.substr(0, slash);
  }

  const auto colon = rest.rfind(':');
  if (colon == std::string::npos) {
    parts.host = rest;
  } else {
    parts.host = rest.substr(0, colon);
    try {
      parts.port = std::stoi(rest.substr(colon + 1));
    } catch (const std::exception&) {
      throw std::invalid_argument("invalid redis port");
    }
  }
  if (parts.host.empty() || parts.port <= 0 || parts.db < 0) {
    throw std::invalid_argument("incomplete redis url");
  }
  return parts;
}

}  // namespace

RedisClient::RedisClient(const std::string& url) {
  const auto parts = parse_redis_url(url);
  ctx_ = redisConnect(parts.host.c_str(), parts.port);
  if (ctx_ == nullptr || ctx_->err) {
    const std::string error = ctx_ == nullptr ? "redisConnect returned null" : ctx_->errstr;
    if (ctx_ != nullptr) {
      redisFree(ctx_);
      ctx_ = nullptr;
    }
    throw std::runtime_error("redis connect failed: " + error);
  }
  timeval timeout{2, 0};
  redisSetTimeout(ctx_, timeout);

  if (parts.db != 0) {
    auto* reply = static_cast<redisReply*>(redisCommand(ctx_, "SELECT %d", parts.db));
    const bool ok = reply != nullptr && reply->type != REDIS_REPLY_ERROR;
    if (reply != nullptr) {
      freeReplyObject(reply);
    }
    if (!ok) {
      redisFree(ctx_);
      ctx_ = nullptr;
      throw std::runtime_error("redis SELECT failed");
    }
  }
}

RedisClient::~RedisClient() {
  if (ctx_ != nullptr) {
    redisFree(ctx_);
  }
}

bool RedisClient::setex(const std::string& key, int ttl_seconds, const std::string& value) {
  const std::lock_guard<std::mutex> lock(mutex_);
  auto* reply = static_cast<redisReply*>(
      redisCommand(ctx_, "SETEX %s %d %s", key.c_str(), ttl_seconds, value.c_str()));
  const bool ok = reply != nullptr && reply->type != REDIS_REPLY_ERROR;
  if (reply != nullptr) {
    freeReplyObject(reply);
  }
  return ok;
}

std::optional<std::string> RedisClient::get(const std::string& key) {
  const std::lock_guard<std::mutex> lock(mutex_);
  auto* reply = static_cast<redisReply*>(redisCommand(ctx_, "GET %s", key.c_str()));
  if (reply == nullptr || reply->type == REDIS_REPLY_ERROR) {
    if (reply != nullptr) {
      freeReplyObject(reply);
    }
    return std::nullopt;
  }
  if (reply->type == REDIS_REPLY_NIL) {
    freeReplyObject(reply);
    return std::nullopt;
  }
  std::optional<std::string> result;
  if (reply->str != nullptr) {
    result = std::string(reply->str, static_cast<std::size_t>(reply->len));
  }
  freeReplyObject(reply);
  return result;
}

bool RedisClient::del(const std::string& key) {
  const std::lock_guard<std::mutex> lock(mutex_);
  auto* reply = static_cast<redisReply*>(redisCommand(ctx_, "DEL %s", key.c_str()));
  const bool ok = reply != nullptr && reply->type == REDIS_REPLY_INTEGER;
  if (reply != nullptr) {
    freeReplyObject(reply);
  }
  return ok;
}

long long RedisClient::incr(const std::string& key) {
  const std::lock_guard<std::mutex> lock(mutex_);
  auto* reply = static_cast<redisReply*>(redisCommand(ctx_, "INCR %s", key.c_str()));
  long long value = 0;
  if (reply != nullptr && reply->type == REDIS_REPLY_INTEGER) {
    value = reply->integer;
  }
  if (reply != nullptr) {
    freeReplyObject(reply);
  }
  return value;
}

bool RedisClient::ping() {
  const std::lock_guard<std::mutex> lock(mutex_);
  auto* reply = static_cast<redisReply*>(redisCommand(ctx_, "PING"));
  const bool ok = reply != nullptr && reply->type == REDIS_REPLY_STATUS;
  if (reply != nullptr) {
    freeReplyObject(reply);
  }
  return ok;
}
