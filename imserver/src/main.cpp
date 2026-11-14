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
* 文件名称          src/main.cpp
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
#include "service/push_notifier.h"
#include "service/session_registry.h"
#include "store/blacklist_repo.h"
#include "store/conversation_repo.h"
#include "store/message_repo.h"
#include "store/mysql_pool.h"
#include "store/redis_client.h"
#include "store/user_repo.h"
#include "util/log.h"

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     程序入口 启动 WS 与 HTTP 服务
// 参数说明     argc             命令行参数个数
//              argv             命令行参数 仅识别 argv[1] 为 --migrate
// 返回参数     int              0 正常退出 1 启动失败
// 使用示例     ./imserver --migrate
// 备注信息     非回环监听必须显式设 IM_ALLOW_PUBLIC_BIND=1 否则启动失败;SIGINT/SIGTERM 触发优雅停服;异常只打 fatal 并返回 1
//-------------------------------------------------------------------------------------------------------------------
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
    // H-1:内部接口的来源网段在启动时就解析一遍,非法条目直接启动失败,
    // 避免线上才发现 /internal/* 全 403(或更糟:为了救火把校验删掉)。
    const auto internal_allow = net_guard::ProxyTrust::from_list(cfg.internal_allow);
    log_info("internal_allow_ready", {{"rules", std::to_string(internal_allow.size())}});

    MysqlPool mysql(parse_mysql_dsn(cfg.mysql_dsn), cfg.db_pool,
                    cfg.db_idle_ping_ms, cfg.db_connect_wait_ms);
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
    // C-1:离线新消息推送的转发器。IM_PUSH_URL 为空 = 关闭(空壳,不建线程)。
    PushNotifier push_notifier(cfg);
    WsServer server(io, cfg, registry, redis, message_service, push_notifier, db_pool);
    server.start();
    HttpApi http(io, cfg, message_service, registry, redis, push_notifier);
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
