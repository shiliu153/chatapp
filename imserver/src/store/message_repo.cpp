#include "store/message_repo.h"

#include <algorithm>
#include <stdexcept>

#include "store/stmt.h"

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
  return row;
}

constexpr const char* kSelect =
    "SELECT msg_id,conv_id,seq,from_id,to_id,kind,body,client_msg_id,created_at,revoked_at "
    "FROM im_message ";

}  // namespace

MessageRepo::MessageRepo(MysqlPool& pool) : pool_(pool) {}

uint64_t MessageRepo::insert(MysqlPool::Lease& lease, uint64_t conv_id, uint64_t seq,
                             uint64_t from_id, uint64_t to_id, int kind,
                             const std::string& body, const std::string& client_msg_id,
                             int64_t now_ms) {
  Stmt stmt(lease.get(),
            "INSERT INTO im_message "
            "(conv_id,seq,from_id,to_id,kind,body,client_msg_id,created_at) "
            "VALUES (?,?,?,?,?,?,?,?)");
  stmt.bind_uint(0, conv_id);
  stmt.bind_uint(1, seq);
  stmt.bind_uint(2, from_id);
  stmt.bind_uint(3, to_id);
  stmt.bind_int(4, kind);
  stmt.bind_string(5, body);
  stmt.bind_string(6, client_msg_id);
  stmt.bind_uint(7, static_cast<uint64_t>(now_ms));
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

uint64_t MessageRepo::count_pair(MysqlPool::Lease& lease, uint64_t a, uint64_t b) {
  const auto [user_a, user_b] = ordered(a, b);
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
