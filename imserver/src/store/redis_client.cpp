#include "store/redis_client.h"

#include <cctype>
#include <stdexcept>
#include <string>

namespace {

/// 把 ``%XX`` 解码成单个字节;非法转义原样保留。
///
/// Args:
///   text: 待解码的字符串。
///
/// Returns:
///   解码后的字符串。
std::string percent_decode(const std::string& text) {
  std::string out;
  out.reserve(text.size());
  for (std::size_t i = 0; i < text.size(); ++i) {
    const bool escaped = text[i] == '%' && i + 2 < text.size() &&
                         std::isxdigit(static_cast<unsigned char>(text[i + 1])) != 0 &&
                         std::isxdigit(static_cast<unsigned char>(text[i + 2])) != 0;
    if (escaped) {
      out.push_back(static_cast<char>(std::stoi(text.substr(i + 1, 2), nullptr, 16)));
      i += 2;
    } else {
      out.push_back(text[i]);
    }
  }
  return out;
}

}  // namespace

RedisUrlParts parse_redis_url(const std::string& url) {
  constexpr const char* kPrefix = "redis://";
  if (url.rfind(kPrefix, 0) != 0) {
    throw std::invalid_argument("redis url must start with redis://");
  }
  const auto rest = url.substr(std::string(kPrefix).size());
  RedisUrlParts parts;

  // userinfo 先按最后一个 '@' 切掉:口令里可能含 '/'、冒号,但 '@' 必须是分隔符
  // (含 '@' 的口令要写成 %40)。
  std::string authority = rest;
  const auto at = rest.rfind('@');
  if (at != std::string::npos) {
    const auto userinfo = rest.substr(0, at);
    authority = rest.substr(at + 1);
    const auto colon = userinfo.find(':');
    if (colon == std::string::npos) {
      // 少见写法 `redis://pass@host`:整段当口令
      parts.password = percent_decode(userinfo);
    } else {
      // 常见写法 `redis://:pass@host` 的 userinfo 是 `:pass` → user 为空、password 正确
      parts.user = percent_decode(userinfo.substr(0, colon));
      parts.password = percent_decode(userinfo.substr(colon + 1));
    }
  }

  const auto slash = authority.find('/');
  if (slash != std::string::npos) {
    const auto db_text = authority.substr(slash + 1);
    if (!db_text.empty()) {
      try {
        parts.db = std::stoi(db_text);
      } catch (const std::exception&) {
        throw std::invalid_argument("invalid redis db");
      }
    }
    authority = authority.substr(0, slash);
  }

  const auto colon = authority.rfind(':');
  if (colon == std::string::npos) {
    parts.host = authority;
  } else {
    parts.host = authority.substr(0, colon);
    try {
      parts.port = std::stoi(authority.substr(colon + 1));
    } catch (const std::exception&) {
      throw std::invalid_argument("invalid redis port");
    }
  }
  if (parts.host.empty() || parts.port <= 0 || parts.db < 0) {
    throw std::invalid_argument("incomplete redis url");
  }
  return parts;
}

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

  // E-6②:配了口令就先 AUTH(Redis 6 起支持 `AUTH user pass`,老版本只认 `AUTH pass`)。
  if (!parts.password.empty()) {
    auto* reply = parts.user.empty()
                      ? static_cast<redisReply*>(redisCommand(
                            ctx_, "AUTH %s", parts.password.c_str()))
                      : static_cast<redisReply*>(redisCommand(
                            ctx_, "AUTH %s %s", parts.user.c_str(), parts.password.c_str()));
    const bool ok = reply != nullptr && reply->type != REDIS_REPLY_ERROR;
    std::string message;
    if (!ok && reply != nullptr && reply->str != nullptr) {
      message = reply->str;
    }
    if (reply != nullptr) {
      freeReplyObject(reply);
    }
    if (!ok) {
      redisFree(ctx_);
      ctx_ = nullptr;
      throw std::runtime_error("redis AUTH failed" + (message.empty() ? "" : ": " + message));
    }
  }

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

bool RedisClient::publish(const std::string& channel, const std::string& payload) {
  const std::lock_guard<std::mutex> lock(mutex_);
  auto* reply = static_cast<redisReply*>(
      redisCommand(ctx_, "PUBLISH %s %s", channel.c_str(), payload.c_str()));
  // PUBLISH 返回收到消息的订阅者数;0 也是「发成功了、只是没人听」。
  const bool ok = reply != nullptr && reply->type == REDIS_REPLY_INTEGER;
  if (reply != nullptr) {
    freeReplyObject(reply);
  }
  return ok;
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
