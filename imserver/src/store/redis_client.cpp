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
* 文件名称          src/store/redis_client.cpp
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
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     把 %XX 转义解码成原始字节
// 参数说明     text             含 %XX 的字符串
// 返回参数     std::string      解码后的字符串
// 使用示例     percent_decode("%40");
// 备注信息     非法转义原样保留 只处理两位十六进制 末尾不足三字符的 % 不解析
//-------------------------------------------------------------------------------------------------------------------
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     解析 Redis URL 成连接参数
// 参数说明     url              形如 redis://[user:pass@]host:port/db
// 返回参数     RedisUrlParts     主机 端口 库号 账号 口令
// 使用示例     parse_redis_url("redis://:pass@127.0.0.1:6379/2");
// 备注信息     前缀必须是 redis:// 按最后一个 @ 切 userinfo 再按最后一个 : 切端口 非法抛 std::invalid_argument
//-------------------------------------------------------------------------------------------------------------------
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     构造客户端 连接并按需鉴权选库
// 参数说明     url              Redis URL 口令可选 库号非 0 时执行 SELECT
// 返回参数     void             无返回值
// 使用示例     RedisClient client("redis://127.0.0.1:6379/2");
// 备注信息     口令非空先 AUTH 有用户名用两参数形式 库号非 0 再 SELECT 失败都 redisFree 后抛 std::runtime_error
//-------------------------------------------------------------------------------------------------------------------
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     析构客户端 释放连接上下文
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     { RedisClient client(url); }
// 备注信息     ctx_ 非空才 redisFree 构造抛异常时不会留下半开连接
//-------------------------------------------------------------------------------------------------------------------
RedisClient::~RedisClient() {
  if (ctx_ != nullptr) {
    redisFree(ctx_);
  }
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     写入带过期时间的字符串
// 参数说明     key              键名
//              ttl_seconds      过期秒数
//              value            字符串值
// 返回参数     bool             回复不是错误类型返回 true
// 使用示例     client.setex("im:token:42", 3600, "1");
// 备注信息     全程持 mutex_ 单连接非线程安全 回复对象用完即 freeReplyObject
//-------------------------------------------------------------------------------------------------------------------
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     读取字符串值
// 参数说明     key              键名
// 返回参数     std::optional<std::string>     键不存在或命令出错时为空
// 使用示例     auto value = client.get("im:token:42");
// 备注信息     错误回复与 NIL 都返回空 optional 有值时按 len 取串 持锁执行
//-------------------------------------------------------------------------------------------------------------------
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     删除键
// 参数说明     key              键名
// 返回参数     bool             回复类型为整数返回 true
// 使用示例     client.del("im:token:42");
// 备注信息     键不存在时回复仍是整数 因此 true 只代表命令执行成功
//-------------------------------------------------------------------------------------------------------------------
bool RedisClient::del(const std::string& key) {
  const std::lock_guard<std::mutex> lock(mutex_);
  auto* reply = static_cast<redisReply*>(redisCommand(ctx_, "DEL %s", key.c_str()));
  const bool ok = reply != nullptr && reply->type == REDIS_REPLY_INTEGER;
  if (reply != nullptr) {
    freeReplyObject(reply);
  }
  return ok;
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     自增计数
// 参数说明     key              键名
// 返回参数     long long        自增后的值 出错返回 0
// 使用示例     long long n = client.incr("im:rate:42");
// 备注信息     回复类型非整数一律返回 0 出错与真实值 0 无法区分
//-------------------------------------------------------------------------------------------------------------------
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     探测连接可用性
// 参数说明     无
// 返回参数     bool             回复类型为状态返回 true
// 使用示例     client.ping();
// 备注信息     持锁执行 失败只返回 false 不重连 重连由调用方重建客户端
//-------------------------------------------------------------------------------------------------------------------
bool RedisClient::ping() {
  const std::lock_guard<std::mutex> lock(mutex_);
  auto* reply = static_cast<redisReply*>(redisCommand(ctx_, "PING"));
  const bool ok = reply != nullptr && reply->type == REDIS_REPLY_STATUS;
  if (reply != nullptr) {
    freeReplyObject(reply);
  }
  return ok;
}
