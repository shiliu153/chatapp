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

  // 冷启动时大量「全新配对」并发发第一条消息:若先 SELECT ... FOR UPDATE 一个不存在的行,
  // REPEATABLE READ 会给这段唯一键间隙加锁,几百个事务抢同一段间隙 → 1213 死锁
  // (2026-11-01 压测实测 500 对全新配对 819/1000 失败)。
  // 改成把 INSERT 放在事务最前面:此时事务还没持有任何行锁/间隙锁,
  // 用 ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id) 让并发插入退化成唯一键上的等锁,
  // 一次往返同时覆盖「新建」与「已存在」两种情况,随后按主键加锁读(last_seq 才是准的)。
  uint64_t conv_id = 0;
  {
    Stmt insert(lease.get(),
                "INSERT INTO im_conversation "
                "(user_a,user_b,last_seq,last_msg_id,last_msg_at,created_at) "
                "VALUES (?,?,0,NULL,0,?) "
                "ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id)");
    insert.bind_uint(0, user_a);
    insert.bind_uint(1, user_b);
    insert.bind_uint(2, static_cast<uint64_t>(now_ms));
    insert.execute();
    conv_id = insert.insert_id();
  }
  if (conv_id == 0) {
    throw std::runtime_error("failed to upsert conversation");
  }

  // 主键等值查询 + FOR UPDATE:只锁这一行,不会加间隙锁。
  auto* result = lease.query(
      "SELECT id,user_a,user_b,last_seq,IFNULL(last_msg_id,0),last_msg_at "
      "FROM im_conversation WHERE id=" + std::to_string(conv_id) + " FOR UPDATE");
  if (result != nullptr) {
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
    if (row) {
      return *row;
    }
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

void ConversationRepo::upsert_states(MysqlPool::Lease& lease, uint64_t owner_a, int delta_a,
                                     uint64_t owner_b, int delta_b, uint64_t conv_id,
                                     int64_t now_ms) {
  if (owner_b == 0) {
    upsert_state(lease, owner_a, conv_id, delta_a, now_ms);
    return;
  }
  // 收发双方的 state 用一条多行 INSERT 写掉,少一次往返(热路径)。
  Stmt stmt(lease.get(),
            "INSERT INTO im_conversation_state "
            "(owner_id,conv_id,unread,read_seq,deleted,updated_at) "
            "VALUES (?,?,?,0,0,?),(?,?,?,0,0,?) "
            "ON DUPLICATE KEY UPDATE unread=unread+VALUES(unread),deleted=0,"
            "updated_at=VALUES(updated_at)");
  stmt.bind_uint(0, owner_a);
  stmt.bind_uint(1, conv_id);
  stmt.bind_int(2, delta_a);
  stmt.bind_uint(3, static_cast<uint64_t>(now_ms));
  stmt.bind_uint(4, owner_b);
  stmt.bind_uint(5, conv_id);
  stmt.bind_int(6, delta_b);
  stmt.bind_uint(7, static_cast<uint64_t>(now_ms));
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

uint64_t ConversationRepo::read_seq_for(MysqlPool::Lease& lease, uint64_t owner,
                                        uint64_t peer) {
  const auto [user_a, user_b] = ordered(owner, peer);
  auto* result = lease.query(
      "SELECT s.read_seq FROM im_conversation_state s "
      "JOIN im_conversation c ON c.id=s.conv_id "
      "WHERE s.owner_id=" + std::to_string(owner) +
      " AND c.user_a=" + std::to_string(user_a) +
      " AND c.user_b=" + std::to_string(user_b));
  uint64_t read_seq = 0;
  if (result != nullptr) {
    if (MYSQL_ROW values = mysql_fetch_row(result)) {
      read_seq = std::stoull(values[0]);
    }
    mysql_free_result(result);
  }
  return read_seq;
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

void ConversationRepo::delete_for_user(MysqlPool::Lease& lease, uint64_t uid) {
  {
    Stmt states(lease.get(), "DELETE FROM im_conversation_state WHERE owner_id=?");
    states.bind_uint(0, uid);
    states.execute();
  }
  {
    Stmt conversations(lease.get(),
                       "DELETE FROM im_conversation WHERE user_a=? OR user_b=?");
    conversations.bind_uint(0, uid);
    conversations.bind_uint(1, uid);
    conversations.execute();
  }
}

std::vector<ConversationView> ConversationRepo::list(MysqlPool::Lease& lease, uint64_t owner,
                                                     int limit) {
  limit = std::clamp(limit, 1, 200);
  // `ps` 是**对端**的会话状态行:同一 conv_id、owner 换成对端。
  // 已读回执靠它把「对端读到哪」带给客户端(`peer_read_seq`),客户端再据此把
  // `seq <= peer_read_seq` 的我方消息标已读。`ps` 走 (owner_id,conv_id) 唯一键,
  // 是等值查找,不会因为多这个 JOIN 而扫全表。
  const std::string sql =
      "SELECT u.user_id,u.nickname,u.avatar_url,"
      "IFNULL(m.msg_id,0),IFNULL(m.conv_id,0),IFNULL(m.seq,0),IFNULL(m.from_id,0),"
      "IFNULL(m.to_id,0),IFNULL(m.kind,1),IFNULL(m.body,''),"
      "IFNULL(m.client_msg_id,''),IFNULL(m.created_at,0),m.revoked_at,"
      // 引用(批次 L-2):会话列表的 last_message 也走同一个序列化函数,
      // 少这两列就会出现「进会话能看到引用、列表里那条摘要却没有」。
      "m.ref_msg_id,m.ref_snapshot,"
      "s.unread,c.last_seq,s.updated_at,IFNULL(ps.read_seq,0) "
      "FROM im_conversation_state s "
      "JOIN im_conversation c ON c.id=s.conv_id "
      "JOIN im_user u ON u.user_id=IF(c.user_a=" + std::to_string(owner) +
      ",c.user_b,c.user_a) "
      "LEFT JOIN im_message m ON m.msg_id=c.last_msg_id "
      "LEFT JOIN im_conversation_state ps ON ps.conv_id=s.conv_id AND ps.owner_id="
      "IF(c.user_a=" + std::to_string(owner) + ",c.user_b,c.user_a) "
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
      if (values[13] != nullptr) {
        view.last.ref_msg_id = std::stoull(values[13]);
      }
      if (values[14] != nullptr) {
        view.last.ref_snapshot = values[14];
      }
    }
    view.unread = static_cast<uint32_t>(std::stoul(values[15]));
    view.last_seq = std::stoull(values[16]);
    view.updated_at = std::stoll(values[17]);
    view.peer_read_seq = std::stoull(values[18]);
    rows.push_back(std::move(view));
  }
  mysql_free_result(result);
  return rows;
}
