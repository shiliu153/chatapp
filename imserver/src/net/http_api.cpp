#include "net/http_api.h"

#include <boost/asio/strand.hpp>
#include <boost/beast/core.hpp>

#include <algorithm>
#include <chrono>
#include <map>
#include <stdexcept>
#include <string>

#include <nlohmann/json.hpp>

#include "auth/token.h"

namespace beast = boost::beast;
namespace http = beast::http;
namespace net = boost::asio;
using tcp = net::ip::tcp;

namespace {

struct Target {
  std::string path;
  std::map<std::string, std::string> query;
};

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

nlohmann::json message_json(const MessageRow& row, UserRepo& users) {
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
    if (row.kind == 1) {
      data["kind"] = "text";
      data["text"] = body.value("text", "");
    } else {
      data["kind"] = "custom";
      data["custom"] = body;
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
    auto response = std::make_shared<HttpApi::response_type>(api_.handle(request_));
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
                 RedisClient& redis)
    : io_(io), acceptor_(io), cfg_(cfg), messages_(messages), redis_(redis) {}

void HttpApi::start() {
  const auto colon = cfg_.listen_http.rfind(':');
  if (colon == std::string::npos) {
    throw std::runtime_error("invalid IM_LISTEN_HTTP");
  }
  const auto host = cfg_.listen_http.substr(0, colon);
  const auto port = std::stoi(cfg_.listen_http.substr(colon + 1));
  const tcp::endpoint endpoint(net::ip::make_address(host), static_cast<unsigned short>(port));
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

HttpApi::response_type HttpApi::handle(
    const http::request<http::string_body>& req) {
  try {
    return route(req);
  } catch (const std::exception&) {
    return error_response(req, http::status::internal_server_error, 50001, "内部错误");
  }
}

HttpApi::response_type HttpApi::route(const http::request<http::string_body>& req) {
  const auto target = parse_target(std::string(req.target()));
  if (target.path.rfind("/internal/", 0) == 0) {
    return error_response(req, http::status::not_found, 40401, "not found");
  }
  if (target.path != "/im/api/conversations" && target.path != "/im/api/messages") {
    return error_response(req, http::status::not_found, 40401, "not found");
  }

  const auto uid = authenticate(req);
  if (!uid.has_value()) {
    return error_response(req, http::status::unauthorized, 40101, "登录已过期");
  }

  if (target.path == "/im/api/conversations") {
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
        item["last_message"] = message_json(view.last, messages_.users());
      }
      items.push_back(std::move(item));
    }
    response_type response(http::status::ok, req.version());
    response.set(http::field::content_type, "application/json");
    response.body() = nlohmann::json{{"items", items}, {"has_more", false}}.dump();
    response.prepare_payload();
    return response;
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
    items.push_back(message_json(row, messages_.users()));
  }
  response_type response(http::status::ok, req.version());
  response.set(http::field::content_type, "application/json");
  response.body() =
      nlohmann::json{{"items", items}, {"has_more", rows.size() == static_cast<std::size_t>(limit)}}
          .dump();
  response.prepare_payload();
  return response;
}
