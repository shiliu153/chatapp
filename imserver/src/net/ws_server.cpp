#include "net/ws_server.h"

#include <boost/asio/post.hpp>
#include <boost/asio/strand.hpp>
#include <boost/beast/core/buffers_to_string.hpp>

#include <algorithm>
#include <chrono>
#include <iostream>
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

std::string error_frame(int code, const std::string& message) {
  return nlohmann::json{{"v", 1},
                        {"type", "error"},
                        {"data", {{"code", code}, {"message", message}}}}
      .dump();
}

std::optional<uint64_t> parse_uid(const std::string& value) {
  if (value.size() < 2 || value[0] != 'u') {
    return std::nullopt;
  }
  try {
    return std::stoull(value.substr(1));
  } catch (const std::exception&) {
    return std::nullopt;
  }
}

std::string ack_frame(const std::string& id, bool ok) {
  return nlohmann::json{{"v", 1}, {"type", "ack"}, {"id", id}, {"data", {{"ok", ok}}}}
      .dump();
}

std::string peer_id(uint64_t uid) {
  return uid == 0 ? "system_notice" : "u" + std::to_string(uid);
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
  auto [it, inserted] = auth_buckets_.try_emplace(ip, auth_rate_, auth_burst_);
  (void)inserted;
  return it->second.allow(now_ms);
}

WsSession::WsSession(tcp::socket socket, const Config& cfg, SessionRegistry& registry,
                     RedisClient& redis, IpCounter& ip_counter, MessageService& messages,
                     boost::asio::thread_pool& db_pool)
    : ws_(std::move(socket)),
      cfg_(cfg),
      registry_(registry),
      redis_(redis),
      ip_counter_(ip_counter),
      messages_(messages),
      db_pool_(db_pool),
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
  const auto forwarded = request_["X-Real-IP"];
  if (!forwarded.empty()) {
    return std::string(forwarded);
  }
  error_code ec;
  const auto endpoint = ws_.next_layer().socket().remote_endpoint(ec);
  return ec ? std::string("unknown") : endpoint.address().to_string();
}

bool WsSession::origin_allowed() const {
  if (cfg_.allowed_origins.empty()) {
    return true;
  }
  const auto origin = std::string(request_[http::field::origin]);
  if (origin.empty()) {
    return true;
  }
  return std::find(cfg_.allowed_origins.begin(), cfg_.allowed_origins.end(), origin) !=
         cfg_.allowed_origins.end();
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
    send_raw(nlohmann::json{{"v", 1},
                            {"type", "pong"},
                            {"data", {{"server_time", now_ms()}}}}
                 .dump());
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

  uid_ = claims->uid;
  authed_ = true;
  auth_timer_.cancel();
  messages_.users().ensure(uid_, "");
  registry_.register_session(uid_, shared_from_this());
  send_raw(nlohmann::json{{"v", 1},
                          {"type", "auth_ok"},
                          {"data", {{"uid", uid_},
                                    {"server_time", now_ms()},
                                    {"heartbeat_sec", 25}}}}
               .dump());
}

void WsSession::handle_send(const nlohmann::json& frame) {
  if (!send_bucket_.allow(now_ms())) {
    send_raw(error_frame(42901, "发送过快"));
    return;
  }
  try {
    const auto data = frame.at("data");
    const auto to = data.value("to", std::string());
    if (to.size() < 2 || to[0] != 'u') {
      send_raw(error_frame(42201, "接收方不合法"));
      return;
    }
    const uint64_t to_uid = std::stoull(to.substr(1));
    SendRequest request;
    request.from = uid_;
    request.to = to_uid;
    request.client_msg_id = data.value("client_msg_id", frame.value("id", std::string()));
    const auto kind = data.value("kind", std::string("text"));
    if (kind == "image") {
      request.kind = 3;
      request.image = data.at("image");
    } else if (kind == "text") {
      request.kind = 1;
      request.text = data.value("text", std::string());
    } else {
      send_raw(error_frame(42201, "暂不支持该消息类型"));
      return;
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
    registry_.send_to(request.to, build_message_frame(*ok, request, messages_.signer()));
    send_raw(nlohmann::json{{"v", 1},
                            {"type", "ack"},
                            {"id", request.client_msg_id},
                            {"data", {{"msg_id", std::to_string(ok->msg_id)},
                                      {"seq", ok->seq},
                                      {"ts", ok->ts}}}}
                 .dump());
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
      const bool ok = self->messages_.mark_read(self->uid_, peer, seq);
      boost::asio::post(self->ws_.get_executor(),
                        [self, ok, id] { self->send_raw(ack_frame(id, ok)); });
    });
  } catch (const std::exception&) {
    send_raw(error_frame(42201, "read 参数错误"));
  }
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
            return nlohmann::json{
                {"v", 1},
                {"type", "revoked"},
                {"data", {{"msg_id", std::to_string(revoked->msg_id)},
                          {"seq", revoked->seq},
                          {"peer", peer_id(other)},
                          {"ts", revoked->ts}}}}
                .dump();
          };
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
      const bool ok = self->messages_.delete_conversation(self->uid_, peer);
      boost::asio::post(self->ws_.get_executor(),
                        [self, ok, id] { self->send_raw(ack_frame(id, ok)); });
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
  if (uid_ != 0 && registry_.unregister(uid_, this)) {
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
    self->outbox_.push_back(nlohmann::json{{"v", 1},
                                           {"type", "kicked"},
                                           {"data", {{"reason", reason}}}}
                                .dump());
    self->outbox_bytes_ += self->outbox_.back().size();
    self->close_code_ = 4001;
    self->do_write();
  });
}

WsServer::WsServer(net::io_context& io, const Config& cfg, SessionRegistry& registry,
                   RedisClient& redis, MessageService& messages,
                   boost::asio::thread_pool& db_pool)
    : io_(io),
      acceptor_(io),
      cfg_(cfg),
      registry_(registry),
      redis_(redis),
      messages_(messages),
      db_pool_(db_pool),
      ip_counter_(cfg.max_conn_per_ip, cfg.auth_rate_per_sec, cfg.auth_burst) {}

void WsServer::start() {
  const auto colon = cfg_.listen_ws.rfind(':');
  if (colon == std::string::npos) {
    throw std::runtime_error("invalid IM_LISTEN_WS");
  }
  const auto host = cfg_.listen_ws.substr(0, colon);
  const auto port = std::stoi(cfg_.listen_ws.substr(colon + 1));
  const tcp::endpoint endpoint(net::ip::make_address(host), static_cast<unsigned short>(port));
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
                                  messages_, db_pool_)
          ->run();
    }
    do_accept();
  });
}
