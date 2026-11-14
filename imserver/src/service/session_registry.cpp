#include "service/session_registry.h"

#include <chrono>
#include <utility>
#include <vector>

#include "net/ws_server.h"
#include "store/redis_client.h"

namespace {

int64_t now_ms() {
  return std::chrono::duration_cast<std::chrono::milliseconds>(
             std::chrono::system_clock::now().time_since_epoch())
      .count();
}

/// 在线键 TTL:与「120 秒内有认证请求 = 在线」同口径(见 CLAUDE.md「在线状态是公开信息」)。
constexpr int kOnlineTtlSeconds = 90;

/// owner 键 TTL:连接归属的保活窗口。
///
/// 续期挂在 ``WsSession::refresh_online`` 的 30s 节流上,所以取 90s 留 3 倍余量:
/// 既不会每帧写 Redis,又能在节点异常退出后最迟 90 秒让归属自然过期,
/// 由客户端重连时重新登记。
constexpr int kOwnerTtlSeconds = 90;

}  // namespace

SessionRegistry::SessionRegistry(RedisClient& redis, std::string instance_id)
    : redis_(redis), instance_id_(std::move(instance_id)) {}

void SessionRegistry::set_remote_hooks(RemoteHooks hooks) { remote_ = std::move(hooks); }

void SessionRegistry::refresh_owner_keys(uint64_t uid) {
  if (instance_id_.empty()) {
    return;  // 单实例:不写 owner 键,行为与改造前一致
  }
  std::vector<std::string> cts;
  {
    const std::lock_guard<std::mutex> lock(mutex_);
    const auto it = sessions_.find(uid);
    if (it == sessions_.end()) {
      return;
    }
    for (const auto& entry : it->second) {
      if (!entry.second.expired()) {
        cts.push_back(entry.first);
      }
    }
  }
  // 锁外写 Redis:一次 Redis 抖动不该卡住所有 WS 帧处理。
  for (const auto& ct : cts) {
    redis_.setex("im:owner:" + std::to_string(uid) + ":" + ct, kOwnerTtlSeconds, instance_id_);
  }
}

void SessionRegistry::register_session(uint64_t uid, std::string_view ct,
                                       std::shared_ptr<WsSession> session) {
  std::shared_ptr<WsSession> old;
  bool replaced_local = false;
  {
    const std::lock_guard<std::mutex> lock(mutex_);
    auto& per_client = sessions_[uid];
    const auto it = per_client.find(std::string(ct));
    if (it != per_client.end()) {
      old = it->second.lock();
      replaced_local = old != nullptr && old.get() != session.get();
    }
    per_client[std::string(ct)] = session;
  }
  // 同类互顶:只踢同端。另一个端(一个 App + 一个网页)不受影响。
  if (replaced_local) {
    old->kick("multi_device");
  } else if (!replaced_local && remote_.kick != nullptr) {
    // 本地没有同端旧连接 —— 可能它连在**另一台** imserver 上,让那边把同端踢掉。
    remote_.kick(uid, ct, "multi_device", false);
  }
  if (!instance_id_.empty()) {
    redis_.setex("im:owner:" + std::to_string(uid) + ":" + std::string(ct), kOwnerTtlSeconds,
                 instance_id_);
  }
  touch_online(uid);
}

bool SessionRegistry::unregister(uint64_t uid, std::string_view ct, WsSession* session) {
  bool removed = false;
  {
    const std::lock_guard<std::mutex> lock(mutex_);
    const auto it = sessions_.find(uid);
    if (it == sessions_.end()) {
      return false;
    }
    const auto client_it = it->second.find(std::string(ct));
    if (client_it != it->second.end() && client_it->second.lock().get() == session) {
      it->second.erase(client_it);
      if (it->second.empty()) {
        sessions_.erase(it);
      }
      removed = true;
    }
  }
  // 只清自己这一端的归属键:另一端可能在别的节点上,不能一把删掉。
  if (removed && !instance_id_.empty()) {
    redis_.del("im:owner:" + std::to_string(uid) + ":" + std::string(ct));
  }
  return removed;
}

void SessionRegistry::kick(uint64_t uid, const std::string& reason) {
  local_kick(uid, reason);
  if (remote_.kick != nullptr) {
    remote_.kick(uid, std::string(), reason, true);
  }
}

void SessionRegistry::kick_client(uint64_t uid, std::string_view ct, const std::string& reason) {
  local_kick_client(uid, ct, reason);
  if (remote_.kick != nullptr) {
    remote_.kick(uid, ct, reason, false);
  }
}

bool SessionRegistry::send_to(uint64_t uid, const std::string& frame) {
  if (local_send_to(uid, frame)) {
    return true;
  }
  // 本地没有这个 uid 的连接 —— 可能连在另一台 imserver 上。
  if (remote_.send_to != nullptr) {
    return remote_.send_to(uid, frame);
  }
  return false;
}

void SessionRegistry::send_to_other_clients(uint64_t uid, const WsSession* except,
                                            const std::string& frame) {
  // 与 send_to 同样:锁内只收集目标,发送放到锁外(不该持着注册表的锁投递 io 任务)。
  std::vector<std::shared_ptr<WsSession>> targets;
  {
    const std::lock_guard<std::mutex> lock(mutex_);
    const auto it = sessions_.find(uid);
    if (it != sessions_.end()) {
      for (const auto& entry : it->second) {
        auto session = entry.second.lock();
        if (session != nullptr && session.get() != except) {
          targets.push_back(std::move(session));
        }
      }
    }
  }
  if (!targets.empty()) {
    for (const auto& session : targets) {
      session->send_raw(frame);
    }
    return;
  }
  // 本地一条都没有 → 交给远端。`except` 只可能是本地连接(远端不可能持有本进程的指针),
  // 所以发给远端「该 uid 的所有端」正是期望语义。
  if (remote_.send_to != nullptr) {
    remote_.send_to(uid, frame);
  }
}

bool SessionRegistry::local_send_to(uint64_t uid, const std::string& frame) {
  // 扇出:本人所有端都收到。锁内只收集目标,发送放到锁外 ——
  // send_raw 会往 io_context 投递任务,不该持着注册表的锁去做。
  std::vector<std::shared_ptr<WsSession>> targets;
  {
    const std::lock_guard<std::mutex> lock(mutex_);
    const auto it = sessions_.find(uid);
    if (it == sessions_.end()) {
      return false;
    }
    for (const auto& entry : it->second) {
      if (auto session = entry.second.lock()) {
        targets.push_back(std::move(session));
      }
    }
  }
  for (const auto& session : targets) {
    session->send_raw(frame);
  }
  return !targets.empty();
}

void SessionRegistry::local_send_to_client(uint64_t uid, std::string_view ct,
                                           const std::string& frame) {
  std::shared_ptr<WsSession> target;
  {
    const std::lock_guard<std::mutex> lock(mutex_);
    const auto it = sessions_.find(uid);
    if (it != sessions_.end()) {
      const auto client_it = it->second.find(std::string(ct));
      if (client_it != it->second.end()) {
        target = client_it->second.lock();
      }
    }
  }
  if (target != nullptr) {
    target->send_raw(frame);
  }
}

void SessionRegistry::local_kick(uint64_t uid, const std::string& reason) {
  // 踢全部端:封禁 / 注销账号用,语义与多端改造前一致。
  std::vector<std::shared_ptr<WsSession>> targets;
  {
    const std::lock_guard<std::mutex> lock(mutex_);
    const auto it = sessions_.find(uid);
    if (it != sessions_.end()) {
      for (const auto& entry : it->second) {
        if (auto session = entry.second.lock()) {
          targets.push_back(std::move(session));
        }
      }
    }
  }
  for (const auto& session : targets) {
    session->kick(reason);
  }
}

void SessionRegistry::local_kick_client(uint64_t uid, std::string_view ct,
                                        const std::string& reason) {
  // 踢单端:同类互顶 / 按端下线(登录时只踢本端的旧会话)。
  std::shared_ptr<WsSession> target;
  {
    const std::lock_guard<std::mutex> lock(mutex_);
    const auto it = sessions_.find(uid);
    if (it != sessions_.end()) {
      const auto client_it = it->second.find(std::string(ct));
      if (client_it != it->second.end()) {
        target = client_it->second.lock();
      }
    }
  }
  if (target != nullptr) {
    target->kick(reason);
  }
}

bool SessionRegistry::is_online(uint64_t uid) {
  const std::lock_guard<std::mutex> lock(mutex_);
  const auto it = sessions_.find(uid);
  if (it == sessions_.end()) {
    return false;
  }
  // 按 uid 计:任一端还活着就算在线(离线推送的判定依赖这一口径)。
  for (const auto& entry : it->second) {
    if (!entry.second.expired()) {
      return true;
    }
  }
  return false;
}

std::size_t SessionRegistry::online_count() {
  const std::lock_guard<std::mutex> lock(mutex_);
  std::size_t count = 0;
  for (const auto& per_uid : sessions_) {
    for (const auto& entry : per_uid.second) {
      if (!entry.second.expired()) {
        ++count;
        break;  // 一个 uid 只算一次:两端同时在线仍是 1 个在线用户
      }
    }
  }
  return count;
}

void SessionRegistry::touch_online(uint64_t uid) {
  redis_.setex("im:online:" + std::to_string(uid), kOnlineTtlSeconds,
               std::to_string(now_ms()));
  // 顺带续 owner 键;调用方(WsSession::refresh_online)已按 30s 节流。
  refresh_owner_keys(uid);
}
