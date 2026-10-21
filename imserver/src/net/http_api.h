#pragma once
#include <boost/asio/io_context.hpp>
#include <boost/asio/ip/tcp.hpp>
#include <boost/beast/http.hpp>

#include <optional>
#include <string>
#include <map>

#include <nlohmann/json.hpp>

#include "config.h"
#include "service/message_service.h"
#include "service/session_registry.h"
#include "store/redis_client.h"

struct Target {
  std::string path;
  std::map<std::string, std::string> query;
};

class HttpApi {
 public:
  using response_type = boost::beast::http::response<boost::beast::http::string_body>;

  HttpApi(boost::asio::io_context& io, const Config& cfg, MessageService& messages,
          SessionRegistry& registry, RedisClient& redis);
  void start();
  void stop();

  response_type handle(
      const boost::beast::http::request<boost::beast::http::string_body>& req,
      bool loopback);

 private:
  void do_accept();
  response_type route(
      const boost::beast::http::request<boost::beast::http::string_body>& req,
      bool loopback);
  response_type internal_route(
      const boost::beast::http::request<boost::beast::http::string_body>& req,
      const Target& target);
  bool verify_internal(
      const boost::beast::http::request<boost::beast::http::string_body>& req);
  response_type json_response(
      const boost::beast::http::request<boost::beast::http::string_body>& req,
      boost::beast::http::status status, const nlohmann::json& body);
  response_type error_response(
      const boost::beast::http::request<boost::beast::http::string_body>& req,
      boost::beast::http::status status, int code, const std::string& message);
  std::optional<uint64_t> authenticate(
      const boost::beast::http::request<boost::beast::http::string_body>& req);

  boost::asio::io_context& io_;
  boost::asio::ip::tcp::acceptor acceptor_;
  Config cfg_;
  MessageService& messages_;
  SessionRegistry& registry_;
  RedisClient& redis_;
};
