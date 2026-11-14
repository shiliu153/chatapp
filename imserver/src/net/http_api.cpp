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
* 文件名称          src/net/http_api.cpp
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
#include "net/http_api.h"

#include <boost/asio/strand.hpp>
#include <boost/beast/core.hpp>

#include <algorithm>
#include <chrono>
#include <iterator>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>

#include <openssl/crypto.h>
#include <nlohmann/json.hpp>

#include "auth/token.h"
#include "net/frames.h"
#include "net/guard.h"
#include "util/hmac.h"
#include "util/metrics.h"
#include "util/uuid.h"

namespace beast = boost::beast;
namespace http = beast::http;
namespace net = boost::asio;
using tcp = net::ip::tcp;

namespace {

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     把请求目标拆成路径与查询参数表
// 参数说明     target           形如 /im/api/search?q=abc&limit=20 的原始目标
// 返回参数     Target           路径与未解码的键值表
// 使用示例     const auto target = parse_target("/im/api/search?q=abc");
// 备注信息     只按 & 与 = 切分 不做百分号解码 没有 = 的段直接丢弃
//              重复键后者覆盖前者 需要解码的调用方自己调 url_decode
//-------------------------------------------------------------------------------------------------------------------
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     读取查询参数里的无符号整数
// 参数说明     target           已解析的请求目标
//              key              参数名
//              fallback         缺失或无法解析时的默认值
// 返回参数     uint64_t         解析结果或默认值
// 使用示例     const auto limit = query_uint(target, "limit", 50);
// 备注信息     用 std::stoull 解析 不校验尾部与负号 调用方拿到后要自己 clamp
//-------------------------------------------------------------------------------------------------------------------
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     解析 u12 形式的对端 id 串
// 参数说明     peer             形如 u12 的对端 id 或字面量 system_notice
// 返回参数     std::optional<uint64_t>     system_notice 映射为 0 无法解析返回 nullopt
// 使用示例     const auto peer = parse_peer("u12");
// 备注信息     只要求以 u 开头 数字部分交给 std::stoull 尾部多余字符会被忽略
//              拿到 nullopt 的调用方按 42201 处理
//-------------------------------------------------------------------------------------------------------------------
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

// `peer_id()` 与 `message_json()` 都在 `net/frames.h` —— 下行 `message` 帧与这里的
// HTTP 响应必须共用同一个序列化函数(批次 L-2 的引用就是这么漏的)。

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     把单个十六进制字符转成数值
// 参数说明     c                待转换字符 0-9 a-f A-F
// 返回参数     int              0 到 15 非十六进制字符返回 -1
// 使用示例     const int low = hex_value('f');
// 备注信息     大小写都接受 只给 url_decode 用
//-------------------------------------------------------------------------------------------------------------------
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
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     对查询参数做百分号解码
// 参数说明     input            原始串
// 返回参数     std::string      解码后的串
// 使用示例     const auto keyword = url_decode(it->second);
// 备注信息     + 当空格处理 与 Web 端 URLSearchParams 的编码一致
//              % 后不足两位或不是合法十六进制时原样保留 不报错
//-------------------------------------------------------------------------------------------------------------------
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     去掉字符串两端的 ASCII 空白
// 参数说明     input            原始串
// 返回参数     std::string      去掉首尾空白后的副本
// 使用示例     const auto keyword = trim_ascii(url_decode(it->second));
// 备注信息     全空白返回空串 与 net/guard.cpp 的同名函数各留一份 互不依赖
//-------------------------------------------------------------------------------------------------------------------
std::string trim_ascii(const std::string& input) {
  const auto begin = input.find_first_not_of(" \t\r\n");
  if (begin == std::string::npos) {
    return "";
  }
  const auto end = input.find_last_not_of(" \t\r\n");
  return input.substr(begin, end - begin + 1);
}

/// 一条消息的 JSON:**转调 `frames.h::message_json`**,不再在这里另写一份。
///
/// Args:
///   row: 库里的消息行。
///   users: 账号仓库(只为取发送者画像,取不到就不下发 `from_profile`)。
///   signer: 媒体签名器。
///
/// Returns:
///   消息的 `data` 对象。
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     从消息行与账号仓库拼出消息 JSON
// 参数说明     row              库里的消息行
//              users            账号仓库 只为取发送者画像
//              signer           媒体签名器
// 返回参数     nlohmann::json     消息的 data 对象
// 使用示例     const auto item = message_json_of(row, messages_.users(), messages_.signer());
// 备注信息     转调 frames.h::message_json HTTP 与 WS 共用同一份序列化
//              取不到发送者画像就不下发 from_profile
//-------------------------------------------------------------------------------------------------------------------
nlohmann::json message_json_of(const MessageRow& row, UserRepo& users,
                               const MediaSigner& signer) {
  return message_json(row, users.get(row.from_id), signer);
}

/// 从会话标志位的请求体里取一个**可选**布尔开关(批次 N)。
///
/// 「可选」的语义要落在类型上:`nullopt` = 这次请求不改这一项,与 `false` 不同 ——
/// 用 `false` 当缺省值会把「只改 muted」的请求当成「顺便取消置顶」。
///
/// Args:
///   body: 已解析的请求体(必须是 JSON 对象)。
///   key: 字段名,`pinned` 或 `muted`。
///   value: 出参;字段不存在时保持 `nullopt`。
///
/// Returns:
///   字段缺省或类型正确时为 true;字段存在但不是布尔时为 false(调用方回 42201)。
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     从请求体里取可选的布尔开关
// 参数说明     body             已解析的请求体 必须是 JSON 对象
//              key              字段名 pinned 或 muted
//              value            出参 字段不存在时保持 nullopt
// 返回参数     bool             字段缺省或类型正确返回 true 存在但不是布尔返回 false
// 使用示例     if (!read_flag(body, "pinned", pinned)) { /* 回 42201 */ }
// 备注信息     nullopt 表示这一项不改 与 false 语义不同 缺省值写 false 会误改另一项
//-------------------------------------------------------------------------------------------------------------------
bool read_flag(const nlohmann::json& body, const char* key, std::optional<bool>& value) {
  const auto it = body.find(key);
  if (it == body.end()) {
    return true;
  }
  if (!it->is_boolean()) {
    return false;
  }
  value = it->get<bool>();
  return true;
}

/// 解析一个 msg_id(批次 T 的多选删除)。
///
/// 契约允许字符串或整数两种写法(App 的 `msg_id` 一直是字符串,Web 侧可能直接传数字),
/// 但**不接受** 0、负数、非数字、超过 20 位的串 —— 这些都是「客户端写错了」,
/// 统一回 42201 而不是静默忽略(静默忽略只留给「不属于我」的合法 id)。
///
/// Args:
///   element: `ids` 数组里的一项。
///   value: 出参,解析成功时写入。
///
/// Returns:
///   解析成功返回 true。
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     解析多选删除里的单个消息 id
// 参数说明     element          ids 数组的一项 允许字符串或整数
//              value            出参 解析成功时写入
// 返回参数     bool             解析成功返回 true
// 使用示例     if (!parse_msg_id(element, id)) { /* 回 42201 */ }
// 备注信息     0 负数 非数字 超过 20 位 前缀 0 一律返回 false
//              这是「客户端写错了」不是「不属于我」 所以不静默忽略 调用方回 42201
//-------------------------------------------------------------------------------------------------------------------
bool parse_msg_id(const nlohmann::json& element, uint64_t& value) {
  if (element.is_number_unsigned()) {
    const auto parsed = element.get<uint64_t>();
    if (parsed == 0) {
      return false;
    }
    value = parsed;
    return true;
  }
  if (element.is_number_integer()) {
    const auto parsed = element.get<int64_t>();
    if (parsed <= 0) {
      return false;
    }
    value = static_cast<uint64_t>(parsed);
    return true;
  }
  if (!element.is_string()) {
    return false;
  }
  const auto text = element.get<std::string>();
  // uint64 最长 20 位;前缀 0 也拒(那不是 id 的正常写法,只可能是拼错了)。
  if (text.empty() || text.size() > 20 || text[0] == '0') {
    return false;
  }
  for (const char ch : text) {
    if (ch < '0' || ch > '9') {
      return false;
    }
  }
  try {
    value = std::stoull(text);
  } catch (const std::exception&) {
    return false;
  }
  return value != 0;
}

/// 多选删除单次最多处理的条数:再长客户端就该拆批,服务端也不为一次点击锁太多行。
constexpr std::size_t kDeleteMaxIds = 50;

}  // namespace

class HttpSession : public std::enable_shared_from_this<HttpSession> {
 public:
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     构造单条 HTTP 连接的会话
// 参数说明     socket           已接受的 TCP 套接字
//              api              所属 HttpApi 借用引用 生命周期由 main 保证
// 返回参数     void             构造函数 无返回值
// 使用示例     std::make_shared<HttpSession>(std::move(socket), *this)->run();
// 备注信息     一条连接只处理一个请求 响应写完即关闭 不做 keep-alive
//-------------------------------------------------------------------------------------------------------------------
  HttpSession(tcp::socket socket, HttpApi& api) : socket_(std::move(socket)), api_(api) {}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     启动异步读请求
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     session.run();
// 备注信息     先取 shared_from_this 延长生命周期 读完进 on_read
//-------------------------------------------------------------------------------------------------------------------
  void run() {
    auto self = shared_from_this();
    http::async_read(socket_, buffer_, request_,
                     [self](beast::error_code ec, std::size_t bytes) {
                       self->on_read(ec, bytes);
                     });
  }

 private:
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     请求读完后的处理 生成响应并异步写回
// 参数说明     ec               读错误码 非零直接返回
//              bytes            已读字节数 本实现未使用
// 返回参数     void             无返回值
// 使用示例     self->on_read(ec, bytes);
// 备注信息     取不到对端地址时用未指定地址 既非回环也不在允许网段 /metrics 与 /internal/* 因此 403
//              写完 shutdown 再 close 不做连接复用
//-------------------------------------------------------------------------------------------------------------------
  void on_read(beast::error_code ec, std::size_t bytes) {
    (void)bytes;
    if (ec) {
      return;
    }
    boost::system::error_code endpoint_error;
    const auto endpoint = socket_.remote_endpoint(endpoint_error);
    // 取不到对端地址时用未指定地址:既不是回环也不在允许网段内 → 一律 403(fail-closed)
    const boost::asio::ip::address peer =
        endpoint_error ? boost::asio::ip::address{} : endpoint.address();
    auto response = std::make_shared<HttpApi::response_type>(api_.handle(request_, peer));
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     构造 HTTP API 并解析内部接口来源网段
// 参数说明     io               事件循环 整个服务共用一个
//              cfg              服务配置 含 listen_http / jwt_secret / internal_secret / internal_allow
//              messages         消息服务
//              registry         会话注册表
//              redis            缓存客户端
//              push             离线新消息推送器
// 返回参数     void             构造函数 无返回值
// 使用示例     HttpApi api(io, cfg, messages, registry, redis, push);
// 备注信息     internal_allow_ 在这里一次性解析 IM_INTERNAL_ALLOW 非法条目直接抛异常
//-------------------------------------------------------------------------------------------------------------------
HttpApi::HttpApi(net::io_context& io, const Config& cfg, MessageService& messages,
                 SessionRegistry& registry, RedisClient& redis, PushNotifier& push)
    : io_(io), acceptor_(io), cfg_(cfg), messages_(messages), registry_(registry),
      redis_(redis), push_(push),
      internal_allow_(net_guard::ProxyTrust::from_list(cfg.internal_allow)) {}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     绑定监听端口并开始接受连接
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     api.start();
// 备注信息     监听地址来自 IM_LISTEN_HTTP 默认 127.0.0.1:9101
//              开了 reuse_address 便于重启时不被 TIME_WAIT 占住 非回环地址的校验在 main 启动时做
//-------------------------------------------------------------------------------------------------------------------
void HttpApi::start() {
  const auto listen = net_guard::parse_listen(cfg_.listen_http);
  const tcp::endpoint endpoint(listen.address, listen.port);
  acceptor_.open(endpoint.protocol());
  acceptor_.set_option(net::socket_base::reuse_address(true));
  acceptor_.bind(endpoint);
  acceptor_.listen(net::socket_base::max_listen_connections);
  do_accept();
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     关闭监听器 停止接受新连接
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     api.stop();
// 备注信息     只关 acceptor 已建立连接不受影响 关闭错误被忽略
//-------------------------------------------------------------------------------------------------------------------
void HttpApi::stop() {
  beast::error_code ec;
  acceptor_.close(ec);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     异步接受连接并为每条连接建会话
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     api.start();  // 内部已调用 do_accept
// 备注信息     每条连接跑在独立 strand 上 接受失败也继续续接 监听器关闭后直接返回
//-------------------------------------------------------------------------------------------------------------------
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     校验 Bearer 令牌并返回账号 id
// 参数说明     req              从 Authorization 头取令牌
// 返回参数     std::optional<uint64_t>     通过返回 uid 否则 nullopt
// 使用示例     const auto uid = authenticate(req);
// 备注信息     依次校验 Bearer 前缀 JWT 签名与过期 im:block: 封禁标记 会话版本
//              会话版本按令牌里的 ct claim 分端比对 与 WS 握手同口径 sv=0 的过渡期旧 token 放行
//-------------------------------------------------------------------------------------------------------------------
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
  // 多端(K-2):版本按端查(token 的 ct claim,缺省 app),与 WS 完全同一份判定。
  if (claims->sv != 0 &&
      !session_version_matches(
          claims->sv, messages_.users().session_version(claims->uid, claims->ct))) {
    return std::nullopt;
  }
  return claims->uid;
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     构造业务错误响应
// 参数说明     req              只用于取 HTTP 版本
//              status           HTTP 状态码
//              code             业务码
//              message          中文提示
// 返回参数     response_type     响应对象
// 使用示例     return error_response(req, http::status::unauthorized, 40101, "登录已过期");
// 备注信息     响应体只有 code 与 message 两个键 imserver 不带 request_id
//              业务码前三位通常与 HTTP 状态一致 400 承载 42201 是刻意例外
//-------------------------------------------------------------------------------------------------------------------
HttpApi::response_type HttpApi::error_response(
    const http::request<http::string_body>& req, http::status status, int code,
    const std::string& message) {
  response_type response(status, req.version());
  response.set(http::field::content_type, "application/json");
  response.body() = nlohmann::json{{"code", code}, {"message", message}}.dump();
  response.prepare_payload();
  return response;
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     构造 JSON 成功响应
// 参数说明     req              只用于取 HTTP 版本
//              status           HTTP 状态码
//              body             响应体 JSON
// 返回参数     response_type     响应对象
// 使用示例     return json_response(req, http::status::ok, {{"ok", true}});
// 备注信息     固定 Content-Type 为 application/json 并自动补 Content-Length
//-------------------------------------------------------------------------------------------------------------------
HttpApi::response_type HttpApi::json_response(
    const http::request<http::string_body>& req, http::status status,
    const nlohmann::json& body) {
  response_type response(status, req.version());
  response.set(http::field::content_type, "application/json");
  response.body() = body.dump();
  response.prepare_payload();
  return response;
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     处理一条已读完的 HTTP 请求
// 参数说明     req              已解析的请求
//              peer_addr        直连对端地址
// 返回参数     response_type     响应对象
// 使用示例     auto response = api.handle(request_, peer);
// 备注信息     所有异常兜成 500 + 50001 不向 io 线程抛 保证连接总能拿到响应
//-------------------------------------------------------------------------------------------------------------------
HttpApi::response_type HttpApi::handle(
    const http::request<http::string_body>& req,
    const boost::asio::ip::address& peer_addr) {
  try {
    return route(req, peer_addr);
  } catch (const std::exception&) {
    return error_response(req, http::status::internal_server_error, 50001, "内部错误");
  }
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     校验内部接口的 HMAC 签名与时间窗
// 参数说明     req              需带 X-IM-Timestamp 与 X-IM-Signature 两个头
// 返回参数     bool             校验通过返回 true
// 使用示例     if (!verify_internal(req)) { return error_response(req, http::status::unauthorized, 40101, "bad signature"); }
// 备注信息     签名原文是 timestamp method target body 四段按换行拼接 密钥为 IM_INTERNAL_SECRET
//              时间戳偏差超过 60 秒即拒 比较用 CRYPTO_memcmp 走常量时间
//-------------------------------------------------------------------------------------------------------------------
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     处理 /internal/* 内部管理接口
// 参数说明     req              已通过来源与签名校验的请求
//              target           已解析的路径与查询参数
// 返回参数     response_type     响应对象
// 使用示例     return internal_route(req, target);
// 备注信息     healthz readyz stats 三个只读探针不读请求体
//              其余九个接口按 path 分发 accounts/ensure profile send blacklist kick unblock pair session_version delete_account
//              请求体非 JSON 或字段缺失回 422 + 42201 发送失败回 400 加消息服务业务码 未匹配回 404 + 40401
//-------------------------------------------------------------------------------------------------------------------
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
        // 与 `/im/api/messages` 同一个构造函数(见 frames.h::message_json):
        // 灰条也是消息,少一处就会有一端看不到它。
        const bool delivered = registry_.send_to(
            request.to,
            build_message_frame(ok->row, messages_.users().get(ok->row.from_id),
                                messages_.signer()));
        // C-1:走内部 API 发出去的消息(im_send / Django 灰条)同样要照顾离线对端。
        // kind=2(灰条/系统通知)由 PushNotifier 自己过滤掉。
        if (!delivered) {
          push_.notify_offline_message(request.to, request.from, ok->msg_id, request.kind,
                                       request.text, ok->from_nickname);
        }
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
      // 多端(K-2):带 client_type 只踢该端 —— 这条只来自「同端换设备登录」(同类互顶),
      // 所以原因用 multi_device;缺省踢全部,保持封禁 / 注销的语义与原因(banned)不变。
      const auto client_type = body.value("client_type", std::string());
      if (client_type.empty()) {
        registry_.kick(uid, "banned");
      } else {
        registry_.kick_client(uid, normalize_client_type(client_type), "multi_device");
      }
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
      // 多端(K-2):带 client_type 只写该端;缺省把 app / web 两行都写成同一个值 ——
      // 与 K-1 之前「一个账号一个版本」的旧调用方保持兼容,不会让网页端令牌错位。
      const auto client_type = body.value("client_type", std::string());
      if (client_type.empty()) {
        messages_.users().set_session_version(uid, kClientApp, version);
        messages_.users().set_session_version(uid, kClientWeb, version);
      } else {
        messages_.users().set_session_version(uid, normalize_client_type(client_type), version);
      }
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     按路径分发请求 做来源限制 鉴权与限流
// 参数说明     req              已解析的请求
//              peer_addr        直连对端地址 来源判定只看它 不看任何请求头
// 返回参数     response_type     响应对象
// 使用示例     return route(req, peer_addr);
// 备注信息     /metrics 只允许回环 否则 403 + 40301 供 Prometheus 直连抓取
//              /internal/* 先判来源网段再验 HMAC 来源不合法 403 + 40301 签名错 401 + 40101
//              /im/api/* 只认五个路径 其余 404 + 40401 鉴权失败 401 + 40101
//              限流按账号 会话列表与历史 120 次/分钟 burst 40 搜索 60 次/分钟 burst 20
//              flags 60 次/分钟 burst 20 多选删除 60 次/分钟 burst 10 超限统一 429 + 42901
//-------------------------------------------------------------------------------------------------------------------
HttpApi::response_type HttpApi::route(const http::request<http::string_body>& req,
                                      const boost::asio::ip::address& peer_addr) {
  const auto target = parse_target(std::string(req.target()));
  const bool loopback = net_guard::is_loopback(peer_addr);
  if (target.path == "/metrics") {
    // 与旧版 /internal/* 同口径:只允许回环。nginx 不代理该路径,Prometheus 直连 9101 抓取。
    if (!loopback) {
      return error_response(req, http::status::forbidden, 40301, "forbidden");
    }
    response_type response(http::status::ok, req.version());
    response.set(http::field::content_type, "text/plain; version=0.0.4; charset=utf-8");
    response.body() = metrics::render(registry_.online_count());
    response.prepare_payload();
    return response;
  }
  if (target.path.rfind("/internal/", 0) == 0) {
    // H-1:来源网段由 IM_INTERNAL_ALLOW 显式配置(容器部署下 Django 不在回环上),
    // HMAC 校验照旧。只放开「谁可以敲门」,不放开「谁可以不签名」。
    if (!internal_allow_.trusted(peer_addr)) {
      return error_response(req, http::status::forbidden, 40301, "forbidden");
    }
    if (target.path != "/internal/healthz" && target.path != "/internal/readyz" &&
        !verify_internal(req)) {
      return error_response(req, http::status::unauthorized, 40101, "bad signature");
    }
    return internal_route(req, target);
  }
  if (target.path != "/im/api/conversations" && target.path != "/im/api/conversations/flags" &&
      target.path != "/im/api/messages" && target.path != "/im/api/messages/delete" &&
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
                             // 对端读到哪(0 = 从没读过)。已读回执的离线补拉入口:
                             // 客户端打开会话/重连后靠它把 seq <= peer_read_seq 的我方消息标已读。
                             {"peer_read_seq", view.peer_read_seq},
                             // 置顶 / 免打扰(批次 N):`pinned` 是布尔,`pinned_at` 不下发 ——
                             // 客户端只需要知道「排在哪一组」,组内顺序服务端已经排好。
                             {"pinned", view.pinned_at > 0},
                             {"muted", view.muted},
                             {"updated_at", view.updated_at}};
      if (view.has_last) {
        item["last_message"] = message_json_of(view.last, messages_.users(), messages_.signer());
      }
      items.push_back(std::move(item));
    }
    response_type response(http::status::ok, req.version());
    response.set(http::field::content_type, "application/json");
    response.body() = nlohmann::json{{"items", items}, {"has_more", false}}.dump();
    response.prepare_payload();
    return response;
  }

  // 会话置顶 / 免打扰(批次 N):**低频写操作走 HTTP,不加 WS 帧** ——
  // 加帧要三端 fixture 同改(成本 ×3),而这两个开关一天也点不了几次。
  // 只有 POST 一种方法;两个开关都可选,缺省表示「这一项不改」。
  if (target.path == "/im/api/conversations/flags") {
    if (req.method() != http::verb::post) {
      return error_response(req, http::status::method_not_allowed, 40501, "只支持 POST");
    }
    if (!flags_table_.allow(*uid, now_ms)) {
      return error_response(req, http::status::too_many_requests, 42901,
                            "操作过于频繁,请稍后再试");
    }
    nlohmann::json body;
    try {
      body = req.body().empty() ? nlohmann::json::object() : nlohmann::json::parse(req.body());
    } catch (const std::exception&) {
      return error_response(req, http::status::bad_request, 42201, "body 不合法");
    }
    if (!body.is_object()) {
      return error_response(req, http::status::bad_request, 42201, "body 不合法");
    }
    const auto peer_text = body.contains("peer") && body["peer"].is_string()
                               ? body["peer"].get<std::string>()
                               : std::string();
    const auto peer = parse_peer(peer_text);
    if (!peer.has_value()) {
      // 这里用 400 而不是 422:本接口的对外口径见 docs/ops/imserver.md §19
      // (与 /internal/send 一样,HTTP 状态给 400、业务码仍是 42201)。
      return error_response(req, http::status::bad_request, 42201, "peer 不合法");
    }
    std::optional<bool> pinned;
    std::optional<bool> muted;
    if (!read_flag(body, "pinned", pinned) || !read_flag(body, "muted", muted)) {
      return error_response(req, http::status::bad_request, 42201, "pinned/muted 必须是布尔");
    }
    const auto flags = messages_.set_conversation_flags(*uid, *peer, pinned, muted);
    if (!flags.has_value()) {
      // 会话不存在 = 未配对 / 从没聊过(口径同 /im/api/messages 的「没有会话就没有历史」)。
      return error_response(req, http::status::not_found, 40401, "会话不存在");
    }
    // 回的是**回读实库**后的真实值,不是回显请求参数:客户端据此刷新本地状态即可。
    return json_response(req, http::status::ok,
                         {{"pinned", flags->pinned}, {"muted", flags->muted}});
  }

  // 多选删除(批次 T):同样**低频写操作走 HTTP,不加 WS 帧**。单方语义 ——
  // 只写 im_message_hidden,不给对端发任何帧、不改消息本体、不动 last_seq。
  if (target.path == "/im/api/messages/delete") {
    if (req.method() != http::verb::post) {
      return error_response(req, http::status::method_not_allowed, 40501, "只支持 POST");
    }
    if (!delete_table_.allow(*uid, now_ms)) {
      return error_response(req, http::status::too_many_requests, 42901,
                            "操作过于频繁,请稍后再试");
    }
    nlohmann::json body;
    try {
      body = req.body().empty() ? nlohmann::json::object() : nlohmann::json::parse(req.body());
    } catch (const std::exception&) {
      return error_response(req, http::status::bad_request, 42201, "body 不合法");
    }
    if (!body.is_object()) {
      return error_response(req, http::status::bad_request, 42201, "body 不合法");
    }
    const auto ids_it = body.find("ids");
    if (ids_it == body.end() || !ids_it->is_array()) {
      return error_response(req, http::status::bad_request, 42201, "ids 必须是数组");
    }
    if (ids_it->empty() || ids_it->size() > kDeleteMaxIds) {
      return error_response(req, http::status::bad_request, 42201,
                            "ids 不能为空,且一次最多 50 条");
    }
    std::vector<uint64_t> ids;
    ids.reserve(ids_it->size());
    for (const auto& element : *ids_it) {
      uint64_t id = 0;
      if (!parse_msg_id(element, id)) {
        return error_response(req, http::status::bad_request, 42201, "ids 里有不合法的消息 id");
      }
      // 同一个 id 出现两次只算一次:否则「新隐藏」计数会被同一行放大,
      // 幂等断言(deleted=N 后第二次 0)就失去意义。
      if (std::find(ids.begin(), ids.end(), id) == ids.end()) {
        ids.push_back(id);
      }
    }
    // 别人的 id 在服务层**静默忽略**(不计入 deleted、不报错):报 403/404 会变成
    // 「探测别人消息是否存在」的信道。
    const auto deleted = messages_.hide_messages(*uid, ids);
    return json_response(req, http::status::ok, {{"deleted", deleted}});
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
      nlohmann::json item = message_json_of(row, messages_.users(), messages_.signer());
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
    items.push_back(message_json_of(row, messages_.users(), messages_.signer()));
  }
  response_type response(http::status::ok, req.version());
  response.set(http::field::content_type, "application/json");
  response.body() =
      nlohmann::json{{"items", items}, {"has_more", rows.size() == static_cast<std::size_t>(limit)}}
          .dump();
  response.prepare_payload();
  return response;
}
