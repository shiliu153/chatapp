#include "net/ws_server.h"

#include <boost/asio/post.hpp>
#include <boost/asio/strand.hpp>
#include <boost/beast/core/buffers_to_string.hpp>

#include <algorithm>
#include <cctype>
#include <chrono>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <utility>

#include "auth/token.h"
#include "net/frames.h"
#include "util/log.h"

namespace beast = boost::beast;
namespace http = beast::http;
namespace websocket = beast::websocket;
namespace net = boost::asio;
using tcp = net::ip::tcp;
using error_code = beast::error_code;

namespace {

int64_t now_ms() {
  return std::chrono::duration_cast<std::chrono::milliseconds>(
             std::chrono::system_clock::now().time_since_epoch())
      .count();
}

std::optional<uint64_t> parse_uid(const std::string& value) {
  if (value.size() < 2 || value[0] != 'u') {
    return std::nullopt;
  }
  const auto digits = value.substr(1);
  // 严格整串数字:``std::stoull`` 会接受 "12abc" 这样的前缀(只解析到 12),
  // 那会让日志/审计里的接收方与客户端意图不一致(M-8)。
  if (digits.size() > 20) {
    return std::nullopt;
  }
  for (const unsigned char ch : digits) {
    if (!std::isdigit(ch)) {
      return std::nullopt;
    }
  }
  try {
    return std::stoull(digits);
  } catch (const std::exception&) {
    return std::nullopt;
  }
}

// `peer_id()` 在 `net/frames.h`:与下行 `message` 帧共用一份 id 映射。

/// 贴纸 id 的合法形状:`sticker_` + 两位数字(`sticker_01` … `sticker_99`)。
///
/// 为什么要在这里校验:贴纸复用 `kind=2 custom`(2026-11-07 批次 J),而 custom 原本
/// 是**服务端专用**的消息类型(灰条 / 系统通知,只走 `/internal/send`)。放开上行
/// 后如果照单全收,任何客户端都能伪造 `match_notice` / `ban_notice` 灰条冒充系统通知。
/// 因此上行只放行 `type=sticker` 且 id 形状合法的那一种,其余一律 42201。
///
/// Args:
///   id: 客户端带上来的贴纸 id。
///
/// Returns:
///   形状合法返回 true。
bool is_sticker_id(const std::string& id) {
  if (id.size() != 10 || id.compare(0, 8, "sticker_") != 0) {
    return false;
  }
  return std::isdigit(static_cast<unsigned char>(id[8])) != 0 &&
         std::isdigit(static_cast<unsigned char>(id[9])) != 0;
}

}  // namespace

bool IpCounter::acquire(const std::string& ip) {
  const std::lock_guard<std::mutex> lock(mutex_);
  int& count = counts_[ip];
  if (count >= max_) {
    return false;
  }
  ++count;
  return true;
}

void IpCounter::release(const std::string& ip) {
  const std::lock_guard<std::mutex> lock(mutex_);
  const auto it = counts_.find(ip);
  if (it == counts_.end()) {
    return;
  }
  if (--it->second <= 0) {
    counts_.erase(it);
  }
}

bool IpCounter::allow_auth(const std::string& ip, int64_t now_ms) {
  const std::lock_guard<std::mutex> lock(mutex_);
  auto it = auth_buckets_.find(ip);
  if (it == auth_buckets_.end()) {
    if (auth_buckets_.size() >= max_auth_buckets_) {
      // 先淘汰 10 分钟没再鉴权的桶(桶本身早已回满,丢掉不影响限流强度);
      // 仍然满就整体清空 —— 只丢失一个限流窗口,绝不跟着任意 IP 无限涨内存(L9)。
      for (auto bucket = auth_buckets_.begin(); bucket != auth_buckets_.end();) {
        bucket = now_ms - bucket->second.seen_ms > 600000 ? auth_buckets_.erase(bucket)
                                                          : std::next(bucket);
      }
      if (auth_buckets_.size() >= max_auth_buckets_) {
        log_warn("auth_buckets_reset", {{"size", std::to_string(auth_buckets_.size())}});
        auth_buckets_.clear();
      }
    }
    it = auth_buckets_
             .try_emplace(ip, AuthBucket{TokenBucket{auth_rate_, auth_burst_}, now_ms})
             .first;
  }
  it->second.seen_ms = now_ms;
  return it->second.bucket.allow(now_ms);
}

std::size_t IpCounter::auth_bucket_count() const {
  const std::lock_guard<std::mutex> lock(mutex_);
  return auth_buckets_.size();
}

WsSession::WsSession(tcp::socket socket, const Config& cfg, SessionRegistry& registry,
                     RedisClient& redis, IpCounter& ip_counter, MessageService& messages,
                     PushNotifier& push, boost::asio::thread_pool& db_pool,
                     const net_guard::ProxyTrust& trust)
    : ws_(std::move(socket)),
      cfg_(cfg),
      registry_(registry),
      redis_(redis),
      ip_counter_(ip_counter),
      messages_(messages),
      push_(push),
      db_pool_(db_pool),
      trust_(trust),
      auth_timer_(ws_.get_executor()),
      idle_timer_(ws_.get_executor()) {}

void WsSession::run() {
  auto self = shared_from_this();
  http::async_read(ws_.next_layer(), buffer_, request_,
                   [self](error_code ec, std::size_t bytes) {
                     self->on_http_read(ec, bytes);
                   });
}

std::string WsSession::remote_ip() {
  error_code ec;
  const auto endpoint = ws_.next_layer().socket().remote_endpoint(ec);
  if (ec) {
    return "unknown";
  }
  // X-Real-IP 只在对端是可信代理(默认回环)时才采信:9100 一旦被绕过 nginx 直连,
  // 伪造这个头就等于伪造「单 IP 连接数」和「鉴权令牌桶」的 key(L9)。
  return net_guard::client_ip(endpoint.address(), std::string(request_["X-Real-IP"]), trust_);
}

bool WsSession::origin_allowed() const {
  // 配了 IM_ALLOWED_ORIGINS 就按白名单;没配则退化为同源校验(仍放行无 Origin 的原生端)。
  return net_guard::origin_allowed(std::string(request_[http::field::origin]),
                                   std::string(request_[http::field::host]),
                                   cfg_.allowed_origins);
}

void WsSession::on_http_read(error_code ec, std::size_t bytes) {
  (void)bytes;
  if (ec) {
    release_ip();
    return;
  }
  client_ip_ = remote_ip();
  if (!origin_allowed()) {
    reject_http(403, "origin not allowed");
    return;
  }
  if (!ip_counter_.acquire(client_ip_)) {
    reject_http(429, "too many connections");
    return;
  }
  ip_acquired_ = true;
  ws_.set_option(websocket::stream_base::timeout::suggested(beast::role_type::server));
  ws_.read_message_max(static_cast<std::uint64_t>(cfg_.max_frame));
  auto self = shared_from_this();
  ws_.async_accept(request_, [self](error_code error) { self->on_accept(error); });
}

void WsSession::reject_http(int status, const std::string& message) {
  auto self = shared_from_this();
  auto response = std::make_shared<http::response<http::string_body>>(
      static_cast<http::status>(status), request_.version());
  response->set(http::field::content_type, "application/json");
  response->body() = nlohmann::json{{"code", status == 403 ? 40301 : 42901},
                                    {"message", message}}
                         .dump();
  response->prepare_payload();
  http::async_write(ws_.next_layer(), *response,
                    [self, response](error_code ec, std::size_t bytes) {
                      (void)bytes;
                      self->release_ip();
                      error_code ignored;
                      self->ws_.next_layer().socket().shutdown(tcp::socket::shutdown_both,
                                                               ignored);
                      self->ws_.next_layer().socket().close(ignored);
                      (void)ec;
                    });
}

void WsSession::on_accept(error_code ec) {
  if (ec) {
    release_ip();
    return;
  }
  last_frame_ = std::chrono::steady_clock::now();
  arm_auth_timer();
  arm_idle_timer();
  do_read();
}

void WsSession::arm_auth_timer() {
  auth_timer_.expires_after(std::chrono::seconds(5));
  auto self = shared_from_this();
  auth_timer_.async_wait([self](error_code ec) {
    if (ec || self->authed_ || self->closing_) {
      return;
    }
    self->outbox_.push_back(error_frame(40001, "请先发送 auth 帧"));
    self->close_code_ = 4002;
    self->do_write();
  });
}

void WsSession::arm_idle_timer() {
  idle_timer_.expires_after(std::chrono::seconds(15));
  auto self = shared_from_this();
  idle_timer_.async_wait([self](error_code ec) {
    if (ec || self->closing_) {
      return;
    }
    const auto idle = std::chrono::steady_clock::now() - self->last_frame_;
    if (idle > std::chrono::seconds(75)) {
      self->do_close(1000);
      return;
    }
    if (self->authed_) {
      self->refresh_online();
    }
    self->arm_idle_timer();
  });
}

void WsSession::refresh_online() {
  if (uid_ == 0) {
    return;
  }
  // Redis 在线键 TTL 90s;每帧都 SETEX 会把单连接 Redis 变成全局串行点,
  // 这里按 30s 节流,语义不变(在线判定仍是 120s 内有认证请求)。
  const int64_t now = now_ms();
  if (now - last_online_ms_ < 30000) {
    return;
  }
  last_online_ms_ = now;
  registry_.touch_online(uid_);
}

bool WsSession::allow_send_quota(int64_t now_ms) {
  if (cfg_.send_per_minute <= 0 || uid_ == 0) {
    return true;
  }
  // 跨连接共享的每分钟配额:同一账号开多条 WS 也无法放大发送量(H4)。
  const int64_t minute = now_ms / 60000;
  const std::string key =
      "im:sendq:" + std::to_string(uid_) + ":" + std::to_string(minute);
  const long long count = redis_.incr(key);
  if (count < 0) {
    return true;   // Redis 故障不阻断聊天;单连接仍有 20/s 的令牌桶兜底
  }
  if (count == 1) {
    redis_.setex(key, 120, "1");
  }
  return count <= cfg_.send_per_minute;
}

void WsSession::do_read() {
  if (closing_) {
    return;
  }
  auto self = shared_from_this();
  ws_.async_read(buffer_, [self](error_code ec, std::size_t bytes) {
    self->on_read(ec, bytes);
  });
}

void WsSession::on_read(error_code ec, std::size_t bytes) {
  (void)bytes;
  if (ec) {
    do_close(1000);
    return;
  }
  last_frame_ = std::chrono::steady_clock::now();
  if (authed_) {
    refresh_online();
  }
  const std::string payload = beast::buffers_to_string(buffer_.data());
  buffer_.consume(buffer_.size());
  try {
    on_frame(payload);
  } catch (const std::exception&) {
    send_raw(error_frame(42201, "帧格式错误"));
  }
  if (!closing_) {
    do_read();
  }
}

void WsSession::on_frame(const std::string& payload) {
  const auto frame = nlohmann::json::parse(payload);
  if (!frame.is_object() || frame.value("v", 0) != 1) {
    send_raw(error_frame(42201, "协议版本错误"));
    return;
  }
  const auto type = frame.value("type", "");
  if (!authed_) {
    if (type != "auth") {
      send_raw(error_frame(40001, "请先发送 auth 帧"));
      close_code_ = 4002;

      return;
    }
    handle_auth(frame);
    return;
  }
  if (type == "ping") {
    send_raw(pong_frame(now_ms()));
    return;
  }
  if (type == "send") {
    handle_send(frame);
    return;
  }
  if (type == "read") {
    handle_read(frame);
    return;
  }
  if (type == "typing") {
    handle_typing(frame);
    return;
  }
  if (type == "revoke") {
    handle_revoke(frame);
    return;
  }
  if (type == "conversation_delete") {
    handle_delete(frame);
    return;
  }
  send_raw(error_frame(42201, "未知帧类型"));
}

void WsSession::handle_auth(const nlohmann::json& frame) {
  if (!ip_counter_.allow_auth(client_ip_, now_ms())) {
    send_raw(error_frame(42901, "认证过于频繁"));
    close_code_ = 4002;

    return;
  }
  std::string token;
  try {
    token = frame.at("data").at("token").get<std::string>();
  } catch (const std::exception&) {
    send_raw(error_frame(40101, "缺少 token"));
    close_code_ = 4002;

    return;
  }

  const auto claims = verify_token(token, cfg_.jwt_secret, now_ms());
  if (!claims.has_value()) {
    send_raw(error_frame(40101, "登录已过期"));
    close_code_ = 4002;

    return;
  }
  if (redis_.get("im:block:" + std::to_string(claims->uid)).has_value()) {
    send_raw(error_frame(40301, "账号已被封禁"));
    close_code_ = 4003;

    return;
  }
  // 会话版本:登录会把**该端**的版本 +1 并同步到 im_device_session;旧设备的 token
  // 带的是旧版本,这里直接拒绝,避免「被顶下线后还能重连收消息」(H3)。
  // sv=0 是过渡期的旧 token;ct 缺省 app 见 verify_token(老 token 继续按 App 放行)。
  if (claims->sv != 0 &&
      !session_version_matches(
          claims->sv, messages_.users().session_version(claims->uid, claims->ct))) {
    send_raw(error_frame(40101, "登录已过期"));
    close_code_ = 4002;

    return;
  }

  uid_ = claims->uid;
  client_type_ = claims->ct;
  authed_ = true;
  auth_timer_.cancel();
  messages_.users().ensure(uid_, "");
  registry_.register_session(uid_, client_type_, shared_from_this());
  send_raw(auth_ok_frame(uid_, now_ms()));
}

void WsSession::handle_send(const nlohmann::json& frame) {
  if (!send_bucket_.allow(now_ms())) {
    send_raw(error_frame(42901, "发送过快"));
    return;
  }
  if (!allow_send_quota(now_ms())) {
    send_raw(error_frame(42901, "发送过快"));
    return;
  }
  try {
    const auto data = frame.at("data");
    const auto to_uid = parse_uid(data.value("to", std::string()));
    if (!to_uid.has_value()) {
      send_raw(error_frame(42201, "接收方不合法"));
      return;
    }
    SendRequest request;
    request.from = uid_;
    request.to = *to_uid;
    request.client_msg_id = data.value("client_msg_id", frame.value("id", std::string()));
    const auto kind = data.value("kind", std::string("text"));
    if (kind == "image") {
      request.kind = 3;
      request.image = data.at("image");
    } else if (kind == "voice") {
      request.kind = 4;
      request.voice = data.at("voice");
    } else if (kind == "text") {
      request.kind = 1;
      request.text = data.value("text", std::string());
    } else if (kind == "custom") {
      // 贴纸(2026-11-07 批次 J):复用 kind=2,落库 / 历史 / 下行帧全部零改动。
      // 只放行 type=sticker 且 id 形状合法的载荷;`match_notice` / `ban_notice`
      // 这类系统灰条仍然只能由服务端经 `/internal/send` 发出。
      const auto custom = data.at("custom");
      if (!custom.is_object() ||
          custom.value("type", std::string()) != "sticker") {
        send_raw(error_frame(42201, "暂不支持该消息类型"));
        return;
      }
      const auto sticker = custom.value("id", std::string());
      if (!is_sticker_id(sticker)) {
        send_raw(error_frame(42201, "贴纸 id 不合法"));
        return;
      }
      request.kind = 2;
      // 只落白名单字段:客户端夹带的其它键一律丢弃,不给 custom 留夹带通道
      request.custom = {{"type", "sticker"}, {"id", sticker}};
    } else {
      send_raw(error_frame(42201, "暂不支持该消息类型"));
      return;
    }

    // 引用回复(批次 L-2):**只接受 `ref_msg_id` 这一个数字**。
    // 客户端夹带的任何 `ref` 内容(哪怕长得像快照)在这里根本不被读取 ——
    // 快照由服务端回库查后自己生成(见 MessageService::send)。
    if (data.contains("ref_msg_id") && !data["ref_msg_id"].is_null()) {
      const auto& ref = data["ref_msg_id"];
      if (!ref.is_number_unsigned() && !ref.is_number_integer()) {
        send_raw(error_frame(42201, "引用的消息不合法"));
        return;
      }
      request.ref_msg_id = ref.get<uint64_t>();
    }

    auto self = shared_from_this();
    run_db([self, request] {
      const auto result = self->messages_.send(request);
      boost::asio::post(self->ws_.get_executor(),
                        [self, result, request] { self->on_send_result(result, request); });
    });
  } catch (const std::exception&) {
    send_raw(error_frame(42201, "发送参数错误"));
  }
}

void WsSession::on_send_result(const std::variant<SendResult, int>& result,
                               const SendRequest& request) {
  if (const auto* ok = std::get_if<SendResult>(&result)) {
    // 下行 `message` 帧与 `/im/api/messages` 用**同一个** `message_json`
    // (见 frames.h):两边各写一份迟早有一边漏字段(引用就是这样漏的)。
    const bool delivered =
        registry_.send_to(request.to, build_message_frame(
                                          ok->row, messages_.users().get(ok->row.from_id),
                                          messages_.signer()));
    // C-1:对端**不在线**才推。send_to 的返回值就是「有没有活跃会话」,
    // 比再查一次 is_online 少一次加锁、也没有两次调用之间的竞态。
    // 这里只入队,不发网络请求 —— 推送失败/关闭都不该影响这次发送的 ack。
    if (!delivered) {
      push_.notify_offline_message(request.to, request.from, ok->msg_id, request.kind,
                                   request.text, ok->from_nickname);
    }
    send_raw(send_ack_frame(request.client_msg_id, ok->msg_id, ok->seq, ok->ts));
    return;
  }
  const int code = std::get<int>(result);
  std::string message = "发送失败";
  if (code == 40302) {
    message = "无法发送";
  } else if (code == 42201) {
    message = "内容不合法";
  } else if (code == 42901) {
    message = "发送过快";
  }
  send_raw(error_frame(code, message));
}

void WsSession::handle_read(const nlohmann::json& frame) {
  // 已读回执是「附带动作」,但它会让服务端给对端推一帧。不设限流的话,
  // 一个坏客户端(或「每滚一屏发一次」的实现)就能把对端的推送打爆。
  // 超限**静默丢弃**:read 是幂等的,下次打开会话/收到新消息还会再发一次,
  // 回错误帧只会让客户端白重试。
  if (!read_bucket_.allow(now_ms())) {
    return;
  }
  try {
    const auto data = frame.at("data");
    const auto peer = parse_uid(data.value("peer", std::string()));
    if (!peer.has_value()) {
      send_raw(error_frame(42201, "peer 不合法"));
      return;
    }
    const uint64_t seq = data.value("seq", 0ULL);
    const std::string id = frame.value("id", std::string());
    auto self = shared_from_this();
    run_db([self, peer = *peer, seq, id] {
      const auto marked = self->messages_.mark_read(self->uid_, peer, seq);
      boost::asio::post(self->ws_.get_executor(), [self, marked, peer_uid = peer, id] {
        self->send_raw(ack_frame(id, marked.has_value()));
        if (!marked.has_value()) {
          return;  // 会话不存在:没东西可广播
        }
        // 通知对端「我读到 *marked」:对端据此把自己 seq <= N 的消息标已读。
        // 不带 id —— 这是服务端主动推的,不要求 ack(客户端也不该回)。
        // 多端(K-2):send_to 是扇出,对端的两端都会收到;我自己另一端靠 K-3 的
        // `self_read` 帧同步(这一帧的语义是「**对端**读到 seq」,不能拿来同步自己)。
        self->registry_.send_to(peer_uid, read_frame(peer_id(self->uid_), *marked));
        // 我自己的其他端(K-3):告诉它们「我在那一端读到了 *marked」,它们据此把
        // 与 peer 的未读清零。用独立帧而不是复用上面的 read 帧:read 帧的语义是
        // 「**对端**读到 seq」,发给自己的另一台设备会被读成「对方已读」。
        // 只有一端在线时这里没有目标,天然不会发给自己这条连接。
        self->registry_.send_to_other_clients(
            self->uid_, self.get(), self_read_frame(peer_id(peer_uid), *marked));
      });
    });
  } catch (const std::exception&) {
    send_raw(error_frame(42201, "read 参数错误"));
  }
}

void WsSession::handle_typing(const nlohmann::json& frame) {
  // 输入中状态(批次 L-1)是**可丢信号**:不落库、无 id、不 ack。
  //
  // 这条路径上**任何情况下都不回错误帧** —— 限流超限、`to` 不合法、未配对、
  // 目标不存在,一律静默返回。原因:给洪泛者任何反馈(42901 / 42201)都只会
  // 告诉他「帧收到了,继续打」;而正常用户这边丢一帧的代价只是「对方晚一点
  // 看到正在输入」,本来就不该被感知到。
  if (!typing_bucket_.allow(now_ms())) {
    return;  // 限流:静默丢弃(1 次 / 2 秒、突发 3)
  }
  const auto data = frame.value("data", nlohmann::json::object());
  const auto to_uid = parse_uid(data.value("to", std::string()));
  if (!to_uid.has_value() || *to_uid == uid_) {
    return;  // `to` 不合法或发给自己:静默丢弃
  }
  auto self = shared_from_this();
  run_db([self, peer = *to_uid] {
    try {
      // 前置与 `send` 同口径:复用同一个配对校验函数(`MessageService::pair_exists`,
      // `send()` 里也是它),别在这里另写一份判定 —— 两份判定迟早会漂移。
      if (!self->messages_.pair_exists(self->uid_, peer)) {
        return;  // 未配对 / 目标不存在:静默丢弃
      }
      // 只发对端。`send_to` 是**多端扇出**:对端若两端都在线会两端都收到(这是对的,
      // 用户在哪个端都该看到「正在输入」);但发起端自己的另一台设备绝不能收到,
      // 所以这里不能用 send_to(self->uid_, ...),也不用 send_to_other_clients。
      self->registry_.send_to(peer, typing_frame(peer_id(self->uid_)));
    } catch (const std::exception&) {
      // 数据库/连接池不可用也别回错误帧(run_db 默认会给发起端发 50001):
      // typing 丢了就丢了,回一个错误只会让客户端以为「正在输入」需要重试。
      return;
    }
  });
}

void WsSession::handle_revoke(const nlohmann::json& frame) {
  try {
    const auto data = frame.at("data");
    const uint64_t msg_id = std::stoull(data.value("msg_id", std::string()));
    const std::string id = frame.value("id", std::string());
    auto self = shared_from_this();
    run_db([self, msg_id, id] {
      const auto result = self->messages_.revoke(self->uid_, msg_id);
      boost::asio::post(self->ws_.get_executor(), [self, result, id] {
        if (const auto* revoked = std::get_if<RevokeResult>(&result)) {
          const auto frame_for = [&](uint64_t other) {
            return revoked_frame(revoked->msg_id, revoked->seq, peer_id(other), revoked->ts);
          };
          // 多端(K-2,Step 0 核实结论):这两帧经 send_to 扇出,撤回者**自己**的另一端
          // 也会收到;帧里的 `peer` 是相对收帧者的对端,对本人另一端同样正确,
          // 所以撤回不需要额外代码。
          self->registry_.send_to(revoked->from_id,
                                  frame_for(revoked->to_id));
          self->registry_.send_to(revoked->to_id,
                                  frame_for(revoked->from_id));
          self->send_raw(ack_frame(id, true));
        } else {
          self->send_raw(error_frame(std::get<int>(result), "撤回失败"));
        }
      });
    });
  } catch (const std::exception&) {
    send_raw(error_frame(41001, "撤回参数错误"));
  }
}

void WsSession::handle_delete(const nlohmann::json& frame) {
  try {
    const auto data = frame.at("data");
    const auto peer = parse_uid(data.value("peer", std::string()));
    if (!peer.has_value()) {
      send_raw(error_frame(42201, "peer 不合法"));
      return;
    }
    const std::string id = frame.value("id", std::string());
    auto self = shared_from_this();
    run_db([self, peer = *peer, id] {
      // 删除是**按 uid** 的软删(set_deleted):只删我这一份,对方那份不受影响。
      const bool ok = self->messages_.delete_conversation(self->uid_, peer);
      boost::asio::post(self->ws_.get_executor(), [self, ok, peer_uid = peer, id] {
        self->send_raw(ack_frame(id, ok));
        if (!ok) {
          return;  // 没删成(会话不存在 / 已删过):没必要让另一台设备做无谓的移除
        }
        // 我自己的其他端(K-3):同步「这条会话已被我删掉」,它们立刻从列表移除,
        // 不必等重新拉全量。**只发给本人的其他端,绝不发给对方** —— 删会话是单方
        // 行为,对方不该知道,更不该因此丢记录。
        self->registry_.send_to_other_clients(self->uid_, self.get(),
                                              conversation_deleted_frame(peer_id(peer_uid)));
      });
    });
  } catch (const std::exception&) {
    send_raw(error_frame(42201, "删除参数错误"));
  }
}

void WsSession::send_raw(std::string frame) {
  auto self = shared_from_this();
  net::post(ws_.get_executor(), [self, frame = std::move(frame)] {
    if (self->closing_) {
      return;
    }
    self->outbox_bytes_ += frame.size();
    self->outbox_.push_back(std::move(frame));
    if (self->outbox_.size() > 64 || self->outbox_bytes_ > 128 * 1024) {
      self->close_code_ = 4004;
      self->do_write();
      return;
    }
    self->do_write();
  });
}

void WsSession::do_write() {
  if (writing_ || closing_) {
    return;
  }
  if (outbox_.empty()) {
    if (close_code_.has_value()) {
      do_close(*close_code_);
    }
    return;
  }
  writing_ = true;
  auto self = shared_from_this();
  ws_.async_write(net::buffer(outbox_.front()),
                  [self](error_code ec, std::size_t bytes) {
                    self->on_write(ec, bytes);
                  });
}

void WsSession::on_write(error_code ec, std::size_t bytes) {
  (void)bytes;
  writing_ = false;
  if (ec) {
    do_close(1000);
    return;
  }
  outbox_bytes_ -= outbox_.front().size();
  outbox_.pop_front();
  if (outbox_.empty() && close_code_.has_value()) {
    do_close(*close_code_);
    return;
  }
  do_write();
}

void WsSession::do_close(int code) {
  if (closing_) {
    return;
  }
  closing_ = true;
  auth_timer_.cancel();
  idle_timer_.cancel();
  auto self = shared_from_this();
  ws_.async_close(websocket::close_reason(static_cast<websocket::close_code>(code)),
                  [self](error_code ec) { self->on_close(ec); });
}

void WsSession::on_close(error_code ec) {
  (void)ec;
  release_ip();
  // 多端在线(K-2):只有该账号**最后一个**连接关掉才抹在线键。
  // 否则 App 断开会把仍在线的网页一起标成离线(Step 0 核实出的真实缺口)。
  if (uid_ != 0 && registry_.unregister(uid_, client_type_, this) &&
      !registry_.is_online(uid_)) {
    redis_.del("im:online:" + std::to_string(uid_));
  }
  error_code ignored;
  ws_.next_layer().socket().close(ignored);
}

void WsSession::release_ip() {
  if (!released_ip_ && ip_acquired_) {
    ip_counter_.release(client_ip_);
    released_ip_ = true;
  }
}

void WsSession::run_db(std::function<void()> task) {
  auto self = shared_from_this();
  net::post(db_pool_, [self, task = std::move(task)] {
    try {
      task();
    } catch (const std::exception& error) {
      // 数据库彻底不可用时(池里连不上、lease 为空),不能把异常抛出线程池 —— 那会
      // std::terminate 整个进程。这里降级成一条 50001,让客户端重试。
      log_error("db_task_failed", {{"error", error.what()}});
      net::post(self->ws_.get_executor(), [self] {
        self->send_raw(error_frame(50001, "服务暂不可用"));
      });
    }
  });
}

void WsSession::kick(const std::string& reason) {
  auto self = shared_from_this();
  net::post(ws_.get_executor(), [self, reason] {
    if (self->closing_) {
      return;
    }
    self->outbox_.push_back(kicked_frame(reason));
    self->outbox_bytes_ += self->outbox_.back().size();
    self->close_code_ = 4001;
    self->do_write();
  });
}

WsServer::WsServer(net::io_context& io, const Config& cfg, SessionRegistry& registry,
                   RedisClient& redis, MessageService& messages, PushNotifier& push,
                   boost::asio::thread_pool& db_pool)
    : io_(io),
      acceptor_(io),
      cfg_(cfg),
      registry_(registry),
      redis_(redis),
      messages_(messages),
      push_(push),
      db_pool_(db_pool),
      ip_counter_(cfg.max_conn_per_ip, cfg.auth_rate_per_sec, cfg.auth_burst),
      trust_(net_guard::ProxyTrust::from_list(cfg.trusted_proxies)) {}

void WsServer::start() {
  const auto listen = net_guard::parse_listen(cfg_.listen_ws);
  const tcp::endpoint endpoint(listen.address, listen.port);
  acceptor_.open(endpoint.protocol());
  acceptor_.set_option(net::socket_base::reuse_address(true));
  acceptor_.bind(endpoint);
  acceptor_.listen(net::socket_base::max_listen_connections);
  do_accept();
}

void WsServer::stop() {
  error_code ec;
  acceptor_.close(ec);
}

void WsServer::do_accept() {
  if (!acceptor_.is_open()) {
    return;
  }
  acceptor_.async_accept(net::make_strand(io_), [this](error_code ec, tcp::socket socket) {
    if (!ec) {
      std::make_shared<WsSession>(std::move(socket), cfg_, registry_, redis_, ip_counter_,
                                  messages_, push_, db_pool_, trust_)
          ->run();
    }
    do_accept();
  });
}
