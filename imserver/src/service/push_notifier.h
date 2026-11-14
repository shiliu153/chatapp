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
* 文件名称          src/service/push_notifier.h
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
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     构造推送器 配置了 IM_PUSH_URL 才起工作线程
// 参数说明     cfg             进程配置 读 push_url push_timeout_ms push_queue internal_secret
//              transport       可选传输层 为空时用内置 Boost.Beast HTTP 客户端
// 返回参数     void             无返回值
// 使用示例     PushNotifier notifier(cfg);
// 备注信息     url 为空时退化成空壳 不建线程 关闭态投递一律返回 false
//-------------------------------------------------------------------------------------------------------------------
  explicit PushNotifier(const Config& cfg, Transport transport = nullptr);

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     析构推送器 置停止位并等待工作线程退出
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     { PushNotifier notifier(cfg); }
// 备注信息     先把队列里已有事件发完再退出 析构期间不得再有并发投递
//-------------------------------------------------------------------------------------------------------------------
  ~PushNotifier();

  PushNotifier(const PushNotifier&) = delete;
  PushNotifier& operator=(const PushNotifier&) = delete;

  /// 是否启用(配置了 `IM_PUSH_URL`)。
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     判断推送器是否启用
// 参数说明     无
// 返回参数     bool             true 表示配置了 IM_PUSH_URL
// 使用示例     bool on = notifier.enabled();
// 备注信息     关闭态下不建工作线程 所有投递直接返回 false
//-------------------------------------------------------------------------------------------------------------------
  bool enabled() const { return enabled_; }

  /// 内部事件的目标地址(空 = 关闭)。
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     取内部事件目标地址
// 参数说明     无
// 返回参数     const std::string& IM_PUSH_URL 原值 空串表示关闭
// 使用示例     const std::string& target = notifier.url();
// 备注信息     返回成员引用 调用方不得在对象析构后继续持有
//-------------------------------------------------------------------------------------------------------------------
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
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     投递一条离线新消息事件 非阻塞
// 参数说明     to_uid          接收者账号 id
//              from_uid        发送者账号 id 为 0 表示系统来源 直接丢弃
//              msg_id          消息 id Django 侧按它去重
//              kind            消息类型 1 文本 2 灰条 3 图片 4 语音
//              preview         预览文本 文本传正文 其它类型由本类换成占位
//              from_nickname   发送者昵称
// 返回参数     bool             true 已入队 false 未启用 被过滤或队列满
// 使用示例     notifier.notify_offline_message(to_uid, from_uid, msg_id, 1, text, nickname);
// 备注信息     只做一次入队 网络请求在工作线程 队列满记 dropped 后丢弃 不反压发送路径
//-------------------------------------------------------------------------------------------------------------------
  bool notify_offline_message(uint64_t to_uid, uint64_t from_uid, uint64_t msg_id,
                              int kind, const std::string& preview,
                              const std::string& from_nickname);

  /// 已入队 / 已发送 / 发送失败 / 因队列满丢弃 的累计计数(测试与排查用)。
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     取已入队事件累计数
// 参数说明     无
// 返回参数     uint64_t         入队成功的事件条数
// 使用示例     uint64_t n = notifier.queued();
// 备注信息     原子读 测试与排查用 不参与业务判定
//-------------------------------------------------------------------------------------------------------------------
  uint64_t queued() const { return queued_.load(std::memory_order_relaxed); }
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     取已成功发送事件累计数
// 参数说明     无
// 返回参数     uint64_t         传输层回报 2xx 的条数
// 使用示例     uint64_t n = notifier.sent();
// 备注信息     原子读 测试与排查用 不参与业务判定
//-------------------------------------------------------------------------------------------------------------------
  uint64_t sent() const { return sent_.load(std::memory_order_relaxed); }
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     取发送失败事件累计数
// 参数说明     无
// 返回参数     uint64_t         非 2xx 与抛异常的条数
// 使用示例     uint64_t n = notifier.failed();
// 备注信息     原子读 签名失败也计入失败 测试与排查用
//-------------------------------------------------------------------------------------------------------------------
  uint64_t failed() const { return failed_.load(std::memory_order_relaxed); }
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     取队列满被丢弃事件累计数
// 参数说明     无
// 返回参数     uint64_t         因队列达到容量上限被丢弃的条数
// 使用示例     uint64_t n = notifier.dropped();
// 备注信息     原子读 丢弃时同时记 push_queue_full 日志与指标
//-------------------------------------------------------------------------------------------------------------------
  uint64_t dropped() const { return dropped_.load(std::memory_order_relaxed); }

  /// 等待队列排空(测试用)。
  ///
  /// Args:
  ///   timeout_ms: 最长等待毫秒。
  ///
  /// Returns:
  ///   true 表示已排空;false 表示超时仍有积压。
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     等待队列排空且无在途投递
// 参数说明     timeout_ms      最长等待毫秒
// 返回参数     bool             true 已排空 false 超时仍有积压
// 使用示例     bool ok = notifier.drain(2000);
// 备注信息     关闭态直接返回 true 单测里等异步投递完成用 会阻塞调用线程
//-------------------------------------------------------------------------------------------------------------------
  bool drain(int timeout_ms);

  /// 按消息类型给出预览文案(文本取正文,图片/语音给占位,其它空串)。
  ///
  /// Args:
  ///   kind: 消息类型。
  ///   text: 文本消息正文。
  ///
  /// Returns:
  ///   预览字符串。
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     按消息类型生成推送预览文案
// 参数说明     kind            消息类型 1 文本 3 图片 4 语音
//              text            文本消息正文 仅 kind=1 时使用
// 返回参数     std::string      预览字符串 图片与语音给占位 其它类型空串
// 使用示例     std::string p = PushNotifier::preview_for(3, "");
// 备注信息     纯函数 无状态 可在任意线程调用
//-------------------------------------------------------------------------------------------------------------------
  static std::string preview_for(int kind, const std::string& text);

 private:
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     工作线程主循环 串行取出队列事件并投递
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     worker_ = std::thread([this] { worker_loop(); });
// 备注信息     私有 单线程串行保证事件顺序 停止位已置且队列空时退出
//-------------------------------------------------------------------------------------------------------------------
  void worker_loop();
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     对一条事件载荷签名并发送
// 参数说明     body            已序列化的 JSON 载荷
// 返回参数     bool             true 表示传输层回报 2xx
// 使用示例     bool ok = deliver(payload);
// 备注信息     私有 签名串 ts\nPOST\npath\nbody 用 IM_INTERNAL_SECRET 做 HMAC-SHA256 签名失败只记日志返回 false
//-------------------------------------------------------------------------------------------------------------------
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
