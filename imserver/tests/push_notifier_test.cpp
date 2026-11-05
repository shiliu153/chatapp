#include <gtest/gtest.h>

#include <atomic>
#include <chrono>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

#include "config.h"
#include "service/push_notifier.h"
#include "util/hmac.h"

namespace {

/// 记录型传输层:把每次投递的入参存下来,便于断言载荷与签名。
struct Recorder {
  std::mutex mutex;
  std::vector<std::string> bodies;
  std::vector<std::string> timestamps;
  std::vector<std::string> signatures;
  bool result = true;
  int delay_ms = 0;

  PushNotifier::Transport transport() {
    return [this](const std::string& url, const std::string& body,
                  const std::string& timestamp, const std::string& signature) {
      (void)url;
      if (delay_ms > 0) {
        std::this_thread::sleep_for(std::chrono::milliseconds(delay_ms));
      }
      std::lock_guard<std::mutex> lock(mutex);
      bodies.push_back(body);
      timestamps.push_back(timestamp);
      signatures.push_back(signature);
      return result;
    };
  }

  std::size_t size() {
    std::lock_guard<std::mutex> lock(mutex);
    return bodies.size();
  }

  std::string body(std::size_t index) {
    std::lock_guard<std::mutex> lock(mutex);
    return bodies.at(index);
  }

  std::string timestamp(std::size_t index) {
    std::lock_guard<std::mutex> lock(mutex);
    return timestamps.at(index);
  }

  std::string signature(std::size_t index) {
    std::lock_guard<std::mutex> lock(mutex);
    return signatures.at(index);
  }
};

Config make_config(const std::string& url, std::size_t queue = 256) {
  Config cfg;
  cfg.internal_secret = "test-secret";
  cfg.push_url = url;
  cfg.push_queue = queue;
  return cfg;
}

}  // namespace

TEST(PushNotifierTest, DisabledWhenUrlEmpty) {
  PushNotifier notifier(make_config(""));
  EXPECT_FALSE(notifier.enabled());
  EXPECT_FALSE(notifier.notify_offline_message(2, 1, 100, 1, "在吗", "发件人"));
  EXPECT_EQ(notifier.queued(), 0u);
  EXPECT_EQ(notifier.sent(), 0u);
}

TEST(PushNotifierTest, RejectsNonHttpUrl) {
  EXPECT_THROW(PushNotifier(make_config("https://127.0.0.1:8000/internal/push")),
               std::runtime_error);
  EXPECT_THROW(PushNotifier(make_config("http://127.0.0.1:8000")), std::runtime_error);
}

TEST(PushNotifierTest, SkipsCustomAndSystemMessages) {
  Recorder recorder;
  PushNotifier notifier(make_config("http://127.0.0.1:8000/internal/push/new-message"),
                        recorder.transport());
  // kind=2 是灰条/系统通知;from=0 是系统账号。两者都不推。
  EXPECT_FALSE(notifier.notify_offline_message(2, 1, 100, 2, "配对成功", "系统"));
  EXPECT_FALSE(notifier.notify_offline_message(2, 0, 101, 1, "系统消息", "系统"));
  EXPECT_TRUE(notifier.drain(1000));
  EXPECT_EQ(recorder.size(), 0u);
}

TEST(PushNotifierTest, SendsSignedPayload) {
  Recorder recorder;
  PushNotifier notifier(make_config("http://127.0.0.1:8000/internal/push/new-message"),
                        recorder.transport());
  ASSERT_TRUE(notifier.notify_offline_message(2, 1, 4242, 1, "晚上一起吃饭吗", "发件人"));
  ASSERT_TRUE(notifier.drain(2000));
  ASSERT_EQ(recorder.size(), 1u);

  const auto body = recorder.body(0);
  EXPECT_NE(body.find("\"to_user_id\":2"), std::string::npos);
  EXPECT_NE(body.find("\"from_user_id\":1"), std::string::npos);
  EXPECT_NE(body.find("\"msg_id\":4242"), std::string::npos);
  EXPECT_NE(body.find("晚上一起吃饭吗"), std::string::npos);

  // 签名口径必须与 Django 侧一致:ts\nPOST\npath\nbody
  const std::string expected = hmac_sha256_hex(
      "test-secret",
      recorder.timestamp(0) + "\nPOST\n/internal/push/new-message\n" + body);
  EXPECT_EQ(recorder.signature(0), expected);
  EXPECT_EQ(notifier.sent(), 1u);
  EXPECT_EQ(notifier.failed(), 0u);
}

TEST(PushNotifierTest, ReplacesPreviewForMediaMessages) {
  EXPECT_EQ(PushNotifier::preview_for(1, "你好"), "你好");
  EXPECT_EQ(PushNotifier::preview_for(3, "ignored"), "[图片]");
  EXPECT_EQ(PushNotifier::preview_for(4, "ignored"), "[语音]");
  EXPECT_EQ(PushNotifier::preview_for(2, "ignored"), "");
}

TEST(PushNotifierTest, CountsFailuresWithoutThrowing) {
  Recorder recorder;
  recorder.result = false;
  PushNotifier notifier(make_config("http://127.0.0.1:8000/internal/push/new-message"),
                        recorder.transport());
  ASSERT_TRUE(notifier.notify_offline_message(2, 1, 7, 1, "hi", "发件人"));
  ASSERT_TRUE(notifier.drain(2000));
  EXPECT_EQ(notifier.sent(), 0u);
  EXPECT_EQ(notifier.failed(), 1u);
}

TEST(PushNotifierTest, DropsWhenQueueIsFull) {
  Recorder recorder;
  recorder.delay_ms = 200;
  PushNotifier notifier(make_config("http://127.0.0.1:8000/internal/push/new-message",
                                    /*queue=*/1),
                        recorder.transport());
  // 第一条被 worker 立刻取走,第二条占住队列,第三条必然被丢。
  EXPECT_TRUE(notifier.notify_offline_message(2, 1, 1, 1, "a", "x"));
  std::this_thread::sleep_for(std::chrono::milliseconds(20));
  notifier.notify_offline_message(2, 1, 2, 1, "b", "x");
  notifier.notify_offline_message(2, 1, 3, 1, "c", "x");
  notifier.drain(3000);
  EXPECT_GE(notifier.dropped(), 1u);
}
