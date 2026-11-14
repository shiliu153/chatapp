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
* 文件名称          src/service/session_registry.cpp
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
#include "service/session_registry.h"

#include <chrono>
#include <utility>
#include <vector>

#include "net/ws_server.h"
#include "store/redis_client.h"

namespace {

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     取当前毫秒时间戳
// 参数说明     无
// 返回参数     int64_t          自 Unix 纪元起的毫秒数
// 使用示例     int64_t ts = now_ms();
// 备注信息     系统时钟 只作为在线键的值写入 不参与 TTL 计算
//-------------------------------------------------------------------------------------------------------------------
int64_t now_ms() {
  return std::chrono::duration_cast<std::chrono::milliseconds>(
             std::chrono::system_clock::now().time_since_epoch())
      .count();
}

/// 在线键 TTL:与「120 秒内有认证请求 = 在线」同口径(见 CLAUDE.md「在线状态是公开信息」)。
constexpr int kOnlineTtlSeconds = 90;

}  // namespace

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     构造在线会话表 持有 Redis 客户端引用
// 参数说明     redis           用于写在线键的 Redis 客户端
// 返回参数     void             无返回值
// 使用示例     SessionRegistry registry(redis);
// 备注信息     只保存引用 构造不访问 Redis 也不起线程
//-------------------------------------------------------------------------------------------------------------------
SessionRegistry::SessionRegistry(RedisClient& redis) : redis_(redis) {}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     注册一条已鉴权连接 同端旧连接互顶
// 参数说明     uid             账号 id
//              ct              端类型 app 或 web
//              session         新连接
// 返回参数     void             无返回值
// 使用示例     registry.register_session(uid, "app", session);
// 备注信息     锁内换表 锁外踢旧连接 避免持锁调 kick 只踢同端 之后刷新在线键
//-------------------------------------------------------------------------------------------------------------------
void SessionRegistry::register_session(uint64_t uid, std::string_view ct,
                                       std::shared_ptr<WsSession> session) {
  std::shared_ptr<WsSession> old;
  {
    const std::lock_guard<std::mutex> lock(mutex_);
    auto& per_client = sessions_[uid];
    const auto it = per_client.find(std::string(ct));
    if (it != per_client.end()) {
      old = it->second.lock();
    }
    per_client[std::string(ct)] = session;
  }
  // 同类互顶:只踢同端。另一个端(一个 App + 一个网页)不受影响。
  if (old != nullptr && old.get() != session.get()) {
    old->kick("multi_device");
  }
  touch_online(uid);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     注销一条连接 只清仍指向它的那条登记
// 参数说明     uid             账号 id
//              ct              端类型
//              session         正在关闭的连接
// 返回参数     bool             true 表示该连接确实在表里并被移除
// 使用示例     registry.unregister(uid, "app", session.get());
// 备注信息     全程持锁 指针比对防止旧连接误删同端新登记 该 uid 无任何端时删除外层条目
//-------------------------------------------------------------------------------------------------------------------
bool SessionRegistry::unregister(uint64_t uid, std::string_view ct, WsSession* session) {
  const std::lock_guard<std::mutex> lock(mutex_);
  const auto it = sessions_.find(uid);
  if (it == sessions_.end()) {
    return false;
  }
  const auto client_it = it->second.find(std::string(ct));
  if (client_it == it->second.end() || client_it->second.lock().get() != session) {
    return false;
  }
  it->second.erase(client_it);
  if (it->second.empty()) {
    sessions_.erase(it);
  }
  return true;
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     踢掉该账号所有端的在线会话
// 参数说明     uid             账号 id
//              reason          踢下线原因 原样放进 kicked 帧
// 返回参数     void             无返回值
// 使用示例     registry.kick(uid, "banned");
// 备注信息     封禁与注销账号用 锁内只收集目标 锁外逐个 kick 不持锁做 IO
//-------------------------------------------------------------------------------------------------------------------
void SessionRegistry::kick(uint64_t uid, const std::string& reason) {
  // 踢全部端:封禁 / 注销账号用,语义与多端改造前一致。
  std::vector<std::shared_ptr<WsSession>> targets;
  {
    const std::lock_guard<std::mutex> lock(mutex_);
    const auto it = sessions_.find(uid);
    if (it != sessions_.end()) {
      for (const auto& entry : it->second) {
        if (auto session = entry.second.lock()) {
          targets.push_back(std::move(session));
        }
      }
    }
  }
  for (const auto& session : targets) {
    session->kick(reason);
  }
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     只踢该账号某一端的在线会话
// 参数说明     uid             账号 id
//              ct              端类型 app 或 web
//              reason          踢下线原因
// 返回参数     void             无返回值
// 使用示例     registry.kick_client(uid, "web", "multi_device");
// 备注信息     同类互顶与按端下线用 只取指定端 锁内收集 锁外 kick 另一端保持在线
//-------------------------------------------------------------------------------------------------------------------
void SessionRegistry::kick_client(uint64_t uid, std::string_view ct,
                                  const std::string& reason) {
  // 踢单端:同类互顶 / 按端下线(登录时只踢本端的旧会话)。
  std::shared_ptr<WsSession> target;
  {
    const std::lock_guard<std::mutex> lock(mutex_);
    const auto it = sessions_.find(uid);
    if (it != sessions_.end()) {
      const auto client_it = it->second.find(std::string(ct));
      if (client_it != it->second.end()) {
        target = client_it->second.lock();
      }
    }
  }
  if (target != nullptr) {
    target->kick(reason);
  }
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     向该账号所有端扇出一帧
// 参数说明     uid             账号 id
//              frame           已序列化的帧
// 返回参数     bool             true 表示至少投给一条活跃连接
// 使用示例     bool online = registry.send_to(uid, frame);
// 备注信息     锁内只收集目标 锁外 send_raw 避免持锁往 io_context 投递任务
//-------------------------------------------------------------------------------------------------------------------
bool SessionRegistry::send_to(uint64_t uid, const std::string& frame) {
  // 扇出:本人所有端都收到。锁内只收集目标,发送放到锁外 ——
  // send_raw 会往 io_context 投递任务,不该持着注册表的锁去做。
  std::vector<std::shared_ptr<WsSession>> targets;
  {
    const std::lock_guard<std::mutex> lock(mutex_);
    const auto it = sessions_.find(uid);
    if (it == sessions_.end()) {
      return false;
    }
    for (const auto& entry : it->second) {
      if (auto session = entry.second.lock()) {
        targets.push_back(std::move(session));
      }
    }
  }
  for (const auto& session : targets) {
    session->send_raw(frame);
  }
  return !targets.empty();
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     发给本人除 except 之外的所有端
// 参数说明     uid             账号 id
//              except          不发的那条连接 通常是当前正在处理的会话
//              frame           已序列化的帧
// 返回参数     void             无返回值
// 使用示例     registry.send_to_other_clients(uid, session, frame);
// 备注信息     跨端同步 self_read 与 conversation_deleted 用 锁内只收集目标 锁外发送
//-------------------------------------------------------------------------------------------------------------------
void SessionRegistry::send_to_other_clients(uint64_t uid, const WsSession* except,
                                            const std::string& frame) {
  // 与 send_to 同样:锁内只收集目标,发送放到锁外(不该持着注册表的锁投递 io 任务)。
  std::vector<std::shared_ptr<WsSession>> targets;
  {
    const std::lock_guard<std::mutex> lock(mutex_);
    const auto it = sessions_.find(uid);
    if (it == sessions_.end()) {
      return;
    }
    for (const auto& entry : it->second) {
      auto session = entry.second.lock();
      if (session != nullptr && session.get() != except) {
        targets.push_back(std::move(session));
      }
    }
  }
  for (const auto& session : targets) {
    session->send_raw(frame);
  }
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     判断账号是否在线
// 参数说明     uid             账号 id
// 返回参数     bool             true 表示至少一端连接还活着
// 使用示例     bool online = registry.is_online(uid);
// 备注信息     按 uid 计 任一端未过期即在线 持锁遍历该 uid 的端表
//-------------------------------------------------------------------------------------------------------------------
bool SessionRegistry::is_online(uint64_t uid) {
  const std::lock_guard<std::mutex> lock(mutex_);
  const auto it = sessions_.find(uid);
  if (it == sessions_.end()) {
    return false;
  }
  // 按 uid 计:任一端还活着就算在线(离线推送的判定依赖这一口径)。
  for (const auto& entry : it->second) {
    if (!entry.second.expired()) {
      return true;
    }
  }
  return false;
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     统计在线账号数
// 参数说明     无
// 返回参数     std::size_t      在线 uid 个数
// 使用示例     std::size_t n = registry.online_count();
// 备注信息     按 uid 计 两端同时在线仍只算 1 个 持锁遍历全部 uid
//-------------------------------------------------------------------------------------------------------------------
std::size_t SessionRegistry::online_count() {
  const std::lock_guard<std::mutex> lock(mutex_);
  std::size_t count = 0;
  for (const auto& per_uid : sessions_) {
    for (const auto& entry : per_uid.second) {
      if (!entry.second.expired()) {
        ++count;
        break;  // 一个 uid 只算一次:两端同时在线仍是 1 个在线用户
      }
    }
  }
  return count;
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     刷新账号在线键的 Redis TTL
// 参数说明     uid             账号 id
// 返回参数     void             无返回值
// 使用示例     registry.touch_online(uid);
// 备注信息     写 im:online:<uid> 键 TTL 90 秒 同步访问 Redis 不持注册表的锁
//-------------------------------------------------------------------------------------------------------------------
void SessionRegistry::touch_online(uint64_t uid) {
  redis_.setex("im:online:" + std::to_string(uid), kOnlineTtlSeconds,
               std::to_string(now_ms()));
}
