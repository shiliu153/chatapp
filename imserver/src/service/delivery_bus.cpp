#include "service/delivery_bus.h"

#include <boost/asio/post.hpp>
#include <nlohmann/json.hpp>

#include "service/session_registry.h"
#include "store/redis_client.h"
#include "util/log.h"

namespace {

/// 端类型集合:与 SessionRegistry 的口径一致(一个 uid 最多两条连接)。
constexpr const char* kClientTypes[] = {"app", "web"};

/// owner 键。
std::string owner_key(uint64_t uid, std::string_view ct) {
  return "im:owner:" + std::to_string(uid) + ":" + std::string(ct);
}

/// 定向投递频道。
std::string deliver_channel(const std::string& instance_id) {
  return "im:deliver:" + instance_id;
}

/// 全节点广播频道。
constexpr const char* kBroadcastChannel = "im:broadcast";

}  // namespace

DeliveryBus::DeliveryBus(SessionRegistry& registry, RedisClient& redis, std::string instance_id,
                         std::string redis_url)
    : registry_(registry),
      redis_(redis),
      instance_id_(std::move(instance_id)),
      redis_url_(std::move(redis_url)) {}

void DeliveryBus::start(boost::asio::io_context& io) {
  io_ = &io;
  if (subscriber_ != nullptr) {
    return;
  }
  subscriber_ = std::make_shared<RedisSubscriber>(
      redis_url_, std::vector<std::string>{deliver_channel(instance_id_), kBroadcastChannel},
      [this](const std::string& /*channel*/, const std::string& payload) {
        on_remote_message(payload);
      });
  subscriber_->start();

  SessionRegistry::RemoteHooks hooks;
  hooks.send_to = [this](uint64_t uid, const std::string& frame) {
    nlohmann::json message{{"op", "send"}, {"uid", uid}, {"ct", ""}, {"frame", frame}};
    return publish_to_owner(uid, std::string_view(), message.dump());
  };
  hooks.send_to_client = [this](uint64_t uid, std::string_view ct, const std::string& frame) {
    nlohmann::json message{
        {"op", "send"}, {"uid", uid}, {"ct", std::string(ct)}, {"frame", frame}};
    return publish_to_owner(uid, ct, message.dump());
  };
  hooks.kick = [this](uint64_t uid, std::string_view ct, const std::string& reason,
                      bool all_ends) {
    if (all_ends) {
      nlohmann::json message{{"op", "kick"}, {"uid", uid}, {"ct", ""},
                             {"reason", reason}, {"all", true}};
      broadcast(message.dump());
      return;
    }
    nlohmann::json message{{"op", "kick"}, {"uid", uid}, {"ct", std::string(ct)},
                           {"reason", reason}, {"all", false}};
    publish_to_owner(uid, ct, message.dump());
  };
  registry_.set_remote_hooks(std::move(hooks));
}

void DeliveryBus::stop() {
  if (subscriber_ == nullptr) {
    return;
  }
  registry_.set_remote_hooks(SessionRegistry::RemoteHooks{});
  subscriber_->stop();
  subscriber_.reset();
  io_ = nullptr;
}

bool DeliveryBus::subscriber_connected() const {
  return subscriber_ != nullptr && subscriber_->connected();
}

bool DeliveryBus::publish_to_owner(uint64_t uid, std::string_view ct,
                                   const std::string& message) {
  bool published = false;
  for (const char* type : kClientTypes) {
    if (!ct.empty() && ct != type) {
      continue;
    }
    const auto owner = redis_.get(owner_key(uid, type));
    if (!owner.has_value() || owner->empty() || *owner == instance_id_) {
      continue;
    }
    if (redis_.publish(deliver_channel(*owner), message)) {
      published = true;
    }
  }
  return published;
}

void DeliveryBus::broadcast(const std::string& message) {
  redis_.publish(kBroadcastChannel, message);
}

void DeliveryBus::on_remote_message(const std::string& payload) {
  // 这里在**订阅线程**上:只做转发,真正的会话操作 post 回 io_context。
  if (io_ == nullptr) {
    return;
  }
  boost::asio::post(*io_, [this, payload] { apply_remote_message(payload); });
}

void DeliveryBus::apply_remote_message(const std::string& payload) {
  nlohmann::json message;
  try {
    message = nlohmann::json::parse(payload);
  } catch (const std::exception&) {
    log_warn("delivery_bus_bad_payload", {});
    return;
  }
  const uint64_t uid = message.value("uid", static_cast<uint64_t>(0));
  if (uid == 0) {
    return;
  }
  const std::string op = message.value("op", std::string());
  const std::string ct = message.value("ct", std::string());

  if (op == "send") {
    const std::string frame = message.value("frame", std::string());
    if (frame.empty()) {
      return;
    }
    if (ct.empty()) {
      registry_.local_send_to(uid, frame);
    } else {
      registry_.local_send_to_client(uid, ct, frame);
    }
    return;
  }
  if (op == "kick") {
    const std::string reason = message.value("reason", std::string("multi_device"));
    const bool all = message.value("all", true);
    if (all || ct.empty()) {
      registry_.local_kick(uid, reason);
    } else {
      registry_.local_kick_client(uid, ct, reason);
    }
    return;
  }
  log_warn("delivery_bus_unknown_op", {{"op", op}});
}
