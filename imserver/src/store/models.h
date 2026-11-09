#pragma once
#include <cstdint>
#include <optional>
#include <string>

struct UserRow {
  uint64_t id = 0;
  std::string nickname;
  std::string avatar;
};

struct ConversationRow {
  uint64_t id = 0;
  uint64_t user_a = 0;
  uint64_t user_b = 0;
  uint64_t last_seq = 0;
  uint64_t last_msg_id = 0;
  int64_t last_msg_at = 0;
};

struct StateRow {
  uint64_t owner_id = 0;
  uint64_t conv_id = 0;
  uint32_t unread = 0;
  uint64_t read_seq = 0;
  bool deleted = false;
  int64_t updated_at = 0;
};

struct MessageRow {
  uint64_t msg_id = 0;
  uint64_t conv_id = 0;
  uint64_t seq = 0;
  uint64_t from_id = 0;
  uint64_t to_id = 0;
  int kind = 1;
  std::string body;
  std::string client_msg_id;
  int64_t created_at = 0;
  std::optional<int64_t> revoked_at;
  /// 引用的原消息 id(批次 L-2)。没有引用时为空 —— 这正是「`ref` 键只在有引用时出现」的源头。
  std::optional<uint64_t> ref_msg_id;
  /// **服务端生成的**引用快照(JSON 文本,字段同下行 `ref` 对象)。
  ///
  /// 为什么存快照而不是每次回查:历史分页意味着被引用消息常常不在当前页里,
  /// 只存 id 会让客户端大量显示「原消息不可见」。快照只由服务端生成,
  /// 客户端传上来的一律丢弃(见 `MessageService::send`)。
  std::optional<std::string> ref_snapshot;
};

struct ConversationView {
  UserRow peer;
  bool has_last = false;
  MessageRow last;
  uint32_t unread = 0;
  uint64_t last_seq = 0;
  int64_t updated_at = 0;
  /// **对端**读到哪(站在「我」的视角)。0 = 对端从没读过,不是错误。
  ///
  /// `unread` 是「我」没读的条数,`peer_read_seq` 是「对端」读到哪 —— 两者是
  /// 两条独立链路,别混。客户端用它把 `seq <= peer_read_seq` 的**我方**消息标成已读。
  uint64_t peer_read_seq = 0;
  /// 置顶时刻(毫秒时间戳)。0 = 未置顶 —— 存时间而不是 bool,是因为列表要按
  /// 「置顶时间倒序」排(批次 N)。
  int64_t pinned_at = 0;
  /// 免打扰。**只影响客户端表现**(静音图标 + 未读只显示灰点),服务端不抑制任何东西。
  bool muted = false;
};

/// 一个会话的置顶 / 免打扰标志位(批次 N,owner 维度,存在 `im_conversation_state`)。
struct ConversationFlags {
  bool pinned = false;
  bool muted = false;
};

struct RevokeResult {
  uint64_t msg_id = 0;
  uint64_t seq = 0;
  uint64_t from_id = 0;
  uint64_t to_id = 0;
  int64_t ts = 0;
};
