#include "store/conversation_repo.h"

#include <algorithm>
#include <stdexcept>

#include "store/stmt.h"

namespace {

std::pair<uint64_t, uint64_t> ordered(uint64_t a, uint64_t b) {
  return a < b ? std::make_pair(a, b) : std::make_pair(b, a);
}

}  // namespace

ConversationRepo::ConversationRepo(MysqlPool& pool) : pool_(pool) {}

std::optional<ConversationRow> ConversationRepo::find_pair(MysqlPool::Lease& lease,
                                                           uint64_t a, uint64_t b) {
  const auto [user_a, user_b] = ordered(a, b);
  auto* result = lease.query(
      "SELECT id,user_a,user_b,last_seq,IFNULL(last_msg_id,0),last_msg_at "
      "FROM im_conversation WHERE user_a=" + std::to_string(user_a) +
      " AND user_b=" + std::to_string(user_b));
  if (result == nullptr) {
    return std::nullopt;
  }
  std::optional<ConversationRow> row;
  if (MYSQL_ROW values = mysql_fetch_row(result)) {
    ConversationRow conversation;
    conversation.id = std::stoull(values[0]);
    conversation.user_a = std::stoull(values[1]);
    conversation.user_b = std::stoull(values[2]);
    conversation.last_seq = std::stoull(values[3]);
    conversation.last_msg_id = std::stoull(values[4]);
    conversation.last_msg_at = std::stoll(values[5]);
    row = conversation;
  }
  mysql_free_result(result);
  return row;
}

ConversationRow ConversationRepo::lock_pair(MysqlPool::Lease& lease, uint64_t a, uint64_t b,
                                            int64_t now_ms) {
  const auto [user_a, user_b] = ordered(a, b);
  const std::string select_sql =
      "SELECT id,user_a,user_b,last_seq,IFNULL(last_msg_id,0),last_msg_at "
      "FROM im_conversation WHERE user_a=" + std::to_string(user_a) +
      " AND user_b=" + std::to_string(user_b) + " FOR UPDATE";

  auto read = [&]() -> std::optional<ConversationRow> {
    auto* result = lease.query(select_sql);
    if (result == nullptr) {
      return std::nullopt;
    }
    std::optional<ConversationRow> row;
    if (MYSQL_ROW values = mysql_fetch_row(result)) {
      ConversationRow conversation;
      conversation.id = std::stoull(values[0]);
      conversation.user_a = std::stoull(values[1]);
      conversation.user_b = std::stoull(values[2]);
      conversation.last_seq = std::stoull(values[3]);
      conversation.last_msg_id = std::stoull(values[4]);
      conversation.last_msg_at = std::stoll(values[5]);
      row = conversation;
    }
    mysql_free_result(result);
    return row;
  };

  if (auto existing = read()) {
    return *existing;
  }

  try {
    Stmt insert(lease.get(),
                "INSERT INTO im_conversation "
                "(user_a,user_b,last_seq,last_msg_id,last_msg_at,created_at) "
                "VALUES (?,?,0,NULL,0,?)");
    insert.bind_uint(0, user_a);
    insert.bind_uint(1, user_b);
    insert.bind_uint(2, static_cast<uint64_t>(now_ms));
    insert.execute();
  } catch (const MysqlError& error) {
    if (error.code() != 1062) {
      throw;
    }
  }

  if (auto created = read()) {
    return *created;
  }
  throw std::runtime_error("failed to lock conversation");
}

void ConversationRepo::touch(MysqlPool::Lease& lease, uint64_t conv_id, uint64_t seq,
                             uint64_t msg_id, int64_t now_ms) {
  Stmt stmt(lease.get(),
            "UPDATE im_conversation SET last_seq=?,last_msg_id=?,last_msg_at=? WHERE id=?");
  stmt.bind_uint(0, seq);
  stmt.bind_uint(1, msg_id);
  stmt.bind_uint(2, static_cast<uint64_t>(now_ms));
  stmt.bind_uint(3, conv_id);
  stmt.execute();
}

void ConversationRepo::upsert_state(MysqlPool::Lease& lease, uint64_t owner,
                                    uint64_t conv_id, int unread_delta, int64_t now_ms) {
  Stmt stmt(lease.get(),
            "INSERT INTO im_conversation_state "
            "(owner_id,conv_id,unread,read_seq,deleted,updated_at) VALUES (?,?,?,0,0,?) "
            "ON DUPLICATE KEY UPDATE unread=unread+VALUES(unread),deleted=0,"
            "updated_at=VALUES(updated_at)");
  stmt.bind_uint(0, owner);
  stmt.bind_uint(1, conv_id);
  stmt.bind_int(2, unread_delta);
  stmt.bind_uint(3, static_cast<uint64_t>(now_ms));
  stmt.execute();
}

uint32_t ConversationRepo::unread_for_peer(MysqlPool::Lease& lease, uint64_t owner,
                                           uint64_t peer) {
  const auto [user_a, user_b] = ordered(owner, peer);
  auto* result = lease.query(
      "SELECT s.unread FROM im_conversation_state s "
      "JOIN im_conversation c ON c.id=s.conv_id "
      "WHERE s.owner_id=" + std::to_string(owner) +
      " AND c.user_a=" + std::to_string(user_a) +
      " AND c.user_b=" + std::to_string(user_b));
  uint32_t unread = 0;
  if (result != nullptr) {
    if (MYSQL_ROW values = mysql_fetch_row(result)) {
      unread = static_cast<uint32_t>(std::stoul(values[0]));
    }
    mysql_free_result(result);
  }
  return unread;
}

uint32_t ConversationRepo::unread_for_peer(uint64_t owner, uint64_t peer) {
  auto lease = pool_.acquire();
  return unread_for_peer(lease, owner, peer);
}

void ConversationRepo::mark_read(MysqlPool::Lease& lease, uint64_t owner, uint64_t peer,
                                 uint64_t seq, int64_t now_ms) {
  const auto [user_a, user_b] = ordered(owner, peer);
  Stmt stmt(lease.get(),
            "UPDATE im_conversation_state s JOIN im_conversation c ON c.id=s.conv_id "
            "SET s.unread=0,s.read_seq=GREATEST(s.read_seq,?),s.updated_at=? "
            "WHERE s.owner_id=? AND c.user_a=? AND c.user_b=?");
  stmt.bind_uint(0, seq);
  stmt.bind_uint(1, static_cast<uint64_t>(now_ms));
  stmt.bind_uint(2, owner);
  stmt.bind_uint(3, user_a);
  stmt.bind_uint(4, user_b);
  stmt.execute();
}

void ConversationRepo::set_deleted(MysqlPool::Lease& lease, uint64_t owner, uint64_t peer,
                                   int64_t now_ms) {
  const auto [user_a, user_b] = ordered(owner, peer);
  Stmt stmt(lease.get(),
            "UPDATE im_conversation_state s JOIN im_conversation c ON c.id=s.conv_id "
            "SET s.deleted=1,s.updated_at=? "
            "WHERE s.owner_id=? AND c.user_a=? AND c.user_b=?");
  stmt.bind_uint(0, static_cast<uint64_t>(now_ms));
  stmt.bind_uint(1, owner);
  stmt.bind_uint(2, user_a);
  stmt.bind_uint(3, user_b);
  stmt.execute();
}

std::vector<ConversationView> ConversationRepo::list(MysqlPool::Lease& lease, uint64_t owner,
                                                     int limit) {
  limit = std::clamp(limit, 1, 200);
  const std::string sql =
      "SELECT u.user_id,u.nickname,u.avatar_url,"
      "IFNULL(m.msg_id,0),IFNULL(m.conv_id,0),IFNULL(m.seq,0),IFNULL(m.from_id,0),"
      "IFNULL(m.to_id,0),IFNULL(m.kind,1),IFNULL(m.body,''),"
      "IFNULL(m.client_msg_id,''),IFNULL(m.created_at,0),m.revoked_at,"
      "s.unread,c.last_seq,s.updated_at "
      "FROM im_conversation_state s "
      "JOIN im_conversation c ON c.id=s.conv_id "
      "JOIN im_user u ON u.user_id=IF(c.user_a=" + std::to_string(owner) +
      ",c.user_b,c.user_a) "
      "LEFT JOIN im_message m ON m.msg_id=c.last_msg_id "
      "WHERE s.owner_id=" + std::to_string(owner) +
      " AND s.deleted=0 ORDER BY c.last_msg_at DESC LIMIT " + std::to_string(limit);

  std::vector<ConversationView> rows;
  auto* result = lease.query(sql);
  if (result == nullptr) {
    return rows;
  }
  while (MYSQL_ROW values = mysql_fetch_row(result)) {
    ConversationView view;
    view.peer.id = std::stoull(values[0]);
    view.peer.nickname = values[1] == nullptr ? "" : values[1];
    view.peer.avatar = values[2] == nullptr ? "" : values[2];

    const uint64_t msg_id = std::stoull(values[3]);
    view.has_last = msg_id != 0;
    if (view.has_last) {
      view.last.msg_id = msg_id;
      view.last.conv_id = std::stoull(values[4]);
      view.last.seq = std::stoull(values[5]);
      view.last.from_id = std::stoull(values[6]);
      view.last.to_id = std::stoull(values[7]);
      view.last.kind = std::stoi(values[8]);
      view.last.body = values[9] == nullptr ? "" : values[9];
      view.last.client_msg_id = values[10] == nullptr ? "" : values[10];
      view.last.created_at = std::stoll(values[11]);
      if (values[12] != nullptr) {
        view.last.revoked_at = std::stoll(values[12]);
      }
    }
    view.unread = static_cast<uint32_t>(std::stoul(values[13]));
    view.last_seq = std::stoull(values[14]);
    view.updated_at = std::stoll(values[15]);
    rows.push_back(std::move(view));
  }
  mysql_free_result(result);
  return rows;
}
