#pragma once
#include <atomic>
#include <condition_variable>
#include <cstdint>
#include <deque>
#include <functional>
#include <mutex>
#include <string>
#include <thread>

#include <nlohmann/json.hpp>

#include "config.h"

/// 把「目标不在线的新消息」转发给 Django 的内部事件入口。
///
/// 背景(C-1):消息由 imserver 直接写进 `chatapp_im`,Django 不知道「有新消息」。
/// 只有 imserver 在消息落库后发一次内部事件,Django 才能在 Celery 里发推送。
///
/// 设计要点:
///   1. **绝不反压发送路径**:`notify_offline_message` 只做一次入队,网络请求在
///      独立线程里跑;队列满就丢(记 `dropped`),发送该成功还是成功;
///   2. **签名口径与 Django → imserver 完全一致**(`ts\nPOST\npath\nbody` + HMAC-SHA256),
///      两边共用 `IM_INTERNAL_SECRET`,Django 侧 `notifications/internal.py` 负责验签;
///   3. **可注入 transport**:单元测试传一个记录用的 lambda 就能验证载荷与签名,
///      不需要起 HTTP 服务;
///   4. `IM_PUSH_URL` 为空 = 关闭(默认),整个类退化成空壳,不建线程。
class PushNotifier {
 public:
  /// 传输层:把「已签名的一次 POST」发出去。返回是否 2xx。
  using Transport = std::function<bool(const std::string& url, const std::string& body,
                                       const std::string& timestamp,
                                       const std::string& signature)>;

  /// 构造:配置里没有 `IM_PUSH_URL` 时只留一个空壳(不建线程)。
  ///
  /// Args:
  ///   cfg: 进程配置(读 `push_url` / `push_timeout_ms` / `push_queue` / `internal_secret`)。
  ///   transport: 可选的传输层实现;为空时用内置的 Boost.Beast HTTP 客户端。
  explicit PushNotifier(const Config& cfg, Transport transport = nullptr);

  ~PushNotifier();

  PushNotifier(const PushNotifier&) = delete;
  PushNotifier& operator=(const PushNotifier&) = delete;

  /// 是否启用(配置了 `IM_PUSH_URL`)。
  bool enabled() const { return enabled_; }

  /// 内部事件的目标地址(空 = 关闭)。
  const std::string& url() const { return url_; }

  /// 投递一条「离线新消息」事件(非阻塞)。
  ///
  /// Args:
  ///   to_uid: 接收者账号 id。
  ///   from_uid: 发送者账号 id。
  ///   msg_id: 消息 id(Django 侧按它去重)。
  ///   kind: 消息类型(1=text 2=custom 3=image 4=voice)。
  ///   preview: 预览文本(文本消息传正文,其它由本类替换成占位文案)。
  ///   from_nickname: 发送者昵称。
  ///
  /// Returns:
  ///   true 表示已入队;false 表示未启用、被过滤(kind=2)或队列已满被丢弃。
  bool notify_offline_message(uint64_t to_uid, uint64_t from_uid, uint64_t msg_id,
                              int kind, const std::string& preview,
                              const std::string& from_nickname);

  /// 已入队 / 已发送 / 发送失败 / 因队列满丢弃 的累计计数(测试与排查用)。
  uint64_t queued() const { return queued_.load(std::memory_order_relaxed); }
  uint64_t sent() const { return sent_.load(std::memory_order_relaxed); }
  uint64_t failed() const { return failed_.load(std::memory_order_relaxed); }
  uint64_t dropped() const { return dropped_.load(std::memory_order_relaxed); }

  /// 等待队列排空(测试用)。
  ///
  /// Args:
  ///   timeout_ms: 最长等待毫秒。
  ///
  /// Returns:
  ///   true 表示已排空;false 表示超时仍有积压。
  bool drain(int timeout_ms);

  /// 按消息类型给出预览文案(文本取正文,图片/语音给占位,其它空串)。
  ///
  /// Args:
  ///   kind: 消息类型。
  ///   text: 文本消息正文。
  ///
  /// Returns:
  ///   预览字符串。
  static std::string preview_for(int kind, const std::string& text);

 private:
  void worker_loop();
  bool deliver(const std::string& body);

  bool enabled_ = false;
  std::string url_;
  std::string path_;
  std::string host_;
  std::string port_ = "80";
  std::string secret_;
  int timeout_ms_ = 2000;
  std::size_t capacity_ = 256;
  Transport transport_;

  mutable std::mutex mutex_;
  std::condition_variable cv_;
  std::condition_variable idle_cv_;
  std::deque<std::string> queue_;
  bool stopping_ = false;
  bool busy_ = false;
  std::thread worker_;

  std::atomic<uint64_t> queued_{0};
  std::atomic<uint64_t> sent_{0};
  std::atomic<uint64_t> failed_{0};
  std::atomic<uint64_t> dropped_{0};
};
