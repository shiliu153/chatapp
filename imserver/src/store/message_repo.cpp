#include "store/message_repo.h"

#include <algorithm>
#include <stdexcept>
#include <unordered_set>

#include "store/stmt.h"
#include "util/like.h"

namespace {

std::pair<uint64_t, uint64_t> ordered(uint64_t a, uint64_t b) {
  return a < b ? std::make_pair(a, b) : std::make_pair(b, a);
}

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

MessageRepo::MessageRepo(MysqlPool& pool) : pool_(pool) {}

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

std::optional<MessageRow> MessageRepo::find_by_client(uint64_t from_id,
                                                      const std::string& client_msg_id) {
  auto lease = pool_.acquire();
  return find_by_client(lease, from_id, client_msg_id);
}

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

void MessageRepo::delete_hidden_by_user(MysqlPool::Lease& lease, uint64_t uid) {
  Stmt stmt(lease.get(), "DELETE FROM im_message_hidden WHERE user_id=?");
  stmt.bind_uint(0, uid);
  stmt.execute();
}

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

void MessageRepo::revoke(MysqlPool::Lease& lease, uint64_t msg_id, int64_t now_ms) {
  Stmt stmt(lease.get(), "UPDATE im_message SET revoked_at=? WHERE msg_id=?");
  stmt.bind_uint(0, static_cast<uint64_t>(now_ms));
  stmt.bind_uint(1, msg_id);
  stmt.execute();
}

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

uint64_t MessageRepo::count_pair(uint64_t a, uint64_t b) {
  auto lease = pool_.acquire();
  return count_pair(lease, a, b);
}

void MessageRepo::delete_for_user(MysqlPool::Lease& lease, uint64_t uid) {
  Stmt stmt(lease.get(), "DELETE FROM im_message WHERE from_id=? OR to_id=?");
  stmt.bind_uint(0, uid);
  stmt.bind_uint(1, uid);
  stmt.execute();
}

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

std::vector<MessageRow> MessageRepo::search(uint64_t uid, const std::string& keyword,
                                            uint64_t before_id, int limit) {
  auto lease = pool_.acquire();
  return search(lease, uid, keyword, before_id, limit);
}
