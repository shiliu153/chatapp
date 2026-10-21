#pragma once
#include <boost/asio/io_context.hpp>
#include <boost/asio/ip/tcp.hpp>
#include <boost/asio/steady_timer.hpp>
#include <boost/asio/thread_pool.hpp>
#include <boost/beast/core.hpp>
#include <boost/beast/http.hpp>
#include <boost/beast/websocket.hpp>

#include <nlohmann/json.hpp>

#include <chrono>
#include <cstdint>
#include <deque>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <unordered_map>
#include <variant>

#include "config.h"
#include "service/message_service.h"
#include "service/session_registry.h"
#include "store/redis_client.h"
#include "util/ratelimit.h"

class IpCounter {
 public:
  bool acquire(const std::string& ip);
  void release(const std::string& ip);
  bool allow_auth(const std::string& ip, int64_t now_ms);

 private:
  std::mutex mutex_;
  std::unordered_map<std::string, int> counts_;
  std::unordered_map<std::string, TokenBucket> auth_buckets_;
};

class WsSession : public std::enable_shared_from_this<WsSession> {
 public:
  using tcp = boost::asio::ip::tcp;
  using WsStream = boost::beast::websocket::stream<boost::beast::tcp_stream>;

  WsSession(tcp::socket socket, const Config& cfg, SessionRegistry& registry,
            RedisClient& redis, IpCounter& ip_counter, MessageService& messages,
            boost::asio::thread_pool& db_pool);

  void run();
  void kick(const std::string& reason);
  void send_raw(std::string frame);

 private:
  void on_http_read(boost::beast::error_code ec, std::size_t bytes);
  void on_accept(boost::beast::error_code ec);
  void do_read();
  void on_read(boost::beast::error_code ec, std::size_t bytes);
  void on_frame(const std::string& payload);
  void handle_auth(const nlohmann::json& frame);
  void handle_send(const nlohmann::json& frame);
  void on_send_result(const std::variant<SendResult, int>& result,
                      const SendRequest& request);
  void send_json(const std::string& payload);
  void do_write();
  void on_write(boost::beast::error_code ec, std::size_t bytes);
  void do_close(int code);
  void on_close(boost::beast::error_code ec);
  void reject_http(int status, const std::string& message);
  void arm_auth_timer();
  void arm_idle_timer();
  void refresh_online();
  std::string remote_ip();
  bool origin_allowed() const;
  void release_ip();

  WsStream ws_;
  boost::beast::flat_buffer buffer_;
  boost::beast::http::request<boost::beast::http::string_body> request_;
  std::deque<std::string> outbox_;
  std::size_t outbox_bytes_ = 0;
  bool authed_ = false;
  bool writing_ = false;
  bool closing_ = false;
  bool released_ip_ = false;
  bool ip_acquired_ = false;
  std::optional<int> close_code_;
  uint64_t uid_ = 0;
  std::string client_ip_;
  Config cfg_;
  SessionRegistry& registry_;
  RedisClient& redis_;
  IpCounter& ip_counter_;
  MessageService& messages_;
  boost::asio::thread_pool& db_pool_;
  boost::asio::steady_timer auth_timer_;
  boost::asio::steady_timer idle_timer_;
  std::chrono::steady_clock::time_point last_frame_;
  TokenBucket send_bucket_{20, 40};
};

class WsServer {
 public:
  WsServer(boost::asio::io_context& io, const Config& cfg, SessionRegistry& registry,
           RedisClient& redis, MessageService& messages, boost::asio::thread_pool& db_pool);
  void start();
  void stop();

 private:
  void do_accept();

  boost::asio::io_context& io_;
  boost::asio::ip::tcp::acceptor acceptor_;
  Config cfg_;
  SessionRegistry& registry_;
  RedisClient& redis_;
  MessageService& messages_;
  boost::asio::thread_pool& db_pool_;
  IpCounter ip_counter_;
};
