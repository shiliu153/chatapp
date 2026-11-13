#include <gtest/gtest.h>

#include <cstdlib>
#include <memory>
#include <string>

#include "service/session_registry.h"
#include "store/redis_client.h"

namespace {

/// 连测试 Redis(与其它 db 测试同一套环境变量),拿不到就跳过用例。
std::unique_ptr<RedisClient> make_redis() {
  const char* url = std::getenv("IM_REDIS_URL");
  if (url == nullptr) {
    return nullptr;
  }
  return std::make_unique<RedisClient>(url);
}

}  // namespace

/// #288:没有钩子、没有 instance_id = 单实例,跨节点能力必须完全不存在。
TEST(SessionRegistryMultiNode, WithoutHooksBehavesAsSingleNode) {
  auto redis = make_redis();
  ASSERT_NE(redis, nullptr);
  SessionRegistry registry(*redis);

  EXPECT_FALSE(registry.send_to(424242, "frame"));
  EXPECT_FALSE(registry.local_send_to(424242, "frame"));
}

/// #288:本地未命中时,`send_to` 必须把帧交给远端钩子,并把钩子的结果透传出去。
TEST(SessionRegistryMultiNode, SendToFallsBackToRemoteHook) {
  auto redis = make_redis();
  ASSERT_NE(redis, nullptr);
  SessionRegistry registry(*redis, "node-a");

  uint64_t seen_uid = 0;
  std::string seen_frame;
  SessionRegistry::RemoteHooks hooks;
  hooks.send_to = [&](uint64_t uid, const std::string& frame) {
    seen_uid = uid;
    seen_frame = frame;
    return true;
  };
  registry.set_remote_hooks(hooks);

  EXPECT_TRUE(registry.send_to(424242, "frame-x"));
  EXPECT_EQ(seen_uid, 424242u);
  EXPECT_EQ(seen_frame, "frame-x");
}

/// 远端钩子说「没投出去」时,`send_to` 必须如实返回 false(离线推送依赖这个返回值)。
TEST(SessionRegistryMultiNode, SendToPropagatesRemoteMissResult) {
  auto redis = make_redis();
  ASSERT_NE(redis, nullptr);
  SessionRegistry registry(*redis, "node-a");

  SessionRegistry::RemoteHooks hooks;
  hooks.send_to = [](uint64_t, const std::string&) { return false; };
  registry.set_remote_hooks(hooks);

  EXPECT_FALSE(registry.send_to(424242, "frame-x"));
}

/// `local_*` 是远端帧回灌入口:**绝不能**再触发跨节点转发(否则会形成回声)。
TEST(SessionRegistryMultiNode, LocalSendNeverCallsRemoteHook) {
  auto redis = make_redis();
  ASSERT_NE(redis, nullptr);
  SessionRegistry registry(*redis, "node-a");

  bool hook_called = false;
  SessionRegistry::RemoteHooks hooks;
  hooks.send_to = [&](uint64_t, const std::string&) {
    hook_called = true;
    return true;
  };
  registry.set_remote_hooks(hooks);

  EXPECT_FALSE(registry.local_send_to(424242, "frame"));
  EXPECT_FALSE(hook_called);
}

/// 跨端同步帧:本地没有该 uid 的连接时也要转到远端。
TEST(SessionRegistryMultiNode, SendToOtherClientsFallsBackToRemote) {
  auto redis = make_redis();
  ASSERT_NE(redis, nullptr);
  SessionRegistry registry(*redis, "node-a");

  bool hook_called = false;
  SessionRegistry::RemoteHooks hooks;
  hooks.send_to = [&](uint64_t, const std::string&) {
    hook_called = true;
    return true;
  };
  registry.set_remote_hooks(hooks);

  registry.send_to_other_clients(424242, nullptr, "frame");
  EXPECT_TRUE(hook_called);
}

/// 封禁 / 注销:`kick` 要让**其它节点**也踢掉该 uid 的全部端(all_ends = true)。
TEST(SessionRegistryMultiNode, KickFansOutToAllNodes) {
  auto redis = make_redis();
  ASSERT_NE(redis, nullptr);
  SessionRegistry registry(*redis, "node-a");

  bool called = false;
  bool saw_all_ends = false;
  std::string saw_reason;
  SessionRegistry::RemoteHooks hooks;
  hooks.kick = [&](uint64_t, std::string_view, const std::string& reason, bool all_ends) {
    called = true;
    saw_all_ends = all_ends;
    saw_reason = reason;
  };
  registry.set_remote_hooks(hooks);

  registry.kick(424242, "banned");
  EXPECT_TRUE(called);
  EXPECT_TRUE(saw_all_ends);
  EXPECT_EQ(saw_reason, "banned");
}

/// 同类互顶 / 按端下线:`kick_client` 只踢指定端(all_ends = false),并带上端类型。
TEST(SessionRegistryMultiNode, KickClientFansOutToOneEnd) {
  auto redis = make_redis();
  ASSERT_NE(redis, nullptr);
  SessionRegistry registry(*redis, "node-a");

  bool called = false;
  bool saw_all_ends = true;
  std::string saw_ct;
  SessionRegistry::RemoteHooks hooks;
  hooks.kick = [&](uint64_t, std::string_view ct, const std::string&, bool all_ends) {
    called = true;
    saw_all_ends = all_ends;
    saw_ct = std::string(ct);
  };
  registry.set_remote_hooks(hooks);

  registry.kick_client(424242, "web", "multi_device");
  EXPECT_TRUE(called);
  EXPECT_FALSE(saw_all_ends);
  EXPECT_EQ(saw_ct, "web");
}

/// 单实例模式(instance_id 为空)**不写 owner 键** —— 多实例能力必须是显式开启的。
TEST(SessionRegistryMultiNode, SingleNodeModeDoesNotWriteOwnerKeys) {
  auto redis = make_redis();
  ASSERT_NE(redis, nullptr);
  SessionRegistry registry(*redis);
  redis->del("im:owner:424242:app");
  redis->del("im:owner:424242:web");

  registry.touch_online(424242);
  EXPECT_FALSE(redis->get("im:owner:424242:app").has_value());
  EXPECT_FALSE(redis->get("im:owner:424242:web").has_value());
}
