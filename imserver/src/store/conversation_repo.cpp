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

std::map<uint64_t, uint64_t> ConversationRepo::read_seqs(MysqlPool::Lease& lease, uint64_t owner,
                                                        const std::vector<uint64_t>& conv_ids) {
  std::map<uint64_t, uint64_t> result_map;
  if (conv_ids.empty()) {
    return result_map;
  }
  std::string in_list;
  in_list.reserve(conv_ids.size() * 8);
  for (std::size_t i = 0; i < conv_ids.size(); ++i) {
    if (i > 0) {
      in_list += ",";
    }
    in_list += std::to_string(conv_ids[i]);
  }
  auto* result = lease.query("SELECT conv_id,read_seq FROM im_conversation_state WHERE owner_id=" +
                             std::to_string(owner) + " AND conv_id IN (" + in_list + ")");
  if (result != nullptr) {
    while (MYSQL_ROW values = mysql_fetch_row(result)) {
      result_map[std::stoull(values[0])] = std::stoull(values[1]);
    }
    mysql_free_result(result);
  }
  return result_map;
}

void ConversationRepo::decrement_unread(MysqlPool::Lease& lease, uint64_t owner, uint64_t conv_id,
                                        int delta, int64_t now_ms) {
  if (delta <= 0) {
    return;
  }
  Stmt stmt(lease.get(),
            "UPDATE im_conversation_state "
            "SET unread=GREATEST(CAST(unread AS SIGNED)-?,0),updated_at=? "
            "WHERE owner_id=? AND conv_id=?");
  stmt.bind_int(0, delta);
  stmt.bind_uint(1, static_cast<uint64_t>(now_ms));
  stmt.bind_uint(2, owner);
  stmt.bind_uint(3, conv_id);
  stmt.execute();
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

std::optional<ConversationFlags> ConversationRepo::flags_of(MysqlPool::Lease& lease,
                                                            uint64_t owner, uint64_t conv_id) {
  auto* result = lease.query("SELECT pinned_at,muted FROM im_conversation_state WHERE owner_id=" +
                             std::to_string(owner) +
                             " AND conv_id=" + std::to_string(conv_id));
  if (result == nullptr) {
    return std::nullopt;
  }
  std::optional<ConversationFlags> flags;
  if (MYSQL_ROW values = mysql_fetch_row(result)) {
    ConversationFlags row;
    row.pinned = std::stoll(values[0]) > 0;
    row.muted = std::stoi(values[1]) != 0;
    flags = row;
  }
  mysql_free_result(result);
  return flags;
}

std::optional<ConversationFlags> ConversationRepo::set_flags(MysqlPool::Lease& lease,
                                                            uint64_t owner, uint64_t peer,
                                                            std::optional<bool> pinned,
                                                            std::optional<bool> muted,
                                                            int64_t now_ms) {
  const auto [user_a, user_b] = ordered(owner, peer);
  // 先按 (owner, conv_id) 唯一键拿到这一行:会话不存在(未配对 / 从没聊过)时直接返回
  // nullopt,由上层回 404 —— 不能顺手 INSERT 一行,那会让一个从没聊过的会话凭空出现在列表里。
  auto* result = lease.query(
      "SELECT s.conv_id,s.pinned_at,s.muted FROM im_conversation_state s "
      "JOIN im_conversation c ON c.id=s.conv_id "
      "WHERE s.owner_id=" + std::to_string(owner) +
      " AND c.user_a=" + std::to_string(user_a) +
      " AND c.user_b=" + std::to_string(user_b));
  if (result == nullptr) {
    return std::nullopt;
  }
  uint64_t conv_id = 0;
  int64_t current_pinned_at = 0;
  bool current_muted = false;
  if (MYSQL_ROW values = mysql_fetch_row(result)) {
    conv_id = std::stoull(values[0]);
    current_pinned_at = std::stoll(values[1]);
    current_muted = std::stoi(values[2]) != 0;
  }
  mysql_free_result(result);
  if (conv_id == 0) {
    return std::nullopt;
  }

  int64_t pinned_at = current_pinned_at;
  if (pinned.has_value()) {
    if (!*pinned) {
      pinned_at = 0;
    } else if (pinned_at == 0) {
      // 只在「本来没置顶」时写当前毫秒:已经是置顶状态再置顶一次不重写时间,
      // 重复请求才是幂等的(否则连点两次会把会话顶到置顶组最前)。
      pinned_at = now_ms;
    }
  }
  const bool muted_value = muted.value_or(current_muted);

  if (pinned_at != current_pinned_at || muted_value != current_muted) {
    Stmt stmt(lease.get(),
              "UPDATE im_conversation_state SET pinned_at=?,muted=? WHERE owner_id=? AND conv_id=?");
    stmt.bind_uint(0, static_cast<uint64_t>(pinned_at));
    stmt.bind_int(1, muted_value ? 1 : 0);
    stmt.bind_uint(2, owner);
    stmt.bind_uint(3, conv_id);
    stmt.execute();
  }

  // 回读而不是回显请求参数:接口承诺的是「库里现在的真实值」,与 mark_read 同一个理由。
  return flags_of(lease, owner, conv_id);
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
  // `m` 是会话的**全局**最后一条消息(批次 T 之后仍按 `c.last_msg_id` join):
  // 「我的最后一条可见」不做成相关子查询 —— 那在 MySQL 8 上会把整段会话历史读出来
  // 再排序(实测见 `docs/ops/imserver.md` §21)。改由
  // `MessageRepo::apply_visible_last` 事后修补:只有「这条摘要确实被我隐藏了」的会话
  // 才多查一次,其余会话零额外成本。
  // `last_seq` / `has_last` / `updated_at` 的语义不变(仍是会话全局)。
  const std::string sql =
      "SELECT u.user_id,u.nickname,u.avatar_url,"
      "IFNULL(m.msg_id,0),IFNULL(m.conv_id,0),IFNULL(m.seq,0),IFNULL(m.from_id,0),"
      "IFNULL(m.to_id,0),IFNULL(m.kind,1),IFNULL(m.body,''),"
      "IFNULL(m.client_msg_id,''),IFNULL(m.created_at,0),m.revoked_at,"
      // 引用(批次 L-2):会话列表的 last_message 也走同一个序列化函数,
      // 少这两列就会出现「进会话能看到引用、列表里那条摘要却没有」。
      "m.ref_msg_id,m.ref_snapshot,"
      "s.unread,c.last_seq,s.updated_at,IFNULL(ps.read_seq,0),s.pinned_at,s.muted "
      "FROM im_conversation_state s "
      "JOIN im_conversation c ON c.id=s.conv_id "
      "JOIN im_user u ON u.user_id=IF(c.user_a=" + std::to_string(owner) +
      ",c.user_b,c.user_a) "
      "LEFT JOIN im_message m ON m.msg_id=c.last_msg_id "
      "LEFT JOIN im_conversation_state ps ON ps.conv_id=s.conv_id AND ps.owner_id="
      "IF(c.user_a=" + std::to_string(owner) + ",c.user_b,c.user_a) "
      "WHERE s.owner_id=" + std::to_string(owner) +
      // 置顶优先(批次 N):先按「是否置顶」分组,置顶组内按置顶时间**倒序**
      // (后置顶的更靠前),两组内部都仍按最近消息排。
      // 排序表达式用不上 idx_owner_updated —— 个人项目会话数 < 100,可接受;
      // 若将来上千再谈索引(设计见 batch-m-q §4.2)。
      " AND s.deleted=0 ORDER BY (s.pinned_at>0) DESC, s.pinned_at DESC, c.last_msg_at DESC "
      "LIMIT " + std::to_string(limit);

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
    view.pinned_at = std::stoll(values[19]);
    view.muted = std::stoi(values[20]) != 0;
    rows.push_back(std::move(view));
  }
  mysql_free_result(result);
  return rows;
}
