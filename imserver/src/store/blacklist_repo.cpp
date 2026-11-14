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
* 文件名称          src/store/blacklist_repo.cpp
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
#include "store/blacklist_repo.h"

#include <chrono>

#include "store/stmt.h"

namespace {

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     取当前系统时间的毫秒时间戳
// 参数说明     无
// 返回参数     int64_t          自 Unix 纪元起的毫秒数
// 使用示例     now_ms();
// 备注信息     匿名 namespace 内的私有辅助 取墙钟时间 不做单调性保证
//-------------------------------------------------------------------------------------------------------------------
int64_t now_ms() {
  return std::chrono::duration_cast<std::chrono::milliseconds>(
             std::chrono::system_clock::now().time_since_epoch())
      .count();
}

}  // namespace

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     构造拉黑仓库 绑定连接池
// 参数说明     pool             MySQL 连接池 只保存引用 生命周期须长于本对象
// 返回参数     void             无返回值
// 使用示例     BlacklistRepo repo(pool);
// 备注信息     构造函数不借连接也不访问数据库
//-------------------------------------------------------------------------------------------------------------------
BlacklistRepo::BlacklistRepo(MysqlPool& pool) : pool_(pool) {}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     写一条拉黑关系 已存在则忽略
// 参数说明     lease            借出的数据库连接 事务边界由调用方决定
//              owner            拉黑发起方 user_id
//              peer             被拉黑方 user_id
//              now_ms           写入 created_at 的毫秒时间戳 与文件内 now_ms() 同名 本函数体内不调用它
// 返回参数     void             无返回值
// 使用示例     repo.add(lease, 1, 2, now_ms());
// 备注信息     INSERT IGNORE 靠主键 (owner_id,peer_id) 去重 重复拉黑影响 0 行且不报错
//-------------------------------------------------------------------------------------------------------------------
void BlacklistRepo::add(MysqlPool::Lease& lease, uint64_t owner, uint64_t peer,
                        int64_t now_ms) {
  Stmt stmt(lease.get(),
            "INSERT IGNORE INTO im_blacklist (owner_id,peer_id,created_at) VALUES (?,?,?)");
  stmt.bind_uint(0, owner);
  stmt.bind_uint(1, peer);
  stmt.bind_uint(2, static_cast<uint64_t>(now_ms));
  stmt.execute();
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     写一条拉黑关系 自行借连接并取当前时间
// 参数说明     owner            拉黑发起方 user_id
//              peer             被拉黑方 user_id
// 返回参数     void             无返回值
// 使用示例     repo.add(1, 2);
// 备注信息     内部 acquire 一条连接并调用三参数重载 不开事务 单条 INSERT 自动提交
//-------------------------------------------------------------------------------------------------------------------
void BlacklistRepo::add(uint64_t owner, uint64_t peer) {
  auto lease = pool_.acquire();
  add(lease, owner, peer, now_ms());
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     删除一条拉黑关系
// 参数说明     lease            借出的数据库连接 事务边界由调用方决定
//              owner            拉黑发起方 user_id
//              peer             被拉黑方 user_id
// 返回参数     void             无返回值
// 使用示例     repo.remove(lease, 1, 2);
// 备注信息     按主键等值 DELETE 关系不存在时影响 0 行且不报错
//-------------------------------------------------------------------------------------------------------------------
void BlacklistRepo::remove(MysqlPool::Lease& lease, uint64_t owner, uint64_t peer) {
  Stmt stmt(lease.get(), "DELETE FROM im_blacklist WHERE owner_id=? AND peer_id=?");
  stmt.bind_uint(0, owner);
  stmt.bind_uint(1, peer);
  stmt.execute();
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     判断两人之间是否存在任一方向的拉黑关系
// 参数说明     lease            借出的数据库连接 事务边界由调用方决定
//              a                参与判定的第一个 user_id
//              b                参与判定的第二个 user_id
// 返回参数     bool             true 表示任一方向存在拉黑关系
// 使用示例     repo.exists_either(lease, from, to);
// 备注信息     SQL 由 uint64 直接拼成字面量 不存在注入面 命中一行即停 没有结果集时按未拉黑返回 false 查询报错抛 MysqlError
//-------------------------------------------------------------------------------------------------------------------
bool BlacklistRepo::exists_either(MysqlPool::Lease& lease, uint64_t a, uint64_t b) {
  auto* result = lease.query(
      "SELECT 1 FROM im_blacklist WHERE (owner_id=" + std::to_string(a) +
      " AND peer_id=" + std::to_string(b) + ") OR (owner_id=" + std::to_string(b) +
      " AND peer_id=" + std::to_string(a) + ") LIMIT 1");
  bool exists = false;
  if (result != nullptr) {
    exists = mysql_fetch_row(result) != nullptr;
    mysql_free_result(result);
  }
  return exists;
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     判断两人之间是否存在任一方向的拉黑关系 自行借连接
// 参数说明     a                参与判定的第一个 user_id
//              b                参与判定的第二个 user_id
// 返回参数     bool             true 表示任一方向存在拉黑关系
// 使用示例     repo.exists_either(1, 2);
// 备注信息     内部 acquire 一条连接 用后归还
//-------------------------------------------------------------------------------------------------------------------
bool BlacklistRepo::exists_either(uint64_t a, uint64_t b) {
  auto lease = pool_.acquire();
  return exists_either(lease, a, b);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     注销时清掉该账号两个方向的全部拉黑关系
// 参数说明     lease            借出的数据库连接 事务边界由调用方决定
//              uid              要注销的账号 user_id
// 返回参数     void             无返回值
// 使用示例     repo.delete_for_user(lease, uid);
// 备注信息     一条 DELETE 同时按 owner_id 与 peer_id 命中 由 MessageService::delete_account 在同一事务内调用
//-------------------------------------------------------------------------------------------------------------------
void BlacklistRepo::delete_for_user(MysqlPool::Lease& lease, uint64_t uid) {
  Stmt stmt(lease.get(), "DELETE FROM im_blacklist WHERE owner_id=? OR peer_id=?");
  stmt.bind_uint(0, uid);
  stmt.bind_uint(1, uid);
  stmt.execute();
}
