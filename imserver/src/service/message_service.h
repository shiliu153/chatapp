#pragma once
#include <cstdint>
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
  int kind = 1;             // 1=text 2=custom 3=image
  nlohmann::json image;     // kind=3 的载荷
  nlohmann::json custom;    // kind=2 的载荷
};

struct SendResult {
  uint64_t msg_id = 0;
  uint64_t seq = 0;
  int64_t ts = 0;
  std::string from_nickname;
  std::string from_avatar;
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
  bool mark_read(uint64_t uid, uint64_t peer, uint64_t seq);
  std::variant<RevokeResult, int> revoke(uint64_t uid, uint64_t msg_id);
  bool delete_conversation(uint64_t uid, uint64_t peer);
  bool delete_account(uint64_t uid);
  bool update_profile(uint64_t uid, const std::optional<std::string>& nickname,
                      const std::optional<std::string>& avatar);
  void blacklist_add(uint64_t owner, uint64_t peer);
  void blacklist_remove(uint64_t owner, uint64_t peer);
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
