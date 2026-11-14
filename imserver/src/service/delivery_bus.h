#pragma once
#include <boost/asio/io_context.hpp>

#include <cstdint>
#include <memory>
#include <string>
#include <string_view>

#include "store/redis_subscriber.h"

class SessionRegistry;
class RedisClient;

/// 跨节点投递总线(#288)。
///
/// 职责:把 ``SessionRegistry`` 的「本地未命中」翻译成一次 Redis 发布,并把别的节点
/// 发来的帧回灌到本节点的会话表。``SessionRegistry`` 不认识 Redis 频道,``DeliveryBus``
/// 不认识 ``WsSession`` —— 两者的唯一接缝是 ``SessionRegistry::RemoteHooks``。
///
/// 频道与消息体:
///   * ``im:deliver:{instance_id}`` —— 定向投递,只发给指定节点;
///   * ``im:broadcast`` —— 踢全部端这类稀有事件,所有节点都收。
///   消息体统一是 JSON:``{"op":"send"|"kick","uid":N,"ct":"app|web|","frame":"...",
///   "reason":"...","all":true|false}``。
///
/// 降级:Redis 不可达时发布失败 —— 此时 ``send_to`` 返回 false,行为退化为
/// 「只投本节点」,与单实例一致;**绝不阻断发送路径**(与「Redis 故障不阻断聊天」同取向)。
class DeliveryBus {
 public:
  /// Args:
  ///   registry: 会话表(会在它上面挂 RemoteHooks)。
  ///   redis: 用于发布与查 owner 键的共享客户端。
  ///   instance_id: 本节点标识,同一集群内必须唯一(通常取容器 hostname)。
  ///   redis_url: 订阅连接用;与 ``redis`` 的连接分开。
  DeliveryBus(SessionRegistry& registry, RedisClient& redis, std::string instance_id,
              std::string redis_url);

  /// 挂钩子、起订阅线程。重复调用无副作用。
  ///
  /// Args:
  ///   io: 收到远端帧后要 post 回的 io_context(不得在订阅线程里直接碰会话)。
  void start(boost::asio::io_context& io);

  /// 摘钩子、停订阅线程、清本节点注册键。重复调用无副作用。
  void stop();

  /// 订阅连接当前是否在线(供日志/排障)。
  bool subscriber_connected() const;

 private:
  /// 定向发布:把消息发给拥有该 (uid, ct) 的节点。owner 就是本节点时直接返回 false。
  ///
  /// Args:
  ///   uid: 账号 id。
  ///   ct: 端类型;空表示「任一端」,会两端都查。
  ///   message: 已构造好的 JSON 消息。
  ///
  /// Returns:
  ///   至少向一个**其它**节点发布成功时返回 true。
  bool publish_to_owner(uint64_t uid, std::string_view ct, const std::string& message);

  /// 向所有节点广播(踢全部端用)。
  ///
  /// Args:
  ///   message: 已构造好的 JSON 消息。
  void broadcast(const std::string& message);

  /// 订阅线程收到消息后的入口:解析并 post 回 io_context 再落本地。
  ///
  /// Args:
  ///   payload: 消息体(JSON)。
  void on_remote_message(const std::string& payload);

  /// 在 io_context 线程里真正执行远端动作。
  ///
  /// Args:
  ///   payload: 消息体(JSON)。
  void apply_remote_message(const std::string& payload);

  SessionRegistry& registry_;
  RedisClient& redis_;
  std::string instance_id_;
  std::string redis_url_;
  std::shared_ptr<RedisSubscriber> subscriber_;
  boost::asio::io_context* io_ = nullptr;
};
