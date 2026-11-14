#pragma once
#include <cstdint>
#include <functional>
#include <memory>
#include <mutex>
#include <string>
#include <string_view>
#include <unordered_map>

class RedisClient;
class WsSession;

/// 在线会话表(多端在线 K-2:一个 uid 下按端各一条连接)。
///
/// 语义约定:
///   * 一个账号可以同时有 `app` 与 `web` 两条连接;**同类第二条连接互顶**(reason `multi_device`);
///   * `send_to` **扇出**到本人所有端;`kick` 踢**全部**端(封禁 / 注销);`kick_client` 只踢一端;
///   * `is_online` / `online_count` 仍**按 uid 计**(离线推送的「目标不在线」判定依赖它),
///     不按连接计 —— 任一端在线即该账号在线。
///
/// 多实例(#288):
///   `sessions_` 是**进程内**表,所以跨节点投递靠 `RemoteHooks` —— 本地未命中时把动作
///   交给钩子(由 `DeliveryBus` 发到拥有该连接的另一台 imserver)。钩子为空 = 单实例,
///   行为与改造前完全一致;远端帧回灌走 `local_*` 系列(不会再次跨节点转发)。
class SessionRegistry {
 public:
  /// 跨节点投递钩子。三项全可选:都为空即单实例行为。
  struct RemoteHooks {
    /// 把一帧投给该 uid 在**其它节点**上的所有端;确实投出去了返回 true。
    std::function<bool(uint64_t uid, const std::string& frame)> send_to;
    /// 把一帧投给该 uid 在**其它节点**上指定端;确实投出去了返回 true。
    std::function<bool(uint64_t uid, std::string_view ct, const std::string& frame)> send_to_client;
    /// 让其它节点踢掉该 uid 的端:`all_ends` 为真时踢全部端,否则只踢 `ct` 那一端。
    std::function<void(uint64_t uid, std::string_view ct, const std::string& reason, bool all_ends)>
        kick;
  };

  /// Args:
  ///   redis: 共享的 Redis 客户端(在线键、owner 键都走它)。
  ///   instance_id: 本节点标识;为空表示**不写 owner 键**(单实例,行为与改造前一致)。
  explicit SessionRegistry(RedisClient& redis, std::string instance_id = {});

  /// 设置跨节点投递钩子(启动时一次性设置)。
  ///
  /// Args:
  ///   hooks: 钩子集合;回调里不得持锁调用本表,`DeliveryBus` 内部已保证不死锁。
  void set_remote_hooks(RemoteHooks hooks);

  /// 注册一条已鉴权的连接;同端已有连接时把它踢下线。
  ///
  /// Args:
  ///   uid: 账号 id。
  ///   ct: 端类型 `app` / `web`。
  ///   session: 新连接。
  void register_session(uint64_t uid, std::string_view ct, std::shared_ptr<WsSession> session);
  /// 注销连接(只清掉仍指向该连接的那一条,避免误删新连接的登记)。
  ///
  /// Args:
  ///   uid: 账号 id。
  ///   ct: 端类型。
  ///   session: 正在关闭的连接。
  ///
  /// Returns:
  ///   该连接确实在表里并被移除时返回 true。
  bool unregister(uint64_t uid, std::string_view ct, WsSession* session);
  /// 踢掉该账号**所有端**的在线会话(封禁 / 注销账号)。
  ///
  /// Args:
  ///   uid: 账号 id。
  ///   reason: 踢下线原因,原样放进 `kicked` 帧。
  void kick(uint64_t uid, const std::string& reason);
  /// 只踢该账号**某一端**的在线会话(同类互顶 / 按端下线)。
  ///
  /// Args:
  ///   uid: 账号 id。
  ///   ct: 端类型 `app` / `web`。
  ///   reason: 踢下线原因。
  void kick_client(uint64_t uid, std::string_view ct, const std::string& reason);
  /// 向该账号**所有端**投递一帧。
  ///
  /// Args:
  ///   uid: 账号 id。
  ///   frame: 已序列化的帧。
  ///
  /// Returns:
  ///   至少投给了一条活跃连接(含远端节点上的)时返回 true(离线推送用它判「目标是否在线」)。
  bool send_to(uint64_t uid, const std::string& frame);
  /// 发给本人**除 `except` 之外**的所有端(跨端同步 `self_read` / `conversation_deleted` 用)。
  ///
  /// 与 `send_to` 的区别只有「跳过发起这条动作的连接」:本人另一台设备要收到,发起端自己
  /// 不需要(它的状态已经由本地操作更新,再收一遍是重复)。远端只能收到「发给该 uid 全部端」,
  /// 因为 `except` 一定是一条本地连接。
  ///
  /// Args:
  ///   uid: 账号 id。
  ///   except: 不发的那条连接(通常是当前正在处理的会话)。
  ///   frame: 已序列化的帧。
  void send_to_other_clients(uint64_t uid, const WsSession* except, const std::string& frame);

  /// 只投本节点(供 DeliveryBus 回灌远端帧,不会再次跨节点转发)。
  ///
  /// Args:
  ///   uid: 账号 id。
  ///   frame: 已序列化的帧。
  ///
  /// Returns:
  ///   本节点确实有该 uid 的活跃连接并投出去时返回 true。
  bool local_send_to(uint64_t uid, const std::string& frame);
  /// 只投本节点该 uid 的指定端。
  ///
  /// Args:
  ///   uid: 账号 id。
  ///   ct: 端类型。
  ///   frame: 已序列化的帧。
  void local_send_to_client(uint64_t uid, std::string_view ct, const std::string& frame);
  /// 只踢本节点的该 uid 全部端。
  ///
  /// Args:
  ///   uid: 账号 id。
  ///   reason: 踢下线原因。
  void local_kick(uint64_t uid, const std::string& reason);
  /// 只踢本节点的该 uid 指定端。
  ///
  /// Args:
  ///   uid: 账号 id。
  ///   ct: 端类型。
  ///   reason: 踢下线原因。
  void local_kick_client(uint64_t uid, std::string_view ct, const std::string& reason);

  bool is_online(uint64_t uid);
  std::size_t online_count();
  void touch_online(uint64_t uid);

 private:
  /// 端类型 → 连接。用 map 而不是 vector:按端踢是 O(1),端数固定为 2。
  using ClientSessions = std::unordered_map<std::string, std::weak_ptr<WsSession>>;

  /// 把该 uid 每个本地端的 owner 键写成 instance_id。
  ///
  /// 实现上「先在锁内收集端类型,再在锁外写 Redis」—— 不持注册表的锁做网络往返,
  /// 否则一次 Redis 抖动会卡住所有 WS 帧处理。
  ///
  /// Args:
  ///   uid: 账号 id。
  void refresh_owner_keys(uint64_t uid);

  RedisClient& redis_;
  std::string instance_id_;
  RemoteHooks remote_;
  std::mutex mutex_;
  std::unordered_map<uint64_t, ClientSessions> sessions_;
};
