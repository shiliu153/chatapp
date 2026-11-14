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
* 文件名称          src/service/push_notifier.cpp
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
#include "service/push_notifier.h"

#include <boost/asio/connect.hpp>
#include <boost/asio/ip/tcp.hpp>
#include <boost/beast/core.hpp>
#include <boost/beast/http.hpp>

#include <chrono>
#include <ctime>
#include <stdexcept>
#include <utility>

#include "util/hmac.h"
#include "util/log.h"
#include "util/metrics.h"

namespace {

namespace beast = boost::beast;
namespace http = beast::http;
namespace net = boost::asio;
using tcp = net::ip::tcp;

/// 解析 `http://host[:port]/path`。
///
/// Args:
///   url: 完整地址。
///   host: 输出主机。
///   port: 输出端口(缺省 80)。
///   path: 输出路径(含前导 `/`)。
///
/// Raises:
///   std::runtime_error: 协议不是 http,或缺少主机 / 路径。
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     解析 IM_PUSH_URL 得到主机 端口 路径
// 参数说明     url             完整地址 必须 http:// 开头
//              host            输出主机
//              port            输出端口 缺省 80
//              path            输出路径 含前导斜杠
// 返回参数     void             无返回值
// 使用示例     parse_url("http://127.0.0.1:8000/api/v1/internal/im/push", host, port, path);
// 备注信息     协议不是 http 缺主机或缺路径时抛 std::runtime_error 构造期与每次发送前各调一次
//-------------------------------------------------------------------------------------------------------------------
void parse_url(const std::string& url, std::string& host, std::string& port,
               std::string& path) {
  constexpr const char* kScheme = "http://";
  if (url.rfind(kScheme, 0) != 0) {
    throw std::runtime_error("IM_PUSH_URL must start with http://, got " + url);
  }
  const std::string rest = url.substr(std::string(kScheme).size());
  const auto slash = rest.find('/');
  if (slash == std::string::npos || slash == 0) {
    throw std::runtime_error("IM_PUSH_URL must contain a path, got " + url);
  }
  const std::string host_port = rest.substr(0, slash);
  path = rest.substr(slash);
  const auto colon = host_port.rfind(':');
  if (colon == std::string::npos) {
    host = host_port;
    port = "80";
  } else {
    host = host_port.substr(0, colon);
    port = host_port.substr(colon + 1);
  }
  if (host.empty() || port.empty()) {
    throw std::runtime_error("IM_PUSH_URL host/port invalid: " + url);
  }
}

/// 内置传输层:一次同步 HTTP POST(超时按毫秒)。
///
/// Args:
///   host: 目标主机。
///   port: 目标端口。
///   path: 请求路径。
///   body: 请求体。
///   headers: 额外请求头。
///   timeout_ms: 超时毫秒。
///
/// Returns:
///   true 表示 2xx。
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用内置 HTTP 客户端发一次同步 POST
// 参数说明     host            目标主机
//              port            目标端口
//              path            请求路径
//              body            请求体 JSON
//              headers         额外请求头 时间戳与签名
//              timeout_ms      连接与读写超时毫秒
// 返回参数     bool             true 表示响应 2xx
// 使用示例     http_post(host, port, path, body, {{"X-IM-Timestamp", ts}}, 2000);
// 备注信息     阻塞调用 只跑在推送工作线程 非 2xx 与异常都记日志后返回 false
//-------------------------------------------------------------------------------------------------------------------
bool http_post(const std::string& host, const std::string& port, const std::string& path,
               const std::string& body,
               const std::map<std::string, std::string>& headers, int timeout_ms) {
  try {
    net::io_context io;
    tcp::resolver resolver(io);
    beast::tcp_stream stream(io);
    const auto endpoints = resolver.resolve(host, port);
    stream.expires_after(std::chrono::milliseconds(timeout_ms));
    stream.connect(endpoints);
    http::request<http::string_body> request{http::verb::post, path, 11};
    request.set(http::field::host, host);
    request.set(http::field::user_agent, "imserver-push/1");
    request.set(http::field::content_type, "application/json");
    for (const auto& [name, value] : headers) {
      request.set(name, value);
    }
    request.body() = body;
    request.prepare_payload();
    http::write(stream, request);
    beast::flat_buffer buffer;
    http::response<http::string_body> response;
    http::read(stream, buffer, response);
    beast::error_code ec;
    stream.socket().shutdown(tcp::socket::shutdown_both, ec);
    const auto status = response.result_int();
    if (status < 200 || status >= 300) {
      log_warn("push_http_non_2xx", {{"status", std::to_string(status)}});
      return false;
    }
    return true;
  } catch (const std::exception& error) {
    log_warn("push_http_failed", {{"error", error.what()}});
    return false;
  }
}

}  // namespace

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     构造推送器 配置了 IM_PUSH_URL 才起工作线程
// 参数说明     cfg             进程配置 读 push_url push_timeout_ms push_queue internal_secret
//              transport       可选传输层 为空时用内置 HTTP POST
// 返回参数     void             无返回值
// 使用示例     PushNotifier notifier(cfg, transport);
// 备注信息     url 为空直接返回 关闭态不建线程 push_queue 为 0 时容量按 1 处理
//-------------------------------------------------------------------------------------------------------------------
PushNotifier::PushNotifier(const Config& cfg, Transport transport)
    : url_(cfg.push_url),
      secret_(cfg.internal_secret),
      timeout_ms_(cfg.push_timeout_ms),
      capacity_(cfg.push_queue == 0 ? 1 : cfg.push_queue),
      transport_(std::move(transport)) {
  if (url_.empty()) {
    return;   // 关闭态:不建线程、不发任何请求
  }
  parse_url(url_, host_, port_, path_);
  enabled_ = true;
  if (!transport_) {
    const auto host = host_;
    const auto port = port_;
    const auto timeout = timeout_ms_;
    transport_ = [host, port, timeout](const std::string& url, const std::string& body,
                                       const std::string& timestamp,
                                       const std::string& signature) {
      (void)url;
      std::string host_out, port_out, path_out;
      parse_url(url, host_out, port_out, path_out);
      return http_post(host_out, port_out, path_out, body,
                       {{"X-IM-Timestamp", timestamp}, {"X-IM-Signature", signature}},
                       timeout);
    };
  }
  worker_ = std::thread([this] { worker_loop(); });
  log_info("push_notifier_enabled", {{"url", url_}, {"queue", std::to_string(capacity_)}});
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     析构推送器 置停止位并等待工作线程退出
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     { PushNotifier notifier(cfg); }
// 备注信息     先把队列里已有事件发完再退出 析构期间不得再有并发投递
//-------------------------------------------------------------------------------------------------------------------
PushNotifier::~PushNotifier() {
  {
    std::lock_guard<std::mutex> lock(mutex_);
    stopping_ = true;
  }
  cv_.notify_all();
  if (worker_.joinable()) {
    worker_.join();
  }
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     按消息类型生成推送预览文案
// 参数说明     kind            消息类型 1 文本 3 图片 4 语音
//              text            文本消息正文 仅 kind=1 时使用
// 返回参数     std::string      预览字符串 图片与语音给占位 其它类型空串
// 使用示例     std::string p = PushNotifier::preview_for(1, "在吗");
// 备注信息     纯函数 无状态 是否推送由调用方按 kind 过滤
//-------------------------------------------------------------------------------------------------------------------
std::string PushNotifier::preview_for(int kind, const std::string& text) {
  switch (kind) {
    case 1:
      return text;
    case 3:
      return "[图片]";
    case 4:
      return "[语音]";
    default:
      return "";
  }
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     投递一条离线新消息事件 非阻塞
// 参数说明     to_uid          接收者账号 id
//              from_uid        发送者账号 id 为 0 表示系统来源 直接丢弃
//              msg_id          消息 id Django 侧按它去重
//              kind            消息类型 1 文本 2 灰条 3 图片 4 语音
//              preview         预览文本 文本传正文 其它类型换成占位
//              from_nickname   发送者昵称
// 返回参数     bool             true 已入队 false 未启用 被过滤或队列满
// 使用示例     notifier.notify_offline_message(to_uid, from_uid, msg_id, 1, text, nickname);
// 备注信息     kind=2 灰条与系统通知不推 锁内只入队 队列满记 dropped 后丢弃 不反压发送路径
//-------------------------------------------------------------------------------------------------------------------
bool PushNotifier::notify_offline_message(uint64_t to_uid, uint64_t from_uid,
                                          uint64_t msg_id, int kind,
                                          const std::string& preview,
                                          const std::string& from_nickname) {
  if (!enabled_) {
    return false;
  }
  // kind=2 是灰条 / 系统通知(配对成功、封禁提示等),不推:它们不是「有人在找你」,
  // 推了只会让通知栏变噪音。
  if (kind == 2 || from_uid == 0) {
    return false;
  }
  nlohmann::json body = {
      {"to_user_id", to_uid},   {"from_user_id", from_uid},
      {"msg_id", msg_id},       {"from_nickname", from_nickname},
      {"preview", preview_for(kind, preview)},
  };
  const std::string payload = body.dump();
  {
    std::lock_guard<std::mutex> lock(mutex_);
    if (stopping_) {
      return false;
    }
    if (queue_.size() >= capacity_) {
      dropped_.fetch_add(1, std::memory_order_relaxed);
      metrics::push_dropped.fetch_add(1, std::memory_order_relaxed);
      log_warn("push_queue_full", {{"capacity", std::to_string(capacity_)}});
      return false;
    }
    queue_.push_back(payload);
    queued_.fetch_add(1, std::memory_order_relaxed);
    metrics::push_queued.fetch_add(1, std::memory_order_relaxed);
  }
  cv_.notify_one();
  return true;
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     对一条事件载荷签名并发送
// 参数说明     body            已序列化的 JSON 载荷
// 返回参数     bool             true 表示传输层回报 2xx
// 使用示例     bool ok = deliver(payload);
// 备注信息     签名串为 ts\nPOST\npath\nbody 用 IM_INTERNAL_SECRET 做 HMAC-SHA256 签名失败只记日志返回 false
//-------------------------------------------------------------------------------------------------------------------
bool PushNotifier::deliver(const std::string& body) {
  const auto now = std::chrono::system_clock::now();
  const auto seconds =
      std::chrono::duration_cast<std::chrono::seconds>(now.time_since_epoch()).count();
  const std::string timestamp = std::to_string(seconds);
  const std::string signing = timestamp + "\nPOST\n" + path_ + "\n" + body;
  std::string signature;
  try {
    signature = hmac_sha256_hex(secret_, signing);
  } catch (const std::exception& error) {
    log_warn("push_sign_failed", {{"error", error.what()}});
    return false;
  }
  return transport_(url_, body, timestamp, signature);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     工作线程主循环 串行取出事件并投递
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     worker_ = std::thread([this] { worker_loop(); });
// 备注信息     单线程串行保证事件顺序 停止位已置且队列空时退出 成功失败分别累加计数与指标
//-------------------------------------------------------------------------------------------------------------------
void PushNotifier::worker_loop() {
  for (;;) {
    std::string body;
    {
      std::unique_lock<std::mutex> lock(mutex_);
      cv_.wait(lock, [this] { return stopping_ || !queue_.empty(); });
      if (stopping_ && queue_.empty()) {
        return;
      }
      body = std::move(queue_.front());
      queue_.pop_front();
      busy_ = true;
    }
    const bool ok = deliver(body);
    if (ok) {
      sent_.fetch_add(1, std::memory_order_relaxed);
      metrics::push_sent.fetch_add(1, std::memory_order_relaxed);
    } else {
      failed_.fetch_add(1, std::memory_order_relaxed);
      metrics::push_failed.fetch_add(1, std::memory_order_relaxed);
    }
    {
      std::lock_guard<std::mutex> lock(mutex_);
      busy_ = false;
      if (queue_.empty()) {
        idle_cv_.notify_all();
      }
    }
  }
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     等待队列排空且无在途投递
// 参数说明     timeout_ms      最长等待毫秒
// 返回参数     bool             true 已排空 false 超时仍有积压
// 使用示例     bool ok = notifier.drain(2000);
// 备注信息     关闭态直接返回 true 判定条件是队列空且 busy_ 为 false 会阻塞调用线程
//-------------------------------------------------------------------------------------------------------------------
bool PushNotifier::drain(int timeout_ms) {
  if (!enabled_) {
    return true;
  }
  std::unique_lock<std::mutex> lock(mutex_);
  return idle_cv_.wait_for(lock, std::chrono::milliseconds(timeout_ms),
                           [this] { return queue_.empty() && !busy_; });
}
