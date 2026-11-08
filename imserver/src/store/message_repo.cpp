#include "store/message_repo.h"

#include <algorithm>
#include <stdexcept>

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

std::vector<MessageRow> MessageRepo::list(MysqlPool::Lease& lease, uint64_t conv_id,
                                          uint64_t before_seq, int limit) {
  limit = std::clamp(limit, 1, 100);
  std::string sql = std::string(kSelect) + "WHERE conv_id=" + std::to_string(conv_id);
  if (before_seq > 0) {
    sql += " AND seq<" + std::to_string(before_seq);
  }
  sql += " ORDER BY seq DESC LIMIT " + std::to_string(limit);

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
      "SELECT m.msg_id,m.conv_id,m.seq,m.from_id,m.to_id,m.kind,m.body,"
      "m.client_msg_id,m.created_at,m.revoked_at,m.ref_msg_id,m.ref_snapshot "
      "FROM im_conversation c JOIN im_message m ON m.conv_id=c.id "
      "LEFT JOIN im_conversation_state s ON s.conv_id=c.id AND s.owner_id=" + owner + " "
      "WHERE (c.user_a=" + owner + " OR c.user_b=" + owner + ") "
      "AND m.kind=1 AND m.revoked_at IS NULL "
      "AND (s.deleted IS NULL OR s.deleted=0) "
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
