#include <boost/asio/io_context.hpp>
#include <boost/asio/signal_set.hpp>

#include <csignal>
#include <iostream>
#include <string>
#include <thread>
#include <vector>

#include "config.h"
#include "migrate.h"
#include "net/ws_server.h"
#include "service/session_registry.h"
#include "store/redis_client.h"
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

    RedisClient redis(cfg.redis_url);
    SessionRegistry registry(redis);
    boost::asio::io_context io;
    WsServer server(io, cfg, registry, redis);
    server.start();

    boost::asio::signal_set signals(io, SIGINT, SIGTERM);
    signals.async_wait([&server, &io](const boost::system::error_code& ec, int) {
      if (!ec) {
        server.stop();
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
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "fatal: " << error.what() << "\n";
    return 1;
  }
}
