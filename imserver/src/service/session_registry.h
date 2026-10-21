#pragma once
#include <cstdint>
#include <memory>
#include <mutex>
#include <string>
#include <unordered_map>

class RedisClient;
class WsSession;

class SessionRegistry {
 public:
  explicit SessionRegistry(RedisClient& redis);

  void register_session(uint64_t uid, std::shared_ptr<WsSession> session);
  bool unregister(uint64_t uid, WsSession* session);
  void kick(uint64_t uid, const std::string& reason);
  bool send_to(uint64_t uid, const std::string& frame);
  bool is_online(uint64_t uid);
  std::size_t online_count();
  void touch_online(uint64_t uid);

 private:
  RedisClient& redis_;
  std::mutex mutex_;
  std::unordered_map<uint64_t, std::weak_ptr<WsSession>> sessions_;
};
