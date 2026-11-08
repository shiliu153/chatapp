#pragma once
#include <cstdint>
#include <optional>
#include <string>
#include <variant>
#include <vector>

#include <nlohmann/json.hpp>

#include "store/blacklist_repo.h"
#include "store/conversation_repo.h"
#include "store/message_repo.h"
#include "store/mysql_pool.h"
#include "store/user_repo.h"
#include "util/media_sign.h"

struct SendRequest {
  uint64_t from = 0;
  uint64_t to = 0;
  std::string client_msg_id;
  std::string text;
  int kind = 1;             // 1=text 2=custom 3=image 4=voice
  nlohmann::json image;     // kind=3 的载荷
  nlohmann::json voice;     // kind=4 的载荷
  nlohmann::json custom;    // kind=2 的载荷
  /// 引用回复(批次 L-2):被引用消息的 id。**只有这一个字段来自客户端** ——
  /// 引用内容(谁说的、说了什么、是否已撤回)一律由服务端回库查并生成快照,
  /// 客户端夹带的 `ref` 载荷在这里根本无处可放。
  std::optional<uint64_t> ref_msg_id;
};

struct SendResult {
  uint64_t msg_id = 0;
  uint64_t seq = 0;
  int64_t ts = 0;
  std::string from_nickname;
  std::string from_avatar;
  /// 刚落库的那一行(含 kind/body/ref_snapshot)。
  ///
  /// 为什么把它带出来:下行 `message` 帧必须与 `/im/api/messages` 用**同一个**
  /// 序列化函数(`frames.h::message_json`),那份函数吃的是 `MessageRow`。
  /// 否则两个构造函数迟早有一边漏字段(引用就是这样漏的)。
  MessageRow row;
};

class MessageService {
 public:
  MessageService(MysqlPool& pool, UserRepo& users, ConversationRepo& conversations,
                 MessageRepo& messages, BlacklistRepo& blacklist,
                 std::size_t text_max = 2000, std::string media_prefix = "",
                 std::string media_sign_secret = "", int media_sign_ttl = 86400);

  std::variant<SendResult, int> send(const SendRequest& request);
  std::vector<ConversationView> list_conversations(uint64_t uid, int limit);
  std::vector<MessageRow> list_messages(uint64_t uid, uint64_t peer, uint64_t before_seq,
                                        int limit);
  /// 关键词搜索(口径见 `MessageRepo::search`)。
  ///
  /// Args:
  ///   uid: 请求者账号。
  ///   keyword: 用户关键词。
  ///   before_id: 游标,0 表示第一页。
  ///   limit: 最多返回条数。
  ///
  /// Returns:
  ///   命中的消息行,新 → 旧。
  std::vector<MessageRow> search(uint64_t uid, const std::string& keyword, uint64_t before_id,
                                 int limit);
  /// 把一个会话标到已读,并返回**写完之后**的已读位置(已读回执广播用)。
  ///
  /// Args:
  ///   uid: 读消息的人。
  ///   peer: 会话对端。
  ///   seq: 读到哪;`0` 表示「读到该会话最新」(`last_seq`)。
  ///
  /// Returns:
  ///   成功时返回实库里的 `read_seq`(已 `GREATEST`,不会回退),会话不存在时 `nullopt`。
  std::optional<uint64_t> mark_read(uint64_t uid, uint64_t peer, uint64_t seq);
  std::variant<RevokeResult, int> revoke(uint64_t uid, uint64_t msg_id);
  bool delete_conversation(uint64_t uid, uint64_t peer);
  bool delete_account(uint64_t uid);
  bool update_profile(uint64_t uid, const std::optional<std::string>& nickname,
                      const std::optional<std::string>& avatar);
  void blacklist_add(uint64_t owner, uint64_t peer);
  void blacklist_remove(uint64_t owner, uint64_t peer);
  /// 配对关系(聊天权限):由 Django 在配对/解除配对/拉黑时同步。
  bool pair_exists(MysqlPool::Lease& lease, uint64_t a, uint64_t b);
  bool pair_exists(uint64_t a, uint64_t b);
  void pair_add(uint64_t a, uint64_t b);
  void pair_remove(uint64_t a, uint64_t b);
  bool ready();

  UserRepo& users() { return users_; }
  ConversationRepo& conversations() { return conversations_; }
  MessageRepo& messages() { return messages_; }
  BlacklistRepo& blacklist() { return blacklist_; }
  const MediaSigner& signer() const { return signer_; }

 private:
  MysqlPool& pool_;
  UserRepo& users_;
  ConversationRepo& conversations_;
  MessageRepo& messages_;
  BlacklistRepo& blacklist_;
  std::size_t text_max_;
  std::string media_prefix_;
  MediaSigner signer_;
  int slow_send_ms_ = 0;
};
