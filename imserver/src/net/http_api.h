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
* 文件名称          src/net/http_api.h
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
#pragma once
#include <boost/asio/io_context.hpp>
#include <boost/asio/ip/address.hpp>
#include <boost/asio/ip/tcp.hpp>
#include <boost/beast/http.hpp>

#include <optional>
#include <string>
#include <map>

#include <nlohmann/json.hpp>

#include "config.h"
#include "net/guard.h"
#include "service/message_service.h"
#include "service/push_notifier.h"
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     构造 HTTP API 并初始化内部接口来源网段表
// 参数说明     io               事件循环 整个服务共用一个
//              cfg              服务配置 含 listen_http / jwt_secret / internal_secret / internal_allow
//              messages         消息服务 历史 搜索 发送 等业务都在它里面
//              registry         会话注册表 在线数与下行推送
//              redis            缓存客户端 封禁标记与在线状态
//              push             离线新消息推送器
// 返回参数     void             构造函数 无返回值
// 使用示例     HttpApi api(io, cfg, messages, registry, redis, push);
// 备注信息     internal_allow_ 由 IM_INTERNAL_ALLOW 解析 任一条目非法即抛异常 启动失败而不是放宽
//-------------------------------------------------------------------------------------------------------------------
  HttpApi(boost::asio::io_context& io, const Config& cfg, MessageService& messages,
          SessionRegistry& registry, RedisClient& redis, PushNotifier& push);
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     绑定监听端口并开始接受连接
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     api.start();
// 备注信息     监听地址来自 IM_LISTEN_HTTP 默认 127.0.0.1:9101 非回环地址的校验在 main 启动时做
//-------------------------------------------------------------------------------------------------------------------
  void start();
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     关闭监听器 停止接受新连接
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     api.stop();
// 备注信息     只关 acceptor 已建立的连接不受影响 关闭错误被忽略
//-------------------------------------------------------------------------------------------------------------------
  void stop();

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     处理一条已读完的 HTTP 请求
// 参数说明     req              已解析的请求 体为 string_body
//              peer_addr        直连对端地址 用于来源判定
// 返回参数     response_type     响应对象
// 使用示例     auto response = api.handle(request, peer_addr);
// 备注信息     内部再调 route 任何异常统一兜成 500 + 50001 不向 io 线程抛
//-------------------------------------------------------------------------------------------------------------------
  response_type handle(
      const boost::beast::http::request<boost::beast::http::string_body>& req,
      const boost::asio::ip::address& peer_addr);

 private:
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     异步接受下一个连接并递归续接
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     api.start();  // 内部已调用 do_accept
// 备注信息     每条连接跑在独立 strand 上 监听器已关闭时直接返回
//-------------------------------------------------------------------------------------------------------------------
  void do_accept();
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     按路径分发请求 做来源限制 鉴权与限流
// 参数说明     req              已解析的请求
//              peer_addr        直连对端地址
// 返回参数     response_type     响应对象
// 使用示例     route(req, peer_addr);
// 备注信息     /metrics 与 /internal/* 先判来源地址 再按需验 HMAC
//              /im/api/* 只认五个路径 先验 Bearer 令牌 再按接口挑限流表
//-------------------------------------------------------------------------------------------------------------------
  response_type route(
      const boost::beast::http::request<boost::beast::http::string_body>& req,
      const boost::asio::ip::address& peer_addr);
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     处理 /internal/* 内部管理接口
// 参数说明     req              已通过来源与签名校验的请求
//              target           已解析的路径与查询参数
// 返回参数     response_type     响应对象
// 使用示例     internal_route(req, target);
// 备注信息     请求体非法或字段缺失回 422 + 42201 未匹配路径回 404 + 40401
//              发送失败回 400 加消息服务返回的业务码
//-------------------------------------------------------------------------------------------------------------------
  response_type internal_route(
      const boost::beast::http::request<boost::beast::http::string_body>& req,
      const Target& target);
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     校验内部接口的 HMAC 签名与时间窗
// 参数说明     req              需带 X-IM-Timestamp 与 X-IM-Signature 两个头
// 返回参数     bool             校验通过返回 true
// 使用示例     if (!api.verify_internal(req)) { /* 回 401 + 40101 */ }
// 备注信息     签名原文是 timestamp method target body 四段按换行拼接 密钥为 IM_INTERNAL_SECRET
//              时间戳偏差超过 60 秒即拒 比较用 CRYPTO_memcmp 走常量时间
//-------------------------------------------------------------------------------------------------------------------
  bool verify_internal(
      const boost::beast::http::request<boost::beast::http::string_body>& req);
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     构造 JSON 成功响应
// 参数说明     req              只用于取 HTTP 版本
//              status           HTTP 状态码
//              body             响应体 JSON
// 返回参数     response_type     响应对象
// 使用示例     json_response(req, boost::beast::http::status::ok, {{"ok", true}});
// 备注信息     固定 Content-Type 为 application/json 并自动补 Content-Length
//-------------------------------------------------------------------------------------------------------------------
  response_type json_response(
      const boost::beast::http::request<boost::beast::http::string_body>& req,
      boost::beast::http::status status, const nlohmann::json& body);
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     构造业务错误响应
// 参数说明     req              只用于取 HTTP 版本
//              status           HTTP 状态码
//              code             业务码 如 40101 / 40302 / 42201
//              message          中文提示
// 返回参数     response_type     响应对象
// 使用示例     error_response(req, boost::beast::http::status::unauthorized, 40101, "登录已过期");
// 备注信息     响应体只有 code 与 message 两个键 imserver 不带 request_id
//              业务码前三位通常与 HTTP 状态一致 400 承载 42201 是刻意例外
//-------------------------------------------------------------------------------------------------------------------
  response_type error_response(
      const boost::beast::http::request<boost::beast::http::string_body>& req,
      boost::beast::http::status status, int code, const std::string& message);
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     校验 Bearer 令牌并返回账号 id
// 参数说明     req              从 Authorization 头取令牌
// 返回参数     std::optional<uint64_t>     通过返回 uid 否则 nullopt
// 使用示例     const auto uid = api.authenticate(req);
// 备注信息     依次校验 Bearer 前缀 JWT 签名与过期 im:block: 封禁标记 会话版本
//              会话版本按令牌里的 ct claim 分端比对 与 WS 握手同一份判定 旧 token 的 sv=0 放行
//-------------------------------------------------------------------------------------------------------------------
  std::optional<uint64_t> authenticate(
      const boost::beast::http::request<boost::beast::http::string_body>& req);

  boost::asio::io_context& io_;
  boost::asio::ip::tcp::acceptor acceptor_;
  Config cfg_;
  MessageService& messages_;
  SessionRegistry& registry_;
  RedisClient& redis_;
  /// 离线新消息推送(C-1):/internal/send 这条路径也要推(im_send、Django 通知都走它)。
  PushNotifier& push_;
  // 搜索:每账号 60 次/分钟、burst 20。
  RateTable search_table_{1.0, 20.0};
  // 普通读接口(会话列表 / 历史消息):每账号 120 次/分钟、burst 40。
  // 之前这两个接口完全没有按账号限流,单账号即可持续打库(M-2)。
  RateTable read_table_{2.0, 40.0};
  // 会话标志位写接口(POST /im/api/conversations/flags,批次 N):每账号
  // 60 次/分钟、burst 20。单列一张表而不是复用 read_table_:它是写路径,
  // 不该和「刷列表」抢同一桶令牌。
  RateTable flags_table_{1.0, 20.0};
  // 多选删除写接口(POST /im/api/messages/delete,批次 T):每账号 60 次/分钟、
  // burst 10。同样是写路径,单列一张表(理由同 flags_table_)。
  RateTable delete_table_{1.0, 10.0};
  // 内部管理接口(/internal/*)的来源网段;容器部署下 Django 不在回环上(H-1)。
  net_guard::ProxyTrust internal_allow_;
};
