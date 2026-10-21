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
};

struct ConversationView {
  UserRow peer;
  bool has_last = false;
  MessageRow last;
  uint32_t unread = 0;
  uint64_t last_seq = 0;
  int64_t updated_at = 0;
};

struct RevokeResult {
  uint64_t msg_id = 0;
  uint64_t seq = 0;
  uint64_t from_id = 0;
  uint64_t to_id = 0;
  int64_t ts = 0;
};
