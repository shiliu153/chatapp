/*********************************************************************************************************************
* chat_app 自建 IM 服务端（imserver）是本项目唯一的 IM 后端，C++20 实现，对外提供 WebSocket :9100 与 HTTP :9101
* Copyright (c) 2026 shiliu153
*
* 本文件是 chat_app 自建 IM 服务端的一部分
*
* 额外注明：
* 本文件使用 MIT 开源许可证协议 许可申明英文版见仓库根目录 LICENSE 文件
* 欢迎各位使用并传播本程序 但修改内容时必须保留作者的版权声明（即本声明）
*
* 文件名称          src/config.cpp
* 项目名称          chat_app / imserver
* 公司名称          个人项目（shiliu153）
* 版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
* 开发环境          CMake 3.22 + g++ (C++20) Linux x86_64
* 适用平台          Linux x86_64 服务端
* 仓库地址          https://github.com/shiliu153/chatapp
*
* 修改记录
* 日期              作者               备注
* 2026-11-14        shiliu153          补齐文件头与函数注释
********************************************************************************************************************/

#include "config.h"

#include <cstdlib>
#include <stdexcept>

#include "util/log.h"

namespace {

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     读取环境变量 缺失时回退默认值
// 参数说明     env              环境变量映射
//              key              变量名
//              fallback         缺失时的默认值 默认空串
// 返回参数     std::string      变量值或默认值
// 使用示例     const std::string listen = get_or(env, "IM_LISTEN_WS", "127.0.0.1:9100");
// 备注信息     空字符串与缺失等价 是否必填由调用方判断
//-------------------------------------------------------------------------------------------------------------------
std::string get_or(const std::map<std::string, std::string>& env,
                   const std::string& key, const std::string& fallback = "") {
  const auto it = env.find(key);
  return it == env.end() ? fallback : it->second;
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     读取正整数型环境变量
// 参数说明     env              环境变量映射
//              key              变量名
//              fallback         缺失时的默认值
// 返回参数     int              解析后的正整数
// 使用示例     cfg.io_threads = get_int(env, "IM_IO_THREADS", 2);
// 备注信息     空值取默认;非数字或小于等于 0 抛 std::runtime_error 让启动失败而不是静默降级
//-------------------------------------------------------------------------------------------------------------------
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     读取正浮点型环境变量
// 参数说明     env              环境变量映射
//              key              变量名
//              fallback         缺失时的默认值
// 返回参数     double           解析后的正浮点数
// 使用示例     cfg.auth_rate_per_sec = get_double(env, "IM_AUTH_RATE", 1.0);
// 备注信息     空值取默认;非数字或小于等于 0 抛 std::runtime_error 与整数版同口径
//-------------------------------------------------------------------------------------------------------------------
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     读取正容量型环境变量
// 参数说明     env              环境变量映射
//              key              变量名
//              fallback         缺失时的默认值
// 返回参数     std::size_t      解析后的正容量值
// 使用示例     cfg.max_frame = get_size(env, "IM_MAX_FRAME", 8192);
// 备注信息     0 视为非法 用于帧长 文本长 队列长度这类按字节或条数计的配置
//-------------------------------------------------------------------------------------------------------------------
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     按逗号切分列表并去掉首尾空白
// 参数说明     raw              逗号分隔的原始字符串
// 返回参数     std::vector<std::string>     切好的条目 空条目丢弃
// 使用示例     const auto list = split_origins("127.0.0.1, ::1");
// 备注信息     Origin 白名单 可信代理 内部接口来源网段三处共用同一份切分逻辑
//-------------------------------------------------------------------------------------------------------------------
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     解析 mysql:// 形式的 DSN
// 参数说明     dsn              形如 mysql://user:pass@host:3306/db 的字符串
// 返回参数     MysqlDsn         拆好的用户名 密码 主机 端口 库名
// 使用示例     const MysqlDsn dsn = parse_mysql_dsn(cfg.mysql_dsn);
// 备注信息     先校验 mysql:// 前缀 再用最后一个 @ 分用户信息与主机段 省略端口时默认 3306 结构不全抛 std::invalid_argument
//-------------------------------------------------------------------------------------------------------------------
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     把环境变量映射转换成配置对象
// 参数说明     env              变量名到值的映射
// 返回参数     Config           填好的配置对象
// 使用示例     Config cfg = Config::from_map(env);
// 备注信息     集中读取 IM_ 变量并做类型转换 最后校验 IM_MYSQL_DSN IM_JWT_SECRET IM_INTERNAL_SECRET IM_MEDIA_PREFIX 四项必填
//-------------------------------------------------------------------------------------------------------------------
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
  cfg.trusted_proxies = split_origins(get_or(env, "IM_TRUSTED_PROXIES", "127.0.0.1,::1"));
  cfg.internal_allow = split_origins(get_or(env, "IM_INTERNAL_ALLOW", "127.0.0.1,::1"));
  cfg.allow_public_bind = get_or(env, "IM_ALLOW_PUBLIC_BIND") == "1";
  cfg.io_threads = get_int(env, "IM_IO_THREADS", cfg.io_threads);
  cfg.db_threads = get_int(env, "IM_DB_THREADS", cfg.db_threads);
  cfg.db_pool = get_int(env, "IM_DB_POOL", cfg.db_pool);
  cfg.db_idle_ping_ms = get_int(env, "IM_DB_IDLE_PING_MS", cfg.db_idle_ping_ms);
  cfg.db_connect_wait_ms = get_int(env, "IM_DB_CONNECT_WAIT_MS", cfg.db_connect_wait_ms);
  cfg.max_conn_per_ip = get_int(env, "IM_MAX_CONN_PER_IP", cfg.max_conn_per_ip);
  cfg.auth_rate_per_sec = get_double(env, "IM_AUTH_RATE", cfg.auth_rate_per_sec);
  cfg.auth_burst = get_double(env, "IM_AUTH_BURST", cfg.auth_burst);
  cfg.send_per_minute = get_int(env, "IM_SEND_PER_MINUTE", cfg.send_per_minute);
  cfg.max_frame = get_size(env, "IM_MAX_FRAME", cfg.max_frame);
  cfg.text_max = get_size(env, "IM_TEXT_MAX", cfg.text_max);
  cfg.sensitive_words_file =
      get_or(env, "IM_SENSITIVE_WORDS_FILE", cfg.sensitive_words_file);
  cfg.media_prefix = get_or(env, "IM_MEDIA_PREFIX");
  cfg.media_sign_secret = get_or(env, "IM_MEDIA_SIGN_SECRET");
  cfg.media_sign_ttl = get_int(env, "IM_MEDIA_SIGN_TTL", cfg.media_sign_ttl);
  cfg.push_url = get_or(env, "IM_PUSH_URL");
  cfg.push_timeout_ms = get_int(env, "IM_PUSH_TIMEOUT_MS", cfg.push_timeout_ms);
  cfg.push_queue = get_size(env, "IM_PUSH_QUEUE", cfg.push_queue);

  if (cfg.mysql_dsn.empty()) {
    throw std::runtime_error("missing IM_MYSQL_DSN");
  }
  if (cfg.jwt_secret.empty()) {
    throw std::runtime_error("missing IM_JWT_SECRET");
  }
  if (cfg.internal_secret.empty()) {
    throw std::runtime_error("missing IM_INTERNAL_SECRET");
  }
  if (cfg.media_prefix.empty()) {
    throw std::runtime_error("missing IM_MEDIA_PREFIX");
  }
  if (cfg.media_sign_secret.empty()) {
    // 不致命(本地/测试不配也能跑),但生产漏配会让图片/语音 URL 不带签名,
    // 经 nginx 验签后全部 403 —— 必须让人一眼看到(L-7)。
    log_warn("media_sign_disabled",
             {{"hint", "IM_MEDIA_SIGN_SECRET 未配置:聊天图片/语音将不带签名"}});
  }
  return cfg;
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     从进程环境变量构建配置
// 参数说明     无
// 返回参数     Config           填好的配置对象
// 使用示例     const Config cfg = Config::from_env();
// 备注信息     只白名单读取 29 个 IM_ 变量 未列出的变量一律忽略 内部转调 from_map
//-------------------------------------------------------------------------------------------------------------------
Config Config::from_env() {
  std::map<std::string, std::string> env;
  for (const char* key : {"IM_LISTEN_WS", "IM_LISTEN_HTTP", "IM_MYSQL_DSN",
                          "IM_REDIS_URL", "IM_JWT_SECRET", "IM_INTERNAL_SECRET",
                          "IM_MIGRATIONS_DIR", "IM_ALLOWED_ORIGINS", "IM_TRUSTED_PROXIES",
                          "IM_INTERNAL_ALLOW",
                          "IM_ALLOW_PUBLIC_BIND", "IM_IO_THREADS",
                          "IM_DB_THREADS", "IM_DB_POOL", "IM_DB_IDLE_PING_MS",
                          "IM_DB_CONNECT_WAIT_MS",
                          "IM_MAX_CONN_PER_IP",
                          "IM_AUTH_RATE", "IM_AUTH_BURST", "IM_MAX_FRAME",
                          "IM_SEND_PER_MINUTE",
                          "IM_TEXT_MAX", "IM_SENSITIVE_WORDS_FILE",
                          "IM_MEDIA_PREFIX", "IM_MEDIA_SIGN_SECRET",
                          "IM_MEDIA_SIGN_TTL", "IM_PUSH_URL", "IM_PUSH_TIMEOUT_MS",
                          "IM_PUSH_QUEUE"}) {
    if (const char* value = std::getenv(key)) {
      env.emplace(key, value);
    }
  }
  return from_map(env);
}
