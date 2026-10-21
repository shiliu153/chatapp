#include "service/session_registry.h"

#include <chrono>
#include <utility>

#include "net/ws_server.h"
#include "store/redis_client.h"

namespace {

int64_t now_ms() {
  return std::chrono::duration_cast<std::chrono::milliseconds>(
             std::chrono::system_clock::now().time_since_epoch())
      .count();
}

}  // namespace

SessionRegistry::SessionRegistry(RedisClient& redis) : redis_(redis) {}

void SessionRegistry::register_session(uint64_t uid, std::shared_ptr<WsSession> session) {
  std::shared_ptr<WsSession> old;
  {
    const std::lock_guard<std::mutex> lock(mutex_);
    const auto it = sessions_.find(uid);
    if (it != sessions_.end()) {
      old = it->second.lock();
    }
    sessions_[uid] = session;
  }
  if (old != nullptr && old.get() != session.get()) {
    old->kick("multi_device");
  }
  touch_online(uid);
}

bool SessionRegistry::unregister(uint64_t uid, WsSession* session) {
  const std::lock_guard<std::mutex> lock(mutex_);
  const auto it = sessions_.find(uid);
  if (it != sessions_.end() && it->second.lock().get() == session) {
    sessions_.erase(it);
    return true;
  }
  return false;
}

void SessionRegistry::kick(uint64_t uid, const std::string& reason) {
  std::shared_ptr<WsSession> session;
  {
    const std::lock_guard<std::mutex> lock(mutex_);
    const auto it = sessions_.find(uid);
    if (it != sessions_.end()) {
      session = it->second.lock();
    }
  }
  if (session != nullptr) {
    session->kick(reason);
  }
}

bool SessionRegistry::send_to(uint64_t uid, const std::string& frame) {
  std::shared_ptr<WsSession> session;
  {
    const std::lock_guard<std::mutex> lock(mutex_);
    const auto it = sessions_.find(uid);
    if (it != sessions_.end()) {
      session = it->second.lock();
    }
  }
  if (session == nullptr) {
    return false;
  }
  session->send_raw(frame);
  return true;
}

bool SessionRegistry::is_online(uint64_t uid) {
  const std::lock_guard<std::mutex> lock(mutex_);
  const auto it = sessions_.find(uid);
  return it != sessions_.end() && !it->second.expired();
}

std::size_t SessionRegistry::online_count() {
  const std::lock_guard<std::mutex> lock(mutex_);
  std::size_t count = 0;
  for (const auto& [uid, weak] : sessions_) {
    if (!weak.expired()) {
      ++count;
    }
  }
  return count;
}

void SessionRegistry::touch_online(uint64_t uid) {
  redis_.setex("im:online:" + std::to_string(uid), 90, std::to_string(now_ms()));
}
