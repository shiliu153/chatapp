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

  /// 落一条消息,返回新行的 msg_id。
  ///
  /// Args:
  ///   lease: 借出的数据库连接(调用方已开事务)。
  ///   conv_id: 会话 id。
  ///   seq: 会话内序号(调用方已加锁分配)。
  ///   from_id: 发送者;0 是系统通知。
  ///   to_id: 接收者。
  ///   kind: 1=text 2=custom 3=image 4=voice。
  ///   body: 已校验并序列化的载荷 JSON 文本。
  ///   client_msg_id: 客户端幂等 id。
  ///   now_ms: 服务端时间(毫秒)。
  ///   ref_msg_id: 引用的原消息 id(批次 L-2);无引用时为空。
  ///   ref_snapshot: **服务端生成的**引用快照 JSON 文本;无引用时为空。
  ///
  /// Returns:
  ///   新插入行的自增 id。
  uint64_t insert(MysqlPool::Lease& lease, uint64_t conv_id, uint64_t seq, uint64_t from_id,
                  uint64_t to_id, int kind, const std::string& body,
                  const std::string& client_msg_id, int64_t now_ms,
                  const std::optional<uint64_t>& ref_msg_id = std::nullopt,
                  const std::optional<std::string>& ref_snapshot = std::nullopt);
  std::optional<MessageRow> find_by_client(MysqlPool::Lease& lease, uint64_t from_id,
                                           const std::string& client_msg_id);
  std::optional<MessageRow> find_by_client(uint64_t from_id, const std::string& client_msg_id);
  std::optional<MessageRow> get(MysqlPool::Lease& lease, uint64_t msg_id);
  /// 历史分页:**排除「我隐藏的」**(批次 T 的多选删除)。
  ///
  /// 隐藏关系在 `im_message_hidden`,用 `LEFT JOIN + h.msg_id IS NULL` 排除。这个写法
  /// 必须仍走 `uk_conv_seq(conv_id,seq)`:隐藏行很少,`LEFT JOIN` 是主键点查,不会退化成
  /// 全表扫(EXPLAIN 断言见 `docs/ops/imserver.md` §21)。
  ///
  /// Args:
  ///   lease: 借出的数据库连接。
  ///   owner: 请求者账号(决定排除哪一份隐藏关系)。
  ///   conv_id: 会话 id。
  ///   before_seq: 游标,只取 seq 小于它的消息;0 表示最新一页。
  ///   limit: 最多返回条数(1–100)。
  ///
  /// Returns:
  ///   旧 → 新排列的消息行。
  std::vector<MessageRow> list(MysqlPool::Lease& lease, uint64_t owner, uint64_t conv_id,
                               uint64_t before_seq, int limit);
  /// 从一批 msg_id 里挑出「真实存在且我参与」的消息行(多选删除的前置查询)。
  ///
  /// 不属于我的 id **不报错也不返回** —— 报错会变成「探测别人消息是否存在」的信道。
  ///
  /// Args:
  ///   lease: 借出的数据库连接。
  ///   owner: 请求者账号。
  ///   ids: 候选 msg_id(调用方已去重、已限量 ≤ 50)。
  ///
  /// Returns:
  ///   命中的消息行(顺序不保证)。
  std::vector<MessageRow> find_mine(MysqlPool::Lease& lease, uint64_t owner,
                                    const std::vector<uint64_t>& ids);
  /// 落一条「我不再看到这条消息」的隐藏关系。
  ///
  /// 用 `INSERT IGNORE` + `affected_rows` 区分「本次新隐藏」与「早就删过」,接口的
  /// 幂等语义(`{"deleted": n}` 第二次必须是 0)就建立在这个返回值上。
  ///
  /// Args:
  ///   lease: 借出的数据库连接(调用方已开事务)。
  ///   owner: 隐藏这条消息的人。
  ///   msg_id: 消息 id。
  ///   now_ms: 当前毫秒时间戳。
  ///
  /// Returns:
  ///   true = 本次新隐藏;false = 这一行本来就存在(幂等重放)。
  bool hide(MysqlPool::Lease& lease, uint64_t owner, uint64_t msg_id, int64_t now_ms);
  /// 我在这个会话里**最后一条可见消息**;一条都没有(或全被我隐藏)时 `nullopt`。
  ///
  /// 走 `uk_conv_seq(conv_id,seq)` **反向扫 + LIMIT 1**:隐藏行 ≤ 几条,所以实际只读
  /// 「被隐藏的条数 + 1」行,不会扫整段历史(EXPLAIN 见 `docs/ops/imserver.md` §21)。
  ///
  /// Args:
  ///   lease: 借出的数据库连接。
  ///   owner: 请求者账号(决定排除哪一份隐藏关系)。
  ///   conv_id: 会话 id。
  ///
  /// Returns:
  ///   最后一条可见消息行;没有时 `nullopt`。
  std::optional<MessageRow> last_visible(MysqlPool::Lease& lease, uint64_t owner,
                                         uint64_t conv_id);
  /// 把会话列表的 `last_message` 修成「**我的**最后一条可见消息」(批次 T)。
  ///
  /// 为什么不在列表 SQL 里直接写相关子查询:`c.last_msg_id` 被我隐藏时才会用到回退,
  /// 而相关子查询的形式在 MySQL 8 上会**把整段会话历史读出来再排序**(实测 2000 条的
  /// 会话每条列表项 0.4ms 全量扫,50 个会话 × 2000 条 ≈ 60ms)。这里改成:
  /// 先照旧 join `c.last_msg_id`,只有「这条摘要确实被我隐藏了」的会话才回查一次
  /// —— 绝大多数会话一条额外查询都不用。
  ///
  /// 语义:`last_seq` / `has_last` / `updated_at` 都不动(仍是会话全局);只换摘要。
  ///
  /// Args:
  ///   lease: 借出的数据库连接。
  ///   owner: 列表的主人。
  ///   views: 已按服务端顺序排好的会话列表(原地修补)。
  void apply_visible_last(MysqlPool::Lease& lease, uint64_t owner,
                          std::vector<ConversationView>& views);
  /// 注销清理第一步:删掉「我隐藏过别人消息」的那些行。
  ///
  /// Args:
  ///   lease: 借出的数据库连接。
  ///   uid: 要注销的账号。
  void delete_hidden_by_user(MysqlPool::Lease& lease, uint64_t uid);
  /// 注销清理第二步:删掉「别人隐藏了我的消息」的那些行。
  ///
  /// **必须在 `delete_for_user`(删 `im_message`)之前跑**:它靠 `im_message` 里
  /// `from_id/to_id = uid` 的行反查 msg_id,消息删掉之后就再也查不到了。
  ///
  /// Args:
  ///   lease: 借出的数据库连接。
  ///   uid: 要注销的账号。
  void delete_hidden_by_messages(MysqlPool::Lease& lease, uint64_t uid);
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
