#pragma once
#include <cstdint>
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
class SessionRegistry {
 public:
  explicit SessionRegistry(RedisClient& redis);

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
  ///   至少投给了一条活跃连接时返回 true(离线推送用它判「目标是否在线」)。
  bool send_to(uint64_t uid, const std::string& frame);
  /// 发给本人**除 `except` 之外**的所有端(跨端同步 `self_read` / `conversation_deleted` 用)。
  ///
  /// 与 `send_to` 的区别只有「跳过发起这条动作的连接」:本人另一台设备要收到,
  /// 发起端自己不需要(它的状态已经由本地操作更新,再收一遍是重复)。
  ///
  /// Args:
  ///   uid: 账号 id。
  ///   except: 不发的那条连接(通常是当前正在处理的会话)。
  ///   frame: 已序列化的帧。
  void send_to_other_clients(uint64_t uid, const WsSession* except, const std::string& frame);
  bool is_online(uint64_t uid);
  std::size_t online_count();
  void touch_online(uint64_t uid);

 private:
  /// 端类型 → 连接。用 map 而不是 vector:按端踢是 O(1),端数固定为 2。
  using ClientSessions = std::unordered_map<std::string, std::weak_ptr<WsSession>>;

  RedisClient& redis_;
  std::mutex mutex_;
  std::unordered_map<uint64_t, ClientSessions> sessions_;
};
