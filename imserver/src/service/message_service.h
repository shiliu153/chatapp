#pragma once
#include <cstdint>
#include <string>
#include <variant>
#include <vector>

#include "store/blacklist_repo.h"
#include "store/conversation_repo.h"
#include "store/message_repo.h"
#include "store/mysql_pool.h"
#include "store/user_repo.h"

struct SendRequest {
  uint64_t from = 0;
  uint64_t to = 0;
  std::string client_msg_id;
  std::string text;
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
                 std::size_t text_max = 2000);

  std::variant<SendResult, int> send(const SendRequest& request);
  std::vector<ConversationView> list_conversations(uint64_t uid, int limit);
  std::vector<MessageRow> list_messages(uint64_t uid, uint64_t peer, uint64_t before_seq,
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

 private:
  MysqlPool& pool_;
  UserRepo& users_;
  ConversationRepo& conversations_;
  MessageRepo& messages_;
  BlacklistRepo& blacklist_;
  std::size_t text_max_;
  int slow_send_ms_ = 0;
};
