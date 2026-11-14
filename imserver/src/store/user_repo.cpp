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
* 文件名称          src/store/user_repo.cpp
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
#include "store/user_repo.h"

#include <chrono>

#include "store/stmt.h"

namespace {

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     取系统时钟当前毫秒时间戳
// 参数说明     无
// 返回参数     int64_t          毫秒时间戳
// 使用示例     int64_t t = now_ms();
// 备注信息     用 system_clock 与库里 updated_at 同口径 不保证单调
//-------------------------------------------------------------------------------------------------------------------
int64_t now_ms() {
  return std::chrono::duration_cast<std::chrono::milliseconds>(
             std::chrono::system_clock::now().time_since_epoch())
      .count();
}

}  // namespace

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     构造仓储 绑定连接池与两个缓存上限
// 参数说明     pool             连接池引用
//              max_known        已知账号集合上限
//              max_profiles     画像缓存上限
// 返回参数     void             无返回值
// 使用示例     UserRepo repo(pool, 100000, 100000);
// 备注信息     只保存引用与上限 不建连接 不预热缓存
//-------------------------------------------------------------------------------------------------------------------
UserRepo::UserRepo(MysqlPool& pool, std::size_t max_known, std::size_t max_profiles)
    : pool_(pool), max_known_(max_known), max_profiles_(max_profiles) {}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     判断账号是否在已知集合
// 参数说明     uid              账号 id
// 返回参数     bool             在集合内返回 true
// 使用示例     repo.is_known(42);  // 私有方法 类内调用
// 备注信息     持 known_mu_ 读 与 remember forget 互斥
//-------------------------------------------------------------------------------------------------------------------
bool UserRepo::is_known(uint64_t uid) {
  const std::lock_guard<std::mutex> lock(known_mu_);
  return known_.count(uid) != 0;
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     把账号记入已知集合
// 参数说明     uid              账号 id
// 返回参数     void             无返回值
// 使用示例     remember(42);  // 仅在类内部调用
// 备注信息     达到 max_known_ 先整体清空再插入 防止集合无限增长
//-------------------------------------------------------------------------------------------------------------------
void UserRepo::remember(uint64_t uid) {
  const std::lock_guard<std::mutex> lock(known_mu_);
  // 上限兜底:正常只缓存真实用户,但绝不能让它随任意 uid 无限增长(H4)。
  if (known_.size() >= max_known_) {
    known_.clear();
  }
  known_.insert(uid);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     从已知集合移除账号
// 参数说明     uid              账号 id
// 返回参数     void             无返回值
// 使用示例     forget(42);  // 仅在类内部调用
// 备注信息     与 is_known remember 共用 known_mu_
//-------------------------------------------------------------------------------------------------------------------
void UserRepo::forget(uint64_t uid) {
  const std::lock_guard<std::mutex> lock(known_mu_);
  known_.erase(uid);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     确保账号行存在 不存在则插入
// 参数说明     lease            已借出的连接
//              uid              账号 id
//              nickname         昵称 仅新建时写入
// 返回参数     void             无返回值
// 使用示例     repo.ensure(lease, 42, "小明");
// 备注信息     known_ 命中直接返回 未命中先 SELECT 1 主键读 再按需走预编译 INSERT ON DUPLICATE KEY UPDATE
//-------------------------------------------------------------------------------------------------------------------
void UserRepo::ensure(MysqlPool::Lease& lease, uint64_t uid, const std::string& nickname) {
  if (is_known(uid)) {
    return;
  }
  // 先做一次主键读(MVCC,不拿写锁):绝大多数调用是已存在的用户,
  // 可以完全避开 INSERT ... ON DUPLICATE KEY UPDATE 在相邻主键上的间隙锁互等。
  bool exists = false;
  auto* result = lease.query("SELECT 1 FROM im_user WHERE user_id=" +
                             std::to_string(uid));
  if (result != nullptr) {
    exists = mysql_fetch_row(result) != nullptr;
    mysql_free_result(result);
  }
  if (!exists) {
    Stmt stmt(lease.get(),
              "INSERT INTO im_user (user_id,nickname,avatar_url,updated_at) VALUES (?,?,'',?) "
              "ON DUPLICATE KEY UPDATE user_id=user_id");
    stmt.bind_uint(0, uid);
    stmt.bind_string(1, nickname);
    stmt.bind_uint(2, static_cast<uint64_t>(now_ms()));
    stmt.execute();
  }
  remember(uid);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     确保账号行存在 自行借连接
// 参数说明     uid              账号 id
//              nickname         昵称 仅新建时写入
// 返回参数     void             无返回值
// 使用示例     repo.ensure(42, "小明");
// 备注信息     内部 acquire 后转调租约版本 连接用完随租约析构归还
//-------------------------------------------------------------------------------------------------------------------
void UserRepo::ensure(uint64_t uid, const std::string& nickname) {
  auto lease = pool_.acquire();
  ensure(lease, uid, nickname);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     按账号 id 取画像
// 参数说明     lease            已借出的连接
//              uid              账号 id
// 返回参数     std::optional<UserRow>     查不到为空
// 使用示例     auto row = repo.get(lease, 42);
// 备注信息     先查 profiles_ 缓存 未命中查库并回填 昵称与头像为 NULL 时给空串
//-------------------------------------------------------------------------------------------------------------------
std::optional<UserRow> UserRepo::get(MysqlPool::Lease& lease, uint64_t uid) {
  {
    const std::lock_guard<std::mutex> lock(profile_mu_);
    const auto it = profiles_.find(uid);
    if (it != profiles_.end()) {
      return it->second;
    }
  }
  auto* result = lease.query(
      "SELECT user_id,nickname,avatar_url FROM im_user WHERE user_id=" +
      std::to_string(uid));
  if (result == nullptr) {
    return std::nullopt;
  }
  std::optional<UserRow> row;
  if (MYSQL_ROW values = mysql_fetch_row(result)) {
    UserRow user;
    user.id = std::stoull(values[0]);
    user.nickname = values[1] == nullptr ? "" : values[1];
    user.avatar = values[2] == nullptr ? "" : values[2];
    row = user;
  }
  mysql_free_result(result);
  if (row.has_value()) {
    remember(row->id);
    const std::lock_guard<std::mutex> lock(profile_mu_);
    if (profiles_.size() >= max_profiles_) {
      profiles_.clear();
    }
    profiles_[row->id] = *row;
  }
  return row;
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     按账号 id 取画像 自行借连接
// 参数说明     uid              账号 id
// 返回参数     std::optional<UserRow>     查不到为空
// 使用示例     auto row = repo.get(42);
// 备注信息     先查缓存 未命中才 acquire 连接
//-------------------------------------------------------------------------------------------------------------------
std::optional<UserRow> UserRepo::get(uint64_t uid) {
  {
    const std::lock_guard<std::mutex> lock(profile_mu_);
    const auto it = profiles_.find(uid);
    if (it != profiles_.end()) {
      return it->second;
    }
  }
  auto lease = pool_.acquire();
  return get(lease, uid);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     取某账号某端的会话版本
// 参数说明     lease            已借出的连接
//              uid              账号 id
//              ct               端类型 app 或 web
// 返回参数     std::optional<int64_t>     该端没有会话行时为空
// 使用示例     auto sv = repo.session_version(lease, 42, "web");
// 备注信息     查 im_device_session 的 (user_id, client_type) ct 走 escape 拼字面量 列值为 NULL 视为 0
//-------------------------------------------------------------------------------------------------------------------
std::optional<int64_t> UserRepo::session_version(MysqlPool::Lease& lease, uint64_t uid,
                                                 std::string_view ct) {
  // 多端在线(K-2):版本从 im_user 单列下沉到 im_device_session 的 (user_id, client_type)。
  // ct 只可能是 app / web(由 token 的 ct claim 归一化而来),仍按仓库既有写法走 escape()。
  auto* result = lease.query("SELECT session_version FROM im_device_session WHERE user_id=" +
                             std::to_string(uid) + " AND client_type='" + lease.escape(
                                 std::string(ct)) + "'");
  if (result == nullptr) {
    return std::nullopt;
  }
  std::optional<int64_t> version;
  if (MYSQL_ROW values = mysql_fetch_row(result)) {
    version = values[0] == nullptr ? 0 : std::stoll(values[0]);
  }
  mysql_free_result(result);
  return version;
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     取某账号某端的会话版本 自行借连接
// 参数说明     uid              账号 id
//              ct               端类型 app 或 web
// 返回参数     std::optional<int64_t>     该端没有会话行时为空
// 使用示例     auto sv = repo.session_version(42, "app");
// 备注信息     内部 acquire 后转调租约版本
//-------------------------------------------------------------------------------------------------------------------
std::optional<int64_t> UserRepo::session_version(uint64_t uid, std::string_view ct) {
  auto lease = pool_.acquire();
  return session_version(lease, uid, ct);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     写某账号某端的会话版本
// 参数说明     lease            已借出的连接
//              uid              账号 id
//              ct               端类型 app 或 web
//              version          该端的新会话版本
// 返回参数     void             无返回值
// 使用示例     repo.set_session_version(lease, 42, "app", 7);
// 备注信息     预编译 upsert 端会话行不存在时补一行 失败抛 MysqlError
//-------------------------------------------------------------------------------------------------------------------
void UserRepo::set_session_version(MysqlPool::Lease& lease, uint64_t uid, std::string_view ct,
                                   int64_t version) {
  // upsert:同步任务可能早于端会话行存在(该端还没登录过就收到同步),补一行。
  Stmt stmt(lease.get(),
            "INSERT INTO im_device_session (user_id,client_type,session_version) "
            "VALUES (?,?,?) ON DUPLICATE KEY UPDATE session_version=VALUES(session_version)");
  stmt.bind_uint(0, uid);
  stmt.bind_string(1, std::string(ct));
  stmt.bind_uint(2, static_cast<uint64_t>(version));
  stmt.execute();
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     写某账号某端的会话版本 自行借连接
// 参数说明     uid              账号 id
//              ct               端类型 app 或 web
//              version          该端的新会话版本
// 返回参数     void             无返回值
// 使用示例     repo.set_session_version(42, "web", 3);
// 备注信息     内部 acquire 后转调租约版本
//-------------------------------------------------------------------------------------------------------------------
void UserRepo::set_session_version(uint64_t uid, std::string_view ct, int64_t version) {
  auto lease = pool_.acquire();
  set_session_version(lease, uid, ct, version);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     删除账号行与端会话行
// 参数说明     lease            已借出的连接
//              uid              账号 id
// 返回参数     void             无返回值
// 使用示例     repo.remove(lease, 42);
// 备注信息     两条 DELETE 都走预编译 端会话行必须显式删否则留下孤儿行 调用方需在同一事务里
//-------------------------------------------------------------------------------------------------------------------
void UserRepo::remove(MysqlPool::Lease& lease, uint64_t uid) {
  Stmt stmt(lease.get(), "DELETE FROM im_user WHERE user_id=?");
  stmt.bind_uint(0, uid);
  stmt.execute();
  // 端会话行随账号一起清:版本已经不在 im_user 上了(多端在线 K-2),
  // 不显式删就会留下孤儿行。注销路径在同一个事务里调用本方法。
  Stmt sessions(lease.get(), "DELETE FROM im_device_session WHERE user_id=?");
  sessions.bind_uint(0, uid);
  sessions.execute();
  forget(uid);
  const std::lock_guard<std::mutex> lock(profile_mu_);
  profiles_.erase(uid);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     清空进程内缓存
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     repo.clear_cache();
// 备注信息     先清 known_ 再清 profiles_ 两把锁分别持有 不跨锁
//-------------------------------------------------------------------------------------------------------------------
void UserRepo::clear_cache() {
  {
    const std::lock_guard<std::mutex> lock(known_mu_);
    known_.clear();
  }
  const std::lock_guard<std::mutex> lock(profile_mu_);
  profiles_.clear();
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     更新昵称与头像
// 参数说明     lease            已借出的连接
//              uid              账号 id
//              nickname         有值才更新昵称
//              avatar           有值才更新头像
//              now              写入 updated_at 的毫秒时间戳
// 返回参数     void             无返回值
// 使用示例     repo.update_profile(lease, 42, std::string("小明"), std::nullopt, now_ms);
// 备注信息     两个字段各发一条 UPDATE 不在同一事务 末尾清掉该账号的画像缓存
//-------------------------------------------------------------------------------------------------------------------
void UserRepo::update_profile(MysqlPool::Lease& lease, uint64_t uid,
                              const std::optional<std::string>& nickname,
                              const std::optional<std::string>& avatar, int64_t now) {
  if (nickname.has_value()) {
    Stmt stmt(lease.get(), "UPDATE im_user SET nickname=?, updated_at=? WHERE user_id=?");
    stmt.bind_string(0, *nickname);
    stmt.bind_uint(1, static_cast<uint64_t>(now));
    stmt.bind_uint(2, uid);
    stmt.execute();
  }
  if (avatar.has_value()) {
    Stmt stmt(lease.get(), "UPDATE im_user SET avatar_url=?, updated_at=? WHERE user_id=?");
    stmt.bind_string(0, *avatar);
    stmt.bind_uint(1, static_cast<uint64_t>(now));
    stmt.bind_uint(2, uid);
    stmt.execute();
  }
  const std::lock_guard<std::mutex> lock(profile_mu_);
  profiles_.erase(uid);
}
