#pragma once
#include <boost/asio/io_context.hpp>
#include <boost/asio/ip/tcp.hpp>
#include <boost/beast/http.hpp>

#include <mutex>
#include <optional>
#include <string>
#include <map>
#include <unordered_map>

#include <nlohmann/json.hpp>

#include "config.h"
#include "service/message_service.h"
#include "service/session_registry.h"
#include "store/redis_client.h"
#include "util/ratelimit.h"

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
  /// 搜索限流:每账号 60 次/分钟、burst 20。
  ///
  /// Args:
  ///   uid: 请求者账号。
  ///   now_ms: 当前毫秒时间戳。
  ///
  /// Returns:
  ///   允许本次请求返回 true。
  bool allow_search(uint64_t uid, int64_t now_ms);

  /// 单账号的搜索令牌桶 + 最近活跃时间(用于清理)。
  struct SearchBucket {
    TokenBucket bucket{1.0, 20.0};
    int64_t seen_ms = 0;
  };

  boost::asio::io_context& io_;
  boost::asio::ip::tcp::acceptor acceptor_;
  Config cfg_;
  MessageService& messages_;
  SessionRegistry& registry_;
  RedisClient& redis_;
  // HTTP 处理跑在 IM_IO_THREADS(默认 2)个线程上,限流表要加锁。
  std::mutex search_mutex_;
  std::unordered_map<uint64_t, SearchBucket> search_buckets_;
};
