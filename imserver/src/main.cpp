#include <boost/asio/io_context.hpp>
#include <boost/asio/signal_set.hpp>
#include <boost/asio/thread_pool.hpp>

#include <csignal>
#include <iostream>
#include <string>
#include <thread>
#include <vector>

#include "config.h"
#include "migrate.h"
#include "net/guard.h"
#include "net/http_api.h"
#include "net/ws_server.h"
#include "service/message_service.h"
#include "service/session_registry.h"
#include "store/blacklist_repo.h"
#include "store/conversation_repo.h"
#include "store/message_repo.h"
#include "store/mysql_pool.h"
#include "store/redis_client.h"
#include "store/user_repo.h"
#include "util/log.h"

int main(int argc, char** argv) {
  try {
    const auto cfg = Config::from_env();
    log_info("startup", {{"listen_ws", cfg.listen_ws},
                         {"listen_http", cfg.listen_http},
                         {"io_threads", std::to_string(cfg.io_threads)}});
    if (argc > 1 && std::string(argv[1]) == "--migrate") {
      run_migrations(cfg);
      return 0;
    }

    // L9:默认只监听回环 —— 9101 的内部接口只靠「回环 + HMAC」保护,9100 也假定前面
    // 一定有 nginx。要监听非回环地址必须显式设 IM_ALLOW_PUBLIC_BIND=1,避免部署时
    // 手滑写成 0.0.0.0 把管理接口和伪造 X-Real-IP 的入口一起暴露出去。
    if (!cfg.allow_public_bind) {
      for (const auto& raw : {cfg.listen_ws, cfg.listen_http}) {
        if (!net_guard::is_loopback(net_guard::parse_listen(raw).address)) {
          throw std::runtime_error("listen address " + raw +
                                   " is not loopback; set IM_ALLOW_PUBLIC_BIND=1 if intentional");
        }
      }
    }
    if (cfg.allowed_origins.empty()) {
      log_warn("allowed_origins_empty", {{"policy", "same-origin-fallback"}});
    }
    if (cfg.trusted_proxies.empty()) {
      // 可信代理为空 = 所有连接的客户端 IP 都是对端地址;nginx 反代时全站会挤在
      // 127.0.0.1 一个 key 上,单 IP 连接数/鉴权限流会误伤正常用户。
      log_warn("trusted_proxies_empty", {{"policy", "peer-address-only"}});
    }

    MysqlPool mysql(parse_mysql_dsn(cfg.mysql_dsn), cfg.db_pool,
                    cfg.db_idle_ping_ms);
    UserRepo users(mysql);
    ConversationRepo conversations(mysql);
    MessageRepo messages(mysql);
    BlacklistRepo blacklist(mysql);
    MessageService message_service(mysql, users, conversations, messages, blacklist,
                                   cfg.text_max, cfg.media_prefix,
                                   cfg.media_sign_secret, cfg.media_sign_ttl);

    RedisClient redis(cfg.redis_url);
    SessionRegistry registry(redis);
    boost::asio::io_context io;
    boost::asio::thread_pool db_pool(static_cast<std::size_t>(cfg.db_threads));
    WsServer server(io, cfg, registry, redis, message_service, db_pool);
    server.start();
    HttpApi http(io, cfg, message_service, registry, redis);
    http.start();

    boost::asio::signal_set signals(io, SIGINT, SIGTERM);
    signals.async_wait([&server, &http, &io](const boost::system::error_code& ec, int) {
      if (!ec) {
        server.stop();
        http.stop();
        io.stop();
      }
    });

    std::vector<std::thread> threads;
    threads.reserve(static_cast<std::size_t>(cfg.io_threads));
    for (int i = 0; i < cfg.io_threads; ++i) {
      threads.emplace_back([&io] { io.run(); });
    }
    for (auto& thread : threads) {
      thread.join();
    }
    db_pool.join();
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "fatal: " << error.what() << "\n";
    return 1;
  }
}
