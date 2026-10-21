#include <iostream>
#include <string>

#include "config.h"
#include "migrate.h"
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
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "fatal: " << error.what() << "\n";
    return 1;
  }
}
