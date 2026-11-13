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

/// 单连接、**可自愈**的 Redis 客户端。
///
/// 自愈(#288 实施中发现):此前只有一条 hiredis 连接且**从不重连** —— 只要连接因为
/// 网络抖动 / 容器重建 / 隧道重连而断掉,这个进程之后所有 Redis 操作都会永久失败
/// (在线键、发送配额、跨节点 owner 键与 publish 全部静默失效,直到进程重启)。
/// 现在每次操作前检查连接状态,发现已死就重连并**把本次命令重试一次**。
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
  /// 往频道发布一条消息(跨节点投递用)。Redis 故障时返回 false,不抛异常。
  ///
  /// Args:
  ///   channel: 频道名,如 ``im:deliver:edge``。
  ///   payload: 消息体(这里统一是 JSON)。
  ///
  /// Returns:
  ///   发布成功(至少有订阅者或已入队)返回 true。
  bool publish(const std::string& channel, const std::string& payload);
  bool ping();

 private:
  /// 若当前连接已失效(或从未建立)则重连。调用方必须已持 ``mutex_``。
  ///
  /// Returns:
  ///   连接可用返回 true。
  bool revive_locked();
  /// 用构造时记住的 URL 建一条新连接,并完成超时/口令/库选择。调用方必须已持锁。
  ///
  /// Returns:
  ///   成功返回 true;失败时 ``ctx_`` 为 nullptr 且 ``last_error_`` 有原因。
  bool connect_locked();
  /// 执行一条命令;连接失败时重连并**重试一次**。调用方必须已持锁。
  ///
  /// Args:
  ///   fn: 真正执行命令的闭包,返回 hiredis 的 reply(失败可能是 nullptr)。
  ///
  /// Returns:
  ///   命令的 reply(仍可能为 nullptr);调用方负责 freeReplyObject。
  template <typename Fn>
  redisReply* run_locked(Fn fn) {
    revive_locked();
    redisReply* reply = fn();
    if (reply == nullptr && revive_locked()) {
      reply = fn();
    }
    return reply;
  }

  redisContext* ctx_ = nullptr;
  std::mutex mutex_;
  /// 记住 URL 才能在断线后重建连接。
  std::string url_;
  std::string last_error_;
};
