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

bool PushNotifier::drain(int timeout_ms) {
  if (!enabled_) {
    return true;
  }
  std::unique_lock<std::mutex> lock(mutex_);
  return idle_cv_.wait_for(lock, std::chrono::milliseconds(timeout_ms),
                           [this] { return queue_.empty() && !busy_; });
}
