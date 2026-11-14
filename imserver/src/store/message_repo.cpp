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
* 文件名称          src/store/message_repo.cpp
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
#include "store/message_repo.h"

#include <algorithm>
#include <stdexcept>
#include <unordered_set>

#include "store/stmt.h"
#include "util/like.h"

namespace {

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     把两个 user_id 规范化成升序对
// 参数说明     a                任意一方 user_id
//              b                另一方 user_id
// 返回参数     std::pair<uint64_t, uint64_t>  first 是较小者 second 是较大者
// 使用示例     ordered(a, b);
// 备注信息     im_conversation 的 uk_pair 要求 user_a 小于 user_b 按对查会话的 SQL 都先过这一步
//-------------------------------------------------------------------------------------------------------------------
std::pair<uint64_t, uint64_t> ordered(uint64_t a, uint64_t b) {
  return a < b ? std::make_pair(a, b) : std::make_pair(b, a);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     把一行消息结果集解析成 MessageRow
// 参数说明     values           mysql_fetch_row 返回的字段数组
// 返回参数     MessageRow       解析后的消息行
// 使用示例     parse_row(values);
// 备注信息     列顺序必须是 kSelect 或 kColumnsM 定义的 12 列 可空列在 values 里是 nullptr 据此决定 std::optional 是否有值
//-------------------------------------------------------------------------------------------------------------------
MessageRow parse_row(MYSQL_ROW values) {
  MessageRow row;
  row.msg_id = std::stoull(values[0]);
  row.conv_id = std::stoull(values[1]);
  row.seq = std::stoull(values[2]);
  row.from_id = std::stoull(values[3]);
  row.to_id = std::stoull(values[4]);
  row.kind = std::stoi(values[5]);
  row.body = values[6] == nullptr ? "" : values[6];
  row.client_msg_id = values[7] == nullptr ? "" : values[7];
  row.created_at = std::stoll(values[8]);
  if (values[9] != nullptr) {
    row.revoked_at = std::stoll(values[9]);
  }
  // 引用(批次 L-2):两列都可空。**所有**读路径都必须带上它们,否则会出现
  // 「实时帧有引用、翻历史就没有」这类一端看不到引用的问题。
  if (values[10] != nullptr) {
    row.ref_msg_id = std::stoull(values[10]);
  }
  if (values[11] != nullptr) {
    row.ref_snapshot = values[11];
  }
  return row;
}

constexpr const char* kSelect =
    "SELECT msg_id,conv_id,seq,from_id,to_id,kind,body,client_msg_id,created_at,revoked_at,"
    "ref_msg_id,ref_snapshot "
    "FROM im_message ";

/// 带别名 `m.` 的同一组列:凡是 join 了 `im_message_hidden` 的读路径都必须用这一份,
/// 否则 `msg_id` 两张表都有,直接报 `Column 'msg_id' in field list is ambiguous`。
constexpr const char* kColumnsM =
    "m.msg_id,m.conv_id,m.seq,m.from_id,m.to_id,m.kind,m.body,m.client_msg_id,m.created_at,"
    "m.revoked_at,m.ref_msg_id,m.ref_snapshot";

}  // namespace

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     构造消息仓库 绑定连接池
// 参数说明     pool             MySQL 连接池 只保存引用 生命周期须长于本对象
// 返回参数     void             无返回值
// 使用示例     MessageRepo repo(pool);
// 备注信息     构造函数不借连接也不访问数据库
//-------------------------------------------------------------------------------------------------------------------
MessageRepo::MessageRepo(MysqlPool& pool) : pool_(pool) {}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     落一条消息 返回新行的 msg_id
// 参数说明     lease            借出的数据库连接 事务边界由调用方决定
//              conv_id          会话 id
//              seq              会话内序号 调用方已加锁分配
//              from_id          发送者 user_id 0 是系统通知
//              to_id            接收者 user_id
//              kind             消息类型 1=text 2=custom 3=image 4=voice
//              body             已校验并序列化的载荷 JSON 文本
//              client_msg_id    客户端幂等 id
//              now_ms           服务端时间 毫秒
//              ref_msg_id       引用的原消息 id 无引用时 nullopt
//              ref_snapshot     服务端生成的引用快照 JSON 无引用时 nullopt
// 返回参数     uint64_t         新插入行的自增 id
// 使用示例     repo.insert(lease, conversation.id, seq, from, to, 1, body_json, client_msg_id, now);
// 备注信息     无引用时两列 bind_null 而不是写 0 或空串 (from_id,client_msg_id) 唯一键冲突抛 MysqlError(1062)
//-------------------------------------------------------------------------------------------------------------------
uint64_t MessageRepo::insert(MysqlPool::Lease& lease, uint64_t conv_id, uint64_t seq,
                             uint64_t from_id, uint64_t to_id, int kind,
                             const std::string& body, const std::string& client_msg_id,
                             int64_t now_ms, const std::optional<uint64_t>& ref_msg_id,
                             const std::optional<std::string>& ref_snapshot) {
  Stmt stmt(lease.get(),
            "INSERT INTO im_message "
            "(conv_id,seq,from_id,to_id,kind,body,client_msg_id,created_at,ref_msg_id,"
            "ref_snapshot) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)");
  stmt.bind_uint(0, conv_id);
  stmt.bind_uint(1, seq);
  stmt.bind_uint(2, from_id);
  stmt.bind_uint(3, to_id);
  stmt.bind_int(4, kind);
  stmt.bind_string(5, body);
  stmt.bind_string(6, client_msg_id);
  stmt.bind_uint(7, static_cast<uint64_t>(now_ms));
  // 无引用时写 NULL(而不是 0 / 空串):读侧据此决定「`ref` 键是否出现」。
  if (ref_msg_id.has_value()) {
    stmt.bind_uint(8, *ref_msg_id);
  } else {
    stmt.bind_null(8);
  }
  if (ref_snapshot.has_value()) {
    stmt.bind_string(9, *ref_snapshot);
  } else {
    stmt.bind_null(9);
  }
  stmt.execute();
  return stmt.insert_id();
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     按发送者与客户端幂等 id 查已落库的消息
// 参数说明     lease            借出的数据库连接 事务边界由调用方决定
//              from_id          发送者 user_id
//              client_msg_id    客户端幂等 id
// 返回参数     std::optional<MessageRow>  命中时返回消息行 否则 nullopt
// 使用示例     repo.find_by_client(lease, from, client_msg_id);
// 备注信息     client_msg_id 先经 lease.escape 转义再拼进 SQL 唯一键 (from_id,client_msg_id) 最多命中一行 LIMIT 1 兜底
//-------------------------------------------------------------------------------------------------------------------
std::optional<MessageRow> MessageRepo::find_by_client(MysqlPool::Lease& lease,
                                                      uint64_t from_id,
                                                      const std::string& client_msg_id) {
  const auto escaped = lease.escape(client_msg_id);
  auto* result = lease.query(std::string(kSelect) + "WHERE from_id=" +
                             std::to_string(from_id) + " AND client_msg_id='" + escaped +
                             "' LIMIT 1");
  std::optional<MessageRow> row;
  if (result != nullptr) {
    if (MYSQL_ROW values = mysql_fetch_row(result)) {
      row = parse_row(values);
    }
    mysql_free_result(result);
  }
  return row;
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     按发送者与客户端幂等 id 查已落库的消息 自行借连接
// 参数说明     from_id          发送者 user_id
//              client_msg_id    客户端幂等 id
// 返回参数     std::optional<MessageRow>  命中时返回消息行 否则 nullopt
// 使用示例     repo.find_by_client(from, client_msg_id);
// 备注信息     内部 acquire 一条连接 用后归还
//-------------------------------------------------------------------------------------------------------------------
std::optional<MessageRow> MessageRepo::find_by_client(uint64_t from_id,
                                                      const std::string& client_msg_id) {
  auto lease = pool_.acquire();
  return find_by_client(lease, from_id, client_msg_id);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     按 msg_id 取一条消息
// 参数说明     lease            借出的数据库连接 事务边界由调用方决定
//              msg_id           消息 id
// 返回参数     std::optional<MessageRow>  命中时返回消息行 否则 nullopt
// 使用示例     repo.get(lease, msg_id);
// 备注信息     按主键等值查 撤回后 revoked_at 有值但行仍在
//-------------------------------------------------------------------------------------------------------------------
std::optional<MessageRow> MessageRepo::get(MysqlPool::Lease& lease, uint64_t msg_id) {
  auto* result = lease.query(std::string(kSelect) + "WHERE msg_id=" + std::to_string(msg_id));
  std::optional<MessageRow> row;
  if (result != nullptr) {
    if (MYSQL_ROW values = mysql_fetch_row(result)) {
      row = parse_row(values);
    }
    mysql_free_result(result);
  }
  return row;
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     分页取会话历史 排除我隐藏的消息
// 参数说明     lease            借出的数据库连接 事务边界由调用方决定
//              owner            请求者 user_id 决定排除哪一份隐藏关系
//              conv_id          会话 id
//              before_seq       游标 只取 seq 小于它的消息 0 表示最新一页
//              limit            最多返回条数 内部夹在 1..100
// 返回参数     std::vector<MessageRow>  旧到新排列的消息行
// 使用示例     repo.list(lease, uid, conv_id, 0, 30);
// 备注信息     LEFT JOIN im_message_hidden 反连接排除隐藏行 该写法仍走 uk_conv_seq 结果在内存里反转成旧到新
//-------------------------------------------------------------------------------------------------------------------
std::vector<MessageRow> MessageRepo::list(MysqlPool::Lease& lease, uint64_t owner,
                                          uint64_t conv_id, uint64_t before_seq, int limit) {
  limit = std::clamp(limit, 1, 100);
  // `LEFT JOIN + h.msg_id IS NULL` = 「排除我隐藏的」(批次 T 的多选删除)。
  // 主查询仍按 `uk_conv_seq(conv_id,seq)` 走 range/反向扫,隐藏表是主键点查 ——
  // 不能改写成 `NOT IN (子查询)` 或先聚合再过滤,那会把分页退化成全表扫。
  std::string sql = std::string("SELECT ") + kColumnsM + " FROM im_message m " +
                    "LEFT JOIN im_message_hidden h ON h.msg_id=m.msg_id AND h.user_id=" +
                    std::to_string(owner) + " WHERE m.conv_id=" + std::to_string(conv_id);
  if (before_seq > 0) {
    sql += " AND m.seq<" + std::to_string(before_seq);
  }
  sql += " AND h.msg_id IS NULL ORDER BY m.seq DESC LIMIT " + std::to_string(limit);

  std::vector<MessageRow> rows;
  auto* result = lease.query(sql);
  if (result != nullptr) {
    while (MYSQL_ROW values = mysql_fetch_row(result)) {
      rows.push_back(parse_row(values));
    }
    mysql_free_result(result);
  }
  std::reverse(rows.begin(), rows.end());
  return rows;
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     取我在某个会话里的最后一条可见消息
// 参数说明     lease            借出的数据库连接 事务边界由调用方决定
//              owner            请求者 user_id 决定排除哪一份隐藏关系
//              conv_id          会话 id
// 返回参数     std::optional<MessageRow>  最后一条可见消息 没有可见消息时 nullopt
// 使用示例     repo.last_visible(lease, uid, conv_id);
// 备注信息     按 seq 倒序加 LIMIT 1 读到第一条没被隐藏的就停 不碰整段历史
//-------------------------------------------------------------------------------------------------------------------
std::optional<MessageRow> MessageRepo::last_visible(MysqlPool::Lease& lease, uint64_t owner,
                                                   uint64_t conv_id) {
  // 反向扫 `uk_conv_seq` + `LEFT JOIN` 反连接 + `LIMIT 1`:读到第一条没被隐藏的就停,
  // 不碰整段历史。
  const std::string sql = std::string("SELECT ") + kColumnsM + " FROM im_message m " +
                          "LEFT JOIN im_message_hidden h ON h.msg_id=m.msg_id AND h.user_id=" +
                          std::to_string(owner) + " WHERE m.conv_id=" + std::to_string(conv_id) +
                          " AND h.msg_id IS NULL ORDER BY m.seq DESC LIMIT 1";
  std::optional<MessageRow> row;
  auto* result = lease.query(sql);
  if (result != nullptr) {
    if (MYSQL_ROW values = mysql_fetch_row(result)) {
      row = parse_row(values);
    }
    mysql_free_result(result);
  }
  return row;
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     把会话列表的摘要修成我的最后一条可见消息
// 参数说明     lease            借出的数据库连接 事务边界由调用方决定
//              owner            列表主人 user_id
//              views            待原地修补的会话列表
// 返回参数     void             无返回值
// 使用示例     repo.apply_visible_last(lease, uid, views);
// 备注信息     先一次 IN 查询问清哪些摘要被我隐藏 没有命中就整体返回 整段会话都被隐藏时把 has_last 置 false 不动 unread 与 last_seq
//-------------------------------------------------------------------------------------------------------------------
void MessageRepo::apply_visible_last(MysqlPool::Lease& lease, uint64_t owner,
                                     std::vector<ConversationView>& views) {
  std::string last_ids;
  for (const auto& view : views) {
    if (!view.has_last) {
      continue;
    }
    if (!last_ids.empty()) {
      last_ids += ",";
    }
    last_ids += std::to_string(view.last.msg_id);
  }
  if (last_ids.empty()) {
    return;
  }
  // 一次问清「这些摘要里有哪几条被我隐藏了」;没有命中就直接返回,一条回查都不做。
  std::unordered_set<uint64_t> hidden;
  {
    auto* result = lease.query("SELECT msg_id FROM im_message_hidden WHERE user_id=" +
                               std::to_string(owner) + " AND msg_id IN (" + last_ids + ")");
    if (result != nullptr) {
      while (MYSQL_ROW values = mysql_fetch_row(result)) {
        hidden.insert(std::stoull(values[0]));
      }
      mysql_free_result(result);
    }
  }
  if (hidden.empty()) {
    return;
  }
  for (auto& view : views) {
    if (!view.has_last || hidden.count(view.last.msg_id) == 0) {
      continue;
    }
    const uint64_t conv_id = view.last.conv_id;
    if (auto visible = last_visible(lease, owner, conv_id)) {
      view.last = *visible;
    } else {
      // 整段会话都被我隐藏了:没有可显示的摘要,但会话本身还在(unread / last_seq 不变)。
      view.has_last = false;
    }
  }
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     从一批 msg_id 里挑出我参与且真实存在的消息
// 参数说明     lease            借出的数据库连接 事务边界由调用方决定
//              owner            请求者 user_id
//              ids              候选 msg_id 调用方已去重且不超过 50 个
// 返回参数     std::vector<MessageRow>  命中的消息行 顺序不保证
// 使用示例     repo.find_mine(lease, uid, ids);
// 备注信息     不属于我的 id 既不报错也不返回 ids 为空直接返回空表 id 由 uint64 拼成 IN 列表
//-------------------------------------------------------------------------------------------------------------------
std::vector<MessageRow> MessageRepo::find_mine(MysqlPool::Lease& lease, uint64_t owner,
                                              const std::vector<uint64_t>& ids) {
  std::vector<MessageRow> rows;
  if (ids.empty()) {
    return rows;
  }
  // id 已经解析成 uint64(见 http_api.cpp),这里拼进 SQL 不存在注入面;
  // 用 prepared statement 反而要给「最多 50 个占位符」准备 50 份变体,
  // 既撞 Stmt 的按 SQL 文本缓存,也读不出结果集(Stmt 只支持无结果集的 execute)。
  std::string in_list;
  in_list.reserve(ids.size() * 8);
  for (std::size_t i = 0; i < ids.size(); ++i) {
    if (i > 0) {
      in_list += ",";
    }
    in_list += std::to_string(ids[i]);
  }
  const std::string owner_text = std::to_string(owner);
  const std::string sql = std::string(kSelect) + "WHERE msg_id IN (" + in_list +
                          ") AND (from_id=" + owner_text + " OR to_id=" + owner_text + ")";
  auto* result = lease.query(sql);
  if (result != nullptr) {
    while (MYSQL_ROW values = mysql_fetch_row(result)) {
      rows.push_back(parse_row(values));
    }
    mysql_free_result(result);
  }
  return rows;
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     记录我不再看到某条消息 返回本次是否新隐藏
// 参数说明     lease            借出的数据库连接 事务边界由调用方决定
//              owner            执行隐藏的 user_id
//              msg_id           消息 id
//              now_ms           当前毫秒时间戳 写入时间列
// 返回参数     bool             true 表示本次新隐藏 false 表示这一行本来就存在
// 使用示例     repo.hide(lease, uid, row.msg_id, now);
// 备注信息     INSERT IGNORE 靠主键 (user_id,msg_id) 幂等 affected_rows 为 1 才算新隐藏
//-------------------------------------------------------------------------------------------------------------------
bool MessageRepo::hide(MysqlPool::Lease& lease, uint64_t owner, uint64_t msg_id, int64_t now_ms) {
  // INSERT IGNORE 而不是先 SELECT 再 INSERT:主键 (user_id,msg_id) 就是幂等键,
  // affected_rows=1 表示「本次新隐藏」,0 表示这一对早就存在(重复删同一批)。
  Stmt stmt(lease.get(),
            "INSERT IGNORE INTO im_message_hidden (user_id,msg_id,created_at) VALUES (?,?,?)");
  stmt.bind_uint(0, owner);
  stmt.bind_uint(1, msg_id);
  stmt.bind_uint(2, static_cast<uint64_t>(now_ms));
  stmt.execute();
  return stmt.affected_rows() == 1;
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     注销清理 删掉我隐藏别人消息的那些行
// 参数说明     lease            借出的数据库连接 事务边界由调用方决定
//              uid              要注销的账号 user_id
// 返回参数     void             无返回值
// 使用示例     repo.delete_hidden_by_user(lease, uid);
// 备注信息     按 user_id 一次删除 必须与 delete_hidden_by_messages 一起在删 im_message 之前跑
//-------------------------------------------------------------------------------------------------------------------
void MessageRepo::delete_hidden_by_user(MysqlPool::Lease& lease, uint64_t uid) {
  Stmt stmt(lease.get(), "DELETE FROM im_message_hidden WHERE user_id=?");
  stmt.bind_uint(0, uid);
  stmt.execute();
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     注销清理 删掉别人隐藏了我消息的那些行
// 参数说明     lease            借出的数据库连接 事务边界由调用方决定
//              uid              要注销的账号 user_id
// 返回参数     void             无返回值
// 使用示例     repo.delete_hidden_by_messages(lease, uid);
// 备注信息     子查询按 im_message 的 from_id 或 to_id 反查 msg_id 所以必须在删消息之前执行 否则隐藏行变永久垃圾
//-------------------------------------------------------------------------------------------------------------------
void MessageRepo::delete_hidden_by_messages(MysqlPool::Lease& lease, uint64_t uid) {
  // 子查询按 `im_message` 的 msg_id 反查:**必须在删 im_message 之前**跑,消息行没了
  // 就再也找不回这些 msg_id,隐藏行会变成永久垃圾(而且 msg_id 会被自增复用)。
  // 目标表是 im_message_hidden、来源表是 im_message,MySQL 允许(不是同表自更新)。
  Stmt stmt(lease.get(),
            "DELETE FROM im_message_hidden WHERE msg_id IN "
            "(SELECT msg_id FROM im_message WHERE from_id=? OR to_id=?)");
  stmt.bind_uint(0, uid);
  stmt.bind_uint(1, uid);
  stmt.execute();
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     把一条消息标记为已撤回
// 参数说明     lease            借出的数据库连接 事务边界由调用方决定
//              msg_id           要撤回的消息 id
//              now_ms           当前毫秒时间戳 写入时间列
// 返回参数     void             无返回值
// 使用示例     repo.revoke(lease, msg_id, now);
// 备注信息     一条 UPDATE 只写 revoked_at 不删行 也不校验发送者与时间窗口
//-------------------------------------------------------------------------------------------------------------------
void MessageRepo::revoke(MysqlPool::Lease& lease, uint64_t msg_id, int64_t now_ms) {
  Stmt stmt(lease.get(), "UPDATE im_message SET revoked_at=? WHERE msg_id=?");
  stmt.bind_uint(0, static_cast<uint64_t>(now_ms));
  stmt.bind_uint(1, msg_id);
  stmt.execute();
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     统计两个人在同一会话里的消息总数
// 参数说明     lease            借出的数据库连接 事务边界由调用方决定
//              a                会话一方 user_id
//              b                会话另一方 user_id
// 返回参数     uint64_t         该会话的消息条数 没有会话时 0
// 使用示例     repo.count_pair(lease, 1, 2);
// 备注信息     规范化成升序对后经 uk_pair 关联 im_conversation 计数 包含已撤回与我隐藏的消息
//-------------------------------------------------------------------------------------------------------------------
uint64_t MessageRepo::count_pair(MysqlPool::Lease& lease, uint64_t a, uint64_t b) {  const auto [user_a, user_b] = ordered(a, b);
  auto* result = lease.query(
      "SELECT COUNT(*) FROM im_message m JOIN im_conversation c ON c.id=m.conv_id "
      "WHERE c.user_a=" + std::to_string(user_a) +
      " AND c.user_b=" + std::to_string(user_b));
  uint64_t count = 0;
  if (result != nullptr) {
    if (MYSQL_ROW values = mysql_fetch_row(result)) {
      count = std::stoull(values[0]);
    }
    mysql_free_result(result);
  }
  return count;
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     统计两个人在同一会话里的消息总数 自行借连接
// 参数说明     a                会话一方 user_id
//              b                会话另一方 user_id
// 返回参数     uint64_t         该会话的消息条数 没有会话时 0
// 使用示例     repo.count_pair(1, 2);
// 备注信息     内部 acquire 一条连接 用后归还
//-------------------------------------------------------------------------------------------------------------------
uint64_t MessageRepo::count_pair(uint64_t a, uint64_t b) {
  auto lease = pool_.acquire();
  return count_pair(lease, a, b);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     注销时删掉该账号收发过的全部消息
// 参数说明     lease            借出的数据库连接 事务边界由调用方决定
//              uid              要注销的账号 user_id
// 返回参数     void             无返回值
// 使用示例     repo.delete_for_user(lease, uid);
// 备注信息     按 from_id 或 to_id 删 必须在两个 delete_hidden_* 之后执行
//-------------------------------------------------------------------------------------------------------------------
void MessageRepo::delete_for_user(MysqlPool::Lease& lease, uint64_t uid) {
  Stmt stmt(lease.get(), "DELETE FROM im_message WHERE from_id=? OR to_id=?");
  stmt.bind_uint(0, uid);
  stmt.bind_uint(1, uid);
  stmt.execute();
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     关键词搜索我参与的未撤回文本消息
// 参数说明     lease            借出的数据库连接 事务边界由调用方决定
//              uid              请求者 user_id 只能搜到自己参与的会话
//              keyword          用户关键词 先 like_pattern 转义再 lease.escape 处理引号
//              before_id        游标 只取 msg_id 小于它的消息 0 表示第一页
//              limit            最多返回条数 内部夹在 1..100
// 返回参数     std::vector<MessageRow>  命中的消息行 新到旧
// 使用示例     repo.search(lease, uid, keyword, 0, 20);
// 备注信息     只搜 kind=1 且未撤回 排除已删除会话与我隐藏的消息 也排除我拉黑的对端 对端为 0 的系统通知同样排除
//-------------------------------------------------------------------------------------------------------------------
std::vector<MessageRow> MessageRepo::search(MysqlPool::Lease& lease, uint64_t uid,
                                            const std::string& keyword, uint64_t before_id,
                                            int limit) {
  limit = std::clamp(limit, 1, 100);
  const std::string owner = std::to_string(uid);
  // like_pattern 先转义 %/_/!,再由 escape() 处理引号与反斜杠,两处各管一层。
  const std::string pattern = lease.escape(like_pattern(keyword));
  std::string sql =
      "SELECT " + std::string(kColumnsM) +
      " FROM im_conversation c JOIN im_message m ON m.conv_id=c.id "
      "LEFT JOIN im_conversation_state s ON s.conv_id=c.id AND s.owner_id=" + owner + " "
      // 多选删除(批次 T):删掉的消息也不能再被我搜到,否则「删了还能搜到」与历史口径冲突。
      "LEFT JOIN im_message_hidden h ON h.msg_id=m.msg_id AND h.user_id=" + owner + " "
      "WHERE (c.user_a=" + owner + " OR c.user_b=" + owner + ") "
      "AND m.kind=1 AND m.revoked_at IS NULL "
      "AND (s.deleted IS NULL OR s.deleted=0) "
      "AND h.msg_id IS NULL "
      "AND IF(c.user_a=" + owner + ",c.user_b,c.user_a)<>0 "
      "AND NOT EXISTS (SELECT 1 FROM im_blacklist b WHERE b.owner_id=" + owner +
      " AND b.peer_id=IF(c.user_a=" + owner + ",c.user_b,c.user_a)) ";
  if (before_id > 0) {
    sql += "AND m.msg_id<" + std::to_string(before_id) + " ";
  }
  sql += "AND m.body LIKE '" + pattern + "' ESCAPE '!' "
         "ORDER BY m.msg_id DESC LIMIT " + std::to_string(limit);

  std::vector<MessageRow> rows;
  auto* result = lease.query(sql);
  if (result != nullptr) {
    while (MYSQL_ROW values = mysql_fetch_row(result)) {
      rows.push_back(parse_row(values));
    }
    mysql_free_result(result);
  }
  return rows;
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     关键词搜索我参与的未撤回文本消息 自行借连接
// 参数说明     uid              请求者 user_id
//              keyword          用户关键词 内部按 LIKE 转义
//              before_id        游标 只取 msg_id 小于它的消息 0 表示第一页
//              limit            最多返回条数 内部夹在 1..100
// 返回参数     std::vector<MessageRow>  命中的消息行 新到旧
// 使用示例     repo.search(uid, keyword, 0, 20);
// 备注信息     内部 acquire 一条连接 用后归还
//-------------------------------------------------------------------------------------------------------------------
std::vector<MessageRow> MessageRepo::search(uint64_t uid, const std::string& keyword,
                                            uint64_t before_id, int limit) {
  auto lease = pool_.acquire();
  return search(lease, uid, keyword, before_id, limit);
}
