#include "net/http_api.h"

#include <boost/asio/strand.hpp>
#include <boost/beast/core.hpp>

#include <algorithm>
#include <chrono>
#include <iterator>
#include <map>
#include <stdexcept>
#include <string>

#include <openssl/crypto.h>
#include <nlohmann/json.hpp>

#include "auth/token.h"
#include "net/frames.h"
#include "net/guard.h"
#include "util/hmac.h"
#include "util/uuid.h"

namespace beast = boost::beast;
namespace http = beast::http;
namespace net = boost::asio;
using tcp = net::ip::tcp;

namespace {

Target parse_target(const std::string& target) {
  Target parsed;
  const auto question = target.find('?');
  parsed.path = target.substr(0, question);
  if (question == std::string::npos) {
    return parsed;
  }
  std::size_t start = question + 1;
  while (start <= target.size()) {
    const auto amp = target.find('&', start);
    const auto pair = target.substr(start, amp == std::string::npos ? std::string::npos
                                                                   : amp - start);
    const auto eq = pair.find('=');
    if (eq != std::string::npos) {
      parsed.query[pair.substr(0, eq)] = pair.substr(eq + 1);
    }
    if (amp == std::string::npos) {
      break;
    }
    start = amp + 1;
  }
  return parsed;
}

uint64_t query_uint(const Target& target, const std::string& key, uint64_t fallback) {
  const auto it = target.query.find(key);
  if (it == target.query.end() || it->second.empty()) {
    return fallback;
  }
  try {
    return std::stoull(it->second);
  } catch (const std::exception&) {
    return fallback;
  }
}

std::optional<uint64_t> parse_peer(const std::string& peer) {
  if (peer == "system_notice") {
    return 0;
  }
  if (peer.size() < 2 || peer[0] != 'u') {
    return std::nullopt;
  }
  try {
    return std::stoull(peer.substr(1));
  } catch (const std::exception&) {
    return std::nullopt;
  }
}

std::string peer_id(uint64_t uid) {
  return uid == 0 ? "system_notice" : "u" + std::to_string(uid);
}

int hex_value(char c) {
  if (c >= '0' && c <= '9') {
    return c - '0';
  }
  if (c >= 'a' && c <= 'f') {
    return c - 'a' + 10;
  }
  if (c >= 'A' && c <= 'F') {
    return c - 'A' + 10;
  }
  return -1;
}

/// 百分号解码 + 把 `+` 当空格(Web 端 URLSearchParams 就是这么编码空格的)。
std::string url_decode(const std::string& input) {
  std::string out;
  out.reserve(input.size());
  for (std::size_t i = 0; i < input.size(); ++i) {
    const char c = input[i];
    if (c == '+') {
      out.push_back(' ');
      continue;
    }
    if (c == '%' && i + 2 < input.size()) {
      const int high = hex_value(input[i + 1]);
      const int low = hex_value(input[i + 2]);
      if (high >= 0 && low >= 0) {
        out.push_back(static_cast<char>(high * 16 + low));
        i += 2;
        continue;
      }
    }
    out.push_back(c);
  }
  return out;
}

std::string trim_ascii(const std::string& input) {
  const auto begin = input.find_first_not_of(" \t\r\n");
  if (begin == std::string::npos) {
    return "";
  }
  const auto end = input.find_last_not_of(" \t\r\n");
  return input.substr(begin, end - begin + 1);
}

nlohmann::json message_json(const MessageRow& row, UserRepo& users, const MediaSigner& signer) {
  nlohmann::json data = {{"msg_id", std::to_string(row.msg_id)},
                         {"seq", row.seq},
                         {"from", peer_id(row.from_id)},
                         {"to", peer_id(row.to_id)},
                         {"ts", row.created_at},
                         {"revoked", row.revoked_at.has_value()}};
  if (row.revoked_at.has_value()) {
    data["kind"] = "text";
  } else {
    const auto body = nlohmann::json::parse(row.body);
    if (row.kind == 3) {
      data["kind"] = "image";
      data["image"] = body.value("image", nlohmann::json::object());
      signer.sign_image(data["image"]);
    } else if (row.kind == 4) {
      data["kind"] = "voice";
      data["voice"] = body.value("voice", nlohmann::json::object());
      signer.sign_media(data["voice"], {"url"});
    } else if (row.kind == 2) {
      data["kind"] = "custom";
      data["custom"] = body;
    } else {
      data["kind"] = "text";
      data["text"] = body.value("text", "");
    }
  }
  if (auto profile = users.get(row.from_id)) {
    data["from_profile"] = {{"nickname", profile->nickname}, {"avatar", profile->avatar}};
  }
  return data;
}

}  // namespace

class HttpSession : public std::enable_shared_from_this<HttpSession> {
 public:
  HttpSession(tcp::socket socket, HttpApi& api) : socket_(std::move(socket)), api_(api) {}

  void run() {
    auto self = shared_from_this();
    http::async_read(socket_, buffer_, request_,
                     [self](beast::error_code ec, std::size_t bytes) {
                       self->on_read(ec, bytes);
                     });
  }

 private:
  void on_read(beast::error_code ec, std::size_t bytes) {
    (void)bytes;
    if (ec) {
      return;
    }
    boost::system::error_code endpoint_error;
    const auto endpoint = socket_.remote_endpoint(endpoint_error);
    const bool loopback = !endpoint_error && endpoint.address().is_loopback();
    auto response = std::make_shared<HttpApi::response_type>(api_.handle(request_, loopback));
    auto self = shared_from_this();
    http::async_write(socket_, *response,
                      [self, response](beast::error_code error, std::size_t written) {
                        (void)written;
                        beast::error_code ignored;
                        self->socket_.shutdown(tcp::socket::shutdown_send, ignored);
                        self->socket_.close(ignored);
                        (void)error;
                      });
  }

  tcp::socket socket_;
  beast::flat_buffer buffer_;
  http::request<http::string_body> request_;
  HttpApi& api_;
};

HttpApi::HttpApi(net::io_context& io, const Config& cfg, MessageService& messages,
                 SessionRegistry& registry, RedisClient& redis)
    : io_(io), acceptor_(io), cfg_(cfg), messages_(messages), registry_(registry),
      redis_(redis) {}

void HttpApi::start() {
  const auto listen = net_guard::parse_listen(cfg_.listen_http);
  const tcp::endpoint endpoint(listen.address, listen.port);
  acceptor_.open(endpoint.protocol());
  acceptor_.set_option(net::socket_base::reuse_address(true));
  acceptor_.bind(endpoint);
  acceptor_.listen(net::socket_base::max_listen_connections);
  do_accept();
}

void HttpApi::stop() {
  beast::error_code ec;
  acceptor_.close(ec);
}

void HttpApi::do_accept() {
  if (!acceptor_.is_open()) {
    return;
  }
  acceptor_.async_accept(net::make_strand(io_), [this](beast::error_code ec, tcp::socket socket) {
    if (!ec) {
      std::make_shared<HttpSession>(std::move(socket), *this)->run();
    }
    do_accept();
  });
}

std::optional<uint64_t> HttpApi::authenticate(
    const http::request<http::string_body>& req) {
  const auto header = std::string(req[http::field::authorization]);
  constexpr const char* kPrefix = "Bearer ";
  if (header.rfind(kPrefix, 0) != 0) {
    return std::nullopt;
  }
  const auto token = header.substr(std::string(kPrefix).size());
  const auto claims = verify_token(
      token, cfg_.jwt_secret,
      std::chrono::duration_cast<std::chrono::milliseconds>(
          std::chrono::system_clock::now().time_since_epoch())
          .count());
  if (!claims.has_value()) {
    return std::nullopt;
  }
  if (redis_.get("im:block:" + std::to_string(claims->uid)).has_value()) {
    return std::nullopt;
  }
  // 会话版本必须与 WS 侧同口径校验:否则被顶下线的旧设备还能用旧 token
  // 通过 /im/api/* 读历史与搜索(H-1)。sv=0 是过渡期旧 token,放行。
  if (claims->sv != 0 &&
      !session_version_matches(claims->sv, messages_.users().session_version(claims->uid))) {
    return std::nullopt;
  }
  return claims->uid;
}

HttpApi::response_type HttpApi::error_response(
    const http::request<http::string_body>& req, http::status status, int code,
    const std::string& message) {
  response_type response(status, req.version());
  response.set(http::field::content_type, "application/json");
  response.body() = nlohmann::json{{"code", code}, {"message", message}}.dump();
  response.prepare_payload();
  return response;
}

HttpApi::response_type HttpApi::json_response(
    const http::request<http::string_body>& req, http::status status,
    const nlohmann::json& body) {
  response_type response(status, req.version());
  response.set(http::field::content_type, "application/json");
  response.body() = body.dump();
  response.prepare_payload();
  return response;
}

HttpApi::response_type HttpApi::handle(
    const http::request<http::string_body>& req, bool loopback) {
  try {
    return route(req, loopback);
  } catch (const std::exception&) {
    return error_response(req, http::status::internal_server_error, 50001, "内部错误");
  }
}

bool HttpApi::verify_internal(const http::request<http::string_body>& req) {
  const auto timestamp = std::string(req["X-IM-Timestamp"]);
  const auto signature = std::string(req["X-IM-Signature"]);
  if (timestamp.empty() || signature.empty()) {
    return false;
  }
  int64_t ts = 0;
  try {
    ts = std::stoll(timestamp);
  } catch (const std::exception&) {
    return false;
  }
  const int64_t now = std::chrono::duration_cast<std::chrono::seconds>(
                          std::chrono::system_clock::now().time_since_epoch())
                          .count();
  if (ts < now - 60 || ts > now + 60) {
    return false;
  }
  const std::string data = timestamp + "\n" + std::string(req.method_string()) + "\n" +
                           std::string(req.target()) + "\n" + req.body();
  const auto expected = hmac_sha256_hex(cfg_.internal_secret, data);
  return expected.size() == signature.size() &&
         CRYPTO_memcmp(expected.data(), signature.data(), expected.size()) == 0;
}

HttpApi::response_type HttpApi::internal_route(
    const http::request<http::string_body>& req, const Target& target) {
  if (target.path == "/internal/healthz") {
    return json_response(req, http::status::ok, {{"ok", true}});
  }
  if (target.path == "/internal/readyz") {
    const bool ready = messages_.ready() && redis_.ping();
    return json_response(req, ready ? http::status::ok : http::status::service_unavailable,
                         {{"ok", ready}});
  }
  if (target.path == "/internal/stats") {
    return json_response(req, http::status::ok,
                         {{"online", registry_.online_count()}});
  }

  nlohmann::json body;
  try {
    body = req.body().empty() ? nlohmann::json::object()
                              : nlohmann::json::parse(req.body());
  } catch (const std::exception&) {
    return error_response(req, http::status::unprocessable_entity, 42201, "body 不合法");
  }

  try {
    if (target.path == "/internal/accounts/ensure") {
      messages_.users().ensure(body.at("uid").get<uint64_t>(),
                               body.value("nickname", std::string()));
      return json_response(req, http::status::ok, {{"ok", true}});
    }
    if (target.path == "/internal/profile") {
      std::optional<std::string> nickname;
      std::optional<std::string> avatar;
      if (body.contains("nickname")) {
        nickname = body["nickname"].get<std::string>();
      }
      if (body.contains("avatar")) {
        avatar = body["avatar"].get<std::string>();
      }
      messages_.update_profile(body.at("uid").get<uint64_t>(), nickname, avatar);
      return json_response(req, http::status::ok, {{"ok", true}});
    }
    if (target.path == "/internal/send") {
      SendRequest request;
      request.from = body.at("from").get<uint64_t>();
      request.to = body.at("to").get<uint64_t>();
      request.client_msg_id = "sys-" + random_uuid();
      const auto kind = body.value("kind", std::string("text"));
      if (kind == "text") {
        request.kind = 1;
        request.text = body.value("text", std::string());
      } else {
        request.kind = 2;
        request.custom = body.at("custom");
      }
      const auto result = messages_.send(request);
      if (const auto* ok = std::get_if<SendResult>(&result)) {
        registry_.send_to(request.to, build_message_frame(*ok, request, messages_.signer()));
        return json_response(req, http::status::ok,
                             {{"ok", true},
                              {"msg_id", std::to_string(ok->msg_id)},
                              {"seq", ok->seq}});
      }
      return error_response(req, http::status::bad_request, std::get<int>(result),
                            "发送失败");
    }
    if (target.path == "/internal/blacklist") {
      const auto owner = body.at("owner").get<uint64_t>();
      const auto peer = body.at("peer").get<uint64_t>();
      if (body.value("action", std::string("add")) == "add") {
        messages_.blacklist_add(owner, peer);
      } else {
        messages_.blacklist_remove(owner, peer);
      }
      return json_response(req, http::status::ok, {{"ok", true}});
    }
    if (target.path == "/internal/kick") {
      const auto uid = body.at("uid").get<uint64_t>();
      registry_.kick(uid, "banned");
      if (body.value("block", false)) {
        redis_.setex("im:block:" + std::to_string(uid), 86400, "1");
      }
      return json_response(req, http::status::ok, {{"ok", true}});
    }
    if (target.path == "/internal/unblock") {
      redis_.del("im:block:" + std::to_string(body.at("uid").get<uint64_t>()));
      return json_response(req, http::status::ok, {{"ok", true}});
    }
    if (target.path == "/internal/pair") {
      const auto a = body.at("a").get<uint64_t>();
      const auto b = body.at("b").get<uint64_t>();
      if (a == 0 || b == 0 || a == b) {
        return error_response(req, http::status::unprocessable_entity, 42201, "参数不合法");
      }
      if (body.value("action", std::string("add")) == "add") {
        messages_.pair_add(a, b);
      } else {
        messages_.pair_remove(a, b);
      }
      return json_response(req, http::status::ok, {{"ok", true}});
    }
    if (target.path == "/internal/session_version") {
      const auto uid = body.at("uid").get<uint64_t>();
      const auto version = body.at("version").get<int64_t>();
      messages_.users().set_session_version(uid, version);
      return json_response(req, http::status::ok, {{"ok", true}});
    }
    if (target.path == "/internal/delete_account") {
      const auto uid = body.at("uid").get<uint64_t>();
      registry_.kick(uid, "deleted");
      redis_.setex("im:block:" + std::to_string(uid), 86400, "1");
      const bool ok = messages_.delete_account(uid);
      return json_response(req, ok ? http::status::ok : http::status::internal_server_error,
                           {{"ok", ok}});
    }
  } catch (const std::exception&) {
    return error_response(req, http::status::unprocessable_entity, 42201, "参数不合法");
  }
  return error_response(req, http::status::not_found, 40401, "not found");
}

HttpApi::response_type HttpApi::route(const http::request<http::string_body>& req,
                                      bool loopback) {
  const auto target = parse_target(std::string(req.target()));
  if (target.path.rfind("/internal/", 0) == 0) {
    if (!loopback) {
      return error_response(req, http::status::forbidden, 40301, "forbidden");
    }
    if (target.path != "/internal/healthz" && target.path != "/internal/readyz" &&
        !verify_internal(req)) {
      return error_response(req, http::status::unauthorized, 40101, "bad signature");
    }
    return internal_route(req, target);
  }
  if (target.path != "/im/api/conversations" && target.path != "/im/api/messages" &&
      target.path != "/im/api/search") {
    return error_response(req, http::status::not_found, 40401, "not found");
  }

  const auto uid = authenticate(req);
  if (!uid.has_value()) {
    return error_response(req, http::status::unauthorized, 40101, "登录已过期");
  }

  const int64_t now_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
                             std::chrono::system_clock::now().time_since_epoch())
                             .count();

  if (target.path == "/im/api/conversations") {
    if (!read_table_.allow(*uid, now_ms)) {
      return error_response(req, http::status::too_many_requests, 42901,
                            "请求过于频繁,请稍后再试");
    }
    const int limit = static_cast<int>(std::clamp<uint64_t>(
        query_uint(target, "limit", 100), 1, 200));
    nlohmann::json items = nlohmann::json::array();
    for (const auto& view : messages_.list_conversations(*uid, limit)) {
      nlohmann::json item = {{"peer", {{"id", peer_id(view.peer.id)},
                                       {"nickname", view.peer.nickname},
                                       {"avatar", view.peer.avatar}}},
                             {"unread", view.unread},
                             {"last_seq", view.last_seq},
                             {"updated_at", view.updated_at}};
      if (view.has_last) {
        item["last_message"] = message_json(view.last, messages_.users(), messages_.signer());
      }
      items.push_back(std::move(item));
    }
    response_type response(http::status::ok, req.version());
    response.set(http::field::content_type, "application/json");
    response.body() = nlohmann::json{{"items", items}, {"has_more", false}}.dump();
    response.prepare_payload();
    return response;
  }

  if (target.path == "/im/api/search") {
    if (!search_table_.allow(*uid, now_ms)) {
      return error_response(req, http::status::too_many_requests, 42901,
                            "搜索过于频繁,请稍后再试");
    }
    std::string keyword;
    if (const auto it = target.query.find("q"); it != target.query.end()) {
      keyword = trim_ascii(url_decode(it->second));
    }
    // 150 字节 ≈ 50 个汉字;再长就没有搜索意义,也挡住超长串打库。
    if (keyword.empty() || keyword.size() > 150) {
      return error_response(req, http::status::unprocessable_entity, 42201, "关键词长度不合法");
    }
    const int limit =
        static_cast<int>(std::clamp<uint64_t>(query_uint(target, "limit", 20), 1, 50));
    const uint64_t before_id = query_uint(target, "before_id", 0);
    // 多取一条判断 has_more,不靠 rows.size()==limit 猜。
    auto rows = messages_.search(*uid, keyword, before_id, limit + 1);
    const bool has_more = rows.size() > static_cast<std::size_t>(limit);
    if (has_more) {
      rows.resize(static_cast<std::size_t>(limit));
    }
    nlohmann::json items = nlohmann::json::array();
    for (const auto& row : rows) {
      nlohmann::json item = message_json(row, messages_.users(), messages_.signer());
      const uint64_t peer = row.from_id == *uid ? row.to_id : row.from_id;
      nlohmann::json profile = {{"id", peer_id(peer)}, {"nickname", ""}, {"avatar", ""}};
      if (auto user = messages_.users().get(peer)) {
        profile["nickname"] = user->nickname;
        profile["avatar"] = user->avatar;
      }
      item["peer"] = std::move(profile);
      items.push_back(std::move(item));
    }
    return json_response(req, http::status::ok, {{"items", items}, {"has_more", has_more}});
  }

  if (!read_table_.allow(*uid, now_ms)) {
    return error_response(req, http::status::too_many_requests, 42901,
                          "请求过于频繁,请稍后再试");
  }
  std::string peer_text;
  if (const auto it = target.query.find("peer"); it != target.query.end()) {
    peer_text = it->second;
  }
  const auto peer = parse_peer(peer_text);
  if (!peer.has_value()) {
    return error_response(req, http::status::unprocessable_entity, 42201, "peer 不合法");
  }
  const uint64_t before = query_uint(target, "before_seq", 0);
  const int limit = static_cast<int>(std::clamp<uint64_t>(
      query_uint(target, "limit", 50), 1, 100));
  nlohmann::json items = nlohmann::json::array();
  const auto rows = messages_.list_messages(*uid, *peer, before, limit);
  for (const auto& row : rows) {
    items.push_back(message_json(row, messages_.users(), messages_.signer()));
  }
  response_type response(http::status::ok, req.version());
  response.set(http::field::content_type, "application/json");
  response.body() =
      nlohmann::json{{"items", items}, {"has_more", rows.size() == static_cast<std::size_t>(limit)}}
          .dump();
  response.prepare_payload();
  return response;
}
