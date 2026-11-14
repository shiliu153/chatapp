/*********************************************************************************************************************
* chat_app 自建 IM 服务端（imserver）是本项目唯一的 IM 后端，C++20 实现，对外提供 WebSocket :9100 与 HTTP :9101
* Copyright (c) 2026 shiliu153
*
* 本文件是 chat_app 自建 IM 服务端的一部分
*
* 额外注明：
* 本文件使用 MIT 开源许可证协议 许可申明英文版见仓库根目录 LICENSE 文件
* 欢迎各位使用并传播本程序 但修改内容时必须保留作者的版权声明（即本声明）
*
* 文件名称          tests/push_notifier_test.cpp
* 项目名称          chat_app / imserver
* 公司名称          个人项目（shiliu153）
* 版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
* 开发环境          CMake 3.22 + g++ (C++20) Linux x86_64
* 适用平台          Linux x86_64 服务端
* 仓库地址          https://github.com/shiliu153/chatapp
*
* 修改记录
* 日期              作者               备注
* 2026-11-14        shiliu153          补齐文件头与函数注释
********************************************************************************************************************/
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证推送地址为空时关闭
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R DisabledWhenUrlEmpty
// 备注信息     enabled 为 false 投递直接返回 false queued 与 sent 都是 0 关闭态不建工作线程
//-------------------------------------------------------------------------------------------------------------------
TEST(PushNotifierTest, DisabledWhenUrlEmpty) {
  PushNotifier notifier(make_config(""));
  EXPECT_FALSE(notifier.enabled());
  EXPECT_FALSE(notifier.notify_offline_message(2, 1, 100, 1, "在吗", "发件人"));
  EXPECT_EQ(notifier.queued(), 0u);
  EXPECT_EQ(notifier.sent(), 0u);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证非法推送地址构造即抛错
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R RejectsNonHttpUrl
// 备注信息     https 协议与缺少内部路径的地址都抛 std::runtime_error 只接受 http 且必须带 path
//-------------------------------------------------------------------------------------------------------------------
TEST(PushNotifierTest, RejectsNonHttpUrl) {
  EXPECT_THROW(PushNotifier(make_config("https://127.0.0.1:8000/internal/push")),
               std::runtime_error);
  EXPECT_THROW(PushNotifier(make_config("http://127.0.0.1:8000")), std::runtime_error);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证灰条与系统消息不推送
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R SkipsCustomAndSystemMessages
// 备注信息     kind=2 与 from=0 均返回 false drain 之后传输层一次都没被调用
//-------------------------------------------------------------------------------------------------------------------
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证离线事件载荷与签名
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R SendsSignedPayload
// 备注信息     断言 body 含 to_user_id from_user_id msg_id 与预览文本 签名口径为 ts 换行 POST 换行 path 换行 body 的 HMAC-SHA256 断言 sent 为 1 failed 为 0
//-------------------------------------------------------------------------------------------------------------------
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证媒体消息预览替换为占位文案
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R ReplacesPreviewForMediaMessages
// 备注信息     kind=3 得图片占位 kind=4 得语音占位 kind=2 得空串 kind=1 原样返回正文
//-------------------------------------------------------------------------------------------------------------------
TEST(PushNotifierTest, ReplacesPreviewForMediaMessages) {
  EXPECT_EQ(PushNotifier::preview_for(1, "你好"), "你好");
  EXPECT_EQ(PushNotifier::preview_for(3, "ignored"), "[图片]");
  EXPECT_EQ(PushNotifier::preview_for(4, "ignored"), "[语音]");
  EXPECT_EQ(PushNotifier::preview_for(2, "ignored"), "");
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证传输失败只计数不抛异常
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R CountsFailuresWithoutThrowing
// 备注信息     传输层返回 false 断言 sent 为 0 failed 为 1 发送路径不被异常打断
//-------------------------------------------------------------------------------------------------------------------
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证队列满时丢事件而不反压
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R DropsWhenQueueIsFull
// 备注信息     队列容量 1 且传输层延迟 200ms 连投三条断言 dropped 至少 1 绝不阻塞调用方
//-------------------------------------------------------------------------------------------------------------------
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
