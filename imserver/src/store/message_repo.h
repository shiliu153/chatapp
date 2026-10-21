#pragma once
#include <cstdint>
#include <optional>
#include <string>
#include <vector>

#include "store/models.h"
#include "store/mysql_pool.h"

class MessageRepo {
 public:
  explicit MessageRepo(MysqlPool& pool);

  uint64_t insert(MysqlPool::Lease& lease, uint64_t conv_id, uint64_t seq, uint64_t from_id,
                  uint64_t to_id, int kind, const std::string& body,
                  const std::string& client_msg_id, int64_t now_ms);
  std::optional<MessageRow> find_by_client(MysqlPool::Lease& lease, uint64_t from_id,
                                           const std::string& client_msg_id);
  std::optional<MessageRow> find_by_client(uint64_t from_id, const std::string& client_msg_id);
  std::vector<MessageRow> list(MysqlPool::Lease& lease, uint64_t conv_id, uint64_t before_seq,
                               int limit);
  void revoke(MysqlPool::Lease& lease, uint64_t msg_id, int64_t now_ms);
  uint64_t count_pair(MysqlPool::Lease& lease, uint64_t a, uint64_t b);
  uint64_t count_pair(uint64_t a, uint64_t b);
  void delete_for_user(MysqlPool::Lease& lease, uint64_t uid);

 private:
  MysqlPool& pool_;
};
