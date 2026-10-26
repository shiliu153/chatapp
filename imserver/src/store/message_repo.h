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
  std::optional<MessageRow> get(MysqlPool::Lease& lease, uint64_t msg_id);
  std::vector<MessageRow> list(MysqlPool::Lease& lease, uint64_t conv_id, uint64_t before_seq,
                               int limit);
  /// 关键词搜索:只搜我参与的、未删除会话里的未撤回文本消息,按 msg_id 倒序。
  ///
  /// Args:
  ///   lease: 借出的数据库连接。
  ///   uid: 请求者账号(只能搜到自己参与的会话)。
  ///   keyword: 用户关键词(内部按 LIKE 转义,大小写不敏感)。
  ///   before_id: 游标,只取 msg_id 小于它的消息;0 表示第一页。
  ///   limit: 最多返回条数(1–100)。
  ///
  /// Returns:
  ///   命中的消息行,新 → 旧。
  std::vector<MessageRow> search(MysqlPool::Lease& lease, uint64_t uid,
                                 const std::string& keyword, uint64_t before_id, int limit);
  std::vector<MessageRow> search(uint64_t uid, const std::string& keyword, uint64_t before_id,
                                 int limit);
  void revoke(MysqlPool::Lease& lease, uint64_t msg_id, int64_t now_ms);
  uint64_t count_pair(MysqlPool::Lease& lease, uint64_t a, uint64_t b);
  uint64_t count_pair(uint64_t a, uint64_t b);
  void delete_for_user(MysqlPool::Lease& lease, uint64_t uid);

 private:
  MysqlPool& pool_;
};
