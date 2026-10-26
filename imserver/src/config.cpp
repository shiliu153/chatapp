#include "config.h"

#include <cstdlib>
#include <stdexcept>

namespace {

std::string get_or(const std::map<std::string, std::string>& env,
                   const std::string& key, const std::string& fallback = "") {
  const auto it = env.find(key);
  return it == env.end() ? fallback : it->second;
}

int get_int(const std::map<std::string, std::string>& env,
            const std::string& key, int fallback) {
  const auto raw = get_or(env, key);
  if (raw.empty()) {
    return fallback;
  }
  try {
    const int value = std::stoi(raw);
    if (value <= 0) {
      throw std::runtime_error("invalid positive int for " + key);
    }
    return value;
  } catch (const std::exception&) {
    throw std::runtime_error("invalid int for " + key + ": " + raw);
  }
}

double get_double(const std::map<std::string, std::string>& env,
                  const std::string& key, double fallback) {
  const auto raw = get_or(env, key);
  if (raw.empty()) {
    return fallback;
  }
  try {
    const double value = std::stod(raw);
    if (value <= 0) {
      throw std::runtime_error("invalid positive double for " + key);
    }
    return value;
  } catch (const std::exception&) {
    throw std::runtime_error("invalid double for " + key + ": " + raw);
  }
}

std::size_t get_size(const std::map<std::string, std::string>& env,
                     const std::string& key, std::size_t fallback) {
  const auto raw = get_or(env, key);
  if (raw.empty()) {
    return fallback;
  }
  try {
    const auto value = std::stoull(raw);
    if (value == 0) {
      throw std::runtime_error("invalid positive size for " + key);
    }
    return static_cast<std::size_t>(value);
  } catch (const std::exception&) {
    throw std::runtime_error("invalid size for " + key + ": " + raw);
  }
}

std::vector<std::string> split_origins(const std::string& raw) {
  std::vector<std::string> out;
  std::size_t start = 0;
  while (start <= raw.size()) {
    const auto end = raw.find(',', start);
    auto item = raw.substr(start, end == std::string::npos ? std::string::npos : end - start);
    const auto first = item.find_first_not_of(" \t");
    const auto last = item.find_last_not_of(" \t");
    if (first != std::string::npos) {
      out.push_back(item.substr(first, last - first + 1));
    }
    if (end == std::string::npos) {
      break;
    }
    start = end + 1;
  }
  return out;
}

}  // namespace

MysqlDsn parse_mysql_dsn(const std::string& dsn) {
  constexpr const char* kPrefix = "mysql://";
  if (dsn.rfind(kPrefix, 0) != 0) {
    throw std::invalid_argument("mysql dsn must start with mysql://");
  }
  const auto rest = dsn.substr(std::string(kPrefix).size());
  const auto at = rest.rfind('@');
  if (at == std::string::npos) {
    throw std::invalid_argument("mysql dsn missing @");
  }
  const auto userinfo = rest.substr(0, at);
  const auto hostpart = rest.substr(at + 1);

  const auto colon = userinfo.find(':');
  if (colon == std::string::npos) {
    throw std::invalid_argument("mysql dsn missing password");
  }

  const auto slash = hostpart.find('/');
  if (slash == std::string::npos || slash + 1 >= hostpart.size()) {
    throw std::invalid_argument("mysql dsn missing database");
  }

  MysqlDsn out;
  out.user = userinfo.substr(0, colon);
  out.password = userinfo.substr(colon + 1);
  out.database = hostpart.substr(slash + 1);

  const auto hostport = hostpart.substr(0, slash);
  const auto port_colon = hostport.rfind(':');
  if (port_colon == std::string::npos) {
    out.host = hostport;
  } else {
    out.host = hostport.substr(0, port_colon);
    try {
      out.port = std::stoi(hostport.substr(port_colon + 1));
    } catch (const std::exception&) {
      throw std::invalid_argument("invalid mysql port");
    }
  }
  if (out.user.empty() || out.host.empty() || out.database.empty() || out.port <= 0) {
    throw std::invalid_argument("incomplete mysql dsn");
  }
  return out;
}

Config Config::from_map(const std::map<std::string, std::string>& env) {
  Config cfg;
  cfg.listen_ws = get_or(env, "IM_LISTEN_WS", cfg.listen_ws);
  cfg.listen_http = get_or(env, "IM_LISTEN_HTTP", cfg.listen_http);
  cfg.mysql_dsn = get_or(env, "IM_MYSQL_DSN");
  cfg.redis_url = get_or(env, "IM_REDIS_URL", cfg.redis_url);
  cfg.jwt_secret = get_or(env, "IM_JWT_SECRET");
  cfg.internal_secret = get_or(env, "IM_INTERNAL_SECRET");
  cfg.migrations_dir = get_or(env, "IM_MIGRATIONS_DIR", cfg.migrations_dir);
  cfg.allowed_origins = split_origins(get_or(env, "IM_ALLOWED_ORIGINS"));
  cfg.io_threads = get_int(env, "IM_IO_THREADS", cfg.io_threads);
  cfg.db_threads = get_int(env, "IM_DB_THREADS", cfg.db_threads);
  cfg.db_pool = get_int(env, "IM_DB_POOL", cfg.db_pool);
  cfg.db_idle_ping_ms = get_int(env, "IM_DB_IDLE_PING_MS", cfg.db_idle_ping_ms);
  cfg.max_conn_per_ip = get_int(env, "IM_MAX_CONN_PER_IP", cfg.max_conn_per_ip);
  cfg.auth_rate_per_sec = get_double(env, "IM_AUTH_RATE", cfg.auth_rate_per_sec);
  cfg.auth_burst = get_double(env, "IM_AUTH_BURST", cfg.auth_burst);
  cfg.max_frame = get_size(env, "IM_MAX_FRAME", cfg.max_frame);
  cfg.text_max = get_size(env, "IM_TEXT_MAX", cfg.text_max);

  if (cfg.mysql_dsn.empty()) {
    throw std::runtime_error("missing IM_MYSQL_DSN");
  }
  if (cfg.jwt_secret.empty()) {
    throw std::runtime_error("missing IM_JWT_SECRET");
  }
  if (cfg.internal_secret.empty()) {
    throw std::runtime_error("missing IM_INTERNAL_SECRET");
  }
  return cfg;
}

Config Config::from_env() {
  std::map<std::string, std::string> env;
  for (const char* key : {"IM_LISTEN_WS", "IM_LISTEN_HTTP", "IM_MYSQL_DSN",
                          "IM_REDIS_URL", "IM_JWT_SECRET", "IM_INTERNAL_SECRET",
                          "IM_MIGRATIONS_DIR", "IM_ALLOWED_ORIGINS", "IM_IO_THREADS",
                          "IM_DB_THREADS", "IM_DB_POOL", "IM_DB_IDLE_PING_MS",
                          "IM_MAX_CONN_PER_IP",
                          "IM_AUTH_RATE", "IM_AUTH_BURST", "IM_MAX_FRAME",
                          "IM_TEXT_MAX"}) {
    if (const char* value = std::getenv(key)) {
      env.emplace(key, value);
    }
  }
  return from_map(env);
}
