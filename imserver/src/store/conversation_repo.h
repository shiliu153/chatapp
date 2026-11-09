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
  void upsert_states(MysqlPool::Lease& lease, uint64_t owner_a, int delta_a, uint64_t owner_b,
                     int delta_b, uint64_t conv_id, int64_t now_ms);
  uint32_t unread_for_peer(MysqlPool::Lease& lease, uint64_t owner, uint64_t peer);
  uint32_t unread_for_peer(uint64_t owner, uint64_t peer);
  /// 读「owner 自己那一行」的 read_seq(即 owner 读到哪);没有行时返回 0。
  ///
  /// 已读回执广播要的是**写完之后**的准确值(`mark_read` 里是 `GREATEST`,乱序到达的
  /// 旧 `read` 帧不会让值回退),所以必须回读,而不是拿请求里带的 seq 直接广播出去。
  uint64_t read_seq_for(MysqlPool::Lease& lease, uint64_t owner, uint64_t peer);
  void mark_read(MysqlPool::Lease& lease, uint64_t owner, uint64_t peer, uint64_t seq,
                 int64_t now_ms);
  void set_deleted(MysqlPool::Lease& lease, uint64_t owner, uint64_t peer, int64_t now_ms);
  /// 改会话的置顶 / 免打扰(批次 N),返回**回读实库**后的真实值。
  ///
  /// 语义:
  ///   - `pinned` 由「假 → 真」时把 `pinned_at` 写成 `now_ms`(毫秒),取消置顶写 0;
  ///     已经置顶再置顶一次**不重写时间**(否则重复点一次就会把会话顶到置顶组最前,
  ///     不幂等);
  ///   - `muted` 直接写 0/1;
  ///   - 两个入参都可以是 `nullopt`,表示「这一项不改」。
  ///
  /// 置顶 / 免打扰是**单方**的(只写 owner 自己那一行),不通知对端,也不改 `updated_at`
  /// —— `updated_at` 是会话活动时间,标志位变化不是活动。
  ///
  /// Args:
  ///   lease: 已租用的连接。
  ///   owner: 会话主人。
  ///   peer: 会话对端。
  ///   pinned: 置顶开关;`nullopt` = 不改。
  ///   muted: 免打扰开关;`nullopt` = 不改。
  ///   now_ms: 当前毫秒时间戳(新置顶时间用它)。
  ///
  /// Returns:
  ///   写完回读到的真实标志位;会话不存在(未配对 / 从没聊过 / 没有状态行)时 `nullopt`。
  std::optional<ConversationFlags> set_flags(MysqlPool::Lease& lease, uint64_t owner,
                                             uint64_t peer, std::optional<bool> pinned,
                                             std::optional<bool> muted, int64_t now_ms);
  std::vector<ConversationView> list(MysqlPool::Lease& lease, uint64_t owner, int limit);
  void delete_for_user(MysqlPool::Lease& lease, uint64_t uid);

 private:
  /// 按 `(owner, conv_id)` 读标志位;没有这一行时 `nullopt`。
  std::optional<ConversationFlags> flags_of(MysqlPool::Lease& lease, uint64_t owner,
                                            uint64_t conv_id);

  MysqlPool& pool_;
};
