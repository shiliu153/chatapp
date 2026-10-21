#pragma once
#include <cstdint>
#include <optional>
#include <vector>

#include "store/models.h"
#include "store/mysql_pool.h"

class ConversationRepo {
 public:
  explicit ConversationRepo(MysqlPool& pool);

  std::optional<ConversationRow> find_pair(MysqlPool::Lease& lease, uint64_t a, uint64_t b);
  ConversationRow lock_pair(MysqlPool::Lease& lease, uint64_t a, uint64_t b, int64_t now_ms);
  void touch(MysqlPool::Lease& lease, uint64_t conv_id, uint64_t seq, uint64_t msg_id,
             int64_t now_ms);
  void upsert_state(MysqlPool::Lease& lease, uint64_t owner, uint64_t conv_id,
                    int unread_delta, int64_t now_ms);
  uint32_t unread_for_peer(MysqlPool::Lease& lease, uint64_t owner, uint64_t peer);
  uint32_t unread_for_peer(uint64_t owner, uint64_t peer);
  void mark_read(MysqlPool::Lease& lease, uint64_t owner, uint64_t peer, uint64_t seq,
                 int64_t now_ms);
  void set_deleted(MysqlPool::Lease& lease, uint64_t owner, uint64_t peer, int64_t now_ms);
  std::vector<ConversationView> list(MysqlPool::Lease& lease, uint64_t owner, int limit);
  void delete_for_user(MysqlPool::Lease& lease, uint64_t uid);

 private:
  MysqlPool& pool_;
};
