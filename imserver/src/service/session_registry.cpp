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

}  // namespace

SessionRegistry::SessionRegistry(RedisClient& redis) : redis_(redis) {}

void SessionRegistry::register_session(uint64_t uid, std::string_view ct,
                                       std::shared_ptr<WsSession> session) {
  std::shared_ptr<WsSession> old;
  {
    const std::lock_guard<std::mutex> lock(mutex_);
    auto& per_client = sessions_[uid];
    const auto it = per_client.find(std::string(ct));
    if (it != per_client.end()) {
      old = it->second.lock();
    }
    per_client[std::string(ct)] = session;
  }
  // 同类互顶:只踢同端。另一个端(一个 App + 一个网页)不受影响。
  if (old != nullptr && old.get() != session.get()) {
    old->kick("multi_device");
  }
  touch_online(uid);
}

bool SessionRegistry::unregister(uint64_t uid, std::string_view ct, WsSession* session) {
  const std::lock_guard<std::mutex> lock(mutex_);
  const auto it = sessions_.find(uid);
  if (it == sessions_.end()) {
    return false;
  }
  const auto client_it = it->second.find(std::string(ct));
  if (client_it == it->second.end() || client_it->second.lock().get() != session) {
    return false;
  }
  it->second.erase(client_it);
  if (it->second.empty()) {
    sessions_.erase(it);
  }
  return true;
}

void SessionRegistry::kick(uint64_t uid, const std::string& reason) {
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

void SessionRegistry::kick_client(uint64_t uid, std::string_view ct,
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

bool SessionRegistry::send_to(uint64_t uid, const std::string& frame) {
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
}
