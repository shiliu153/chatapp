#include "service/message_service.h"

#include <chrono>
#include <cctype>
#include <stdexcept>

#include <nlohmann/json.hpp>

#include "store/stmt.h"
#include "util/log.h"

namespace {

int64_t now_ms() {
  return std::chrono::duration_cast<std::chrono::milliseconds>(
             std::chrono::system_clock::now().time_since_epoch())
      .count();
}

std::size_t utf8_length(const std::string& text) {
  std::size_t count = 0;
  for (unsigned char ch : text) {
    if ((ch & 0xC0) != 0x80) {
      ++count;
    }
  }
  return count;
}

std::string trim(const std::string& text) {
  const auto first = text.find_first_not_of(" \t\r\n");
  if (first == std::string::npos) {
    return "";
  }
  const auto last = text.find_last_not_of(" \t\r\n");
  return text.substr(first, last - first + 1);
}

bool valid_client_id(const std::string& value) {
  if (value.empty() || value.size() > 64) {
    return false;
  }
  for (unsigned char ch : value) {
    if (!std::isalnum(ch) && ch != '_' && ch != '-') {
      return false;
    }
  }
  return true;
}

SendResult result_for(const MessageRow& row, UserRepo& users) {
  SendResult result;
  result.msg_id = row.msg_id;
  result.seq = row.seq;
  result.ts = row.created_at;
  if (auto profile = users.get(row.from_id)) {
    result.from_nickname = profile->nickname;
    result.from_avatar = profile->avatar;
  }
  return result;
}

}  // namespace

MessageService::MessageService(MysqlPool& pool, UserRepo& users,
                               ConversationRepo& conversations, MessageRepo& messages,
                               BlacklistRepo& blacklist, std::size_t text_max)
    : pool_(pool),
      users_(users),
      conversations_(conversations),
      messages_(messages),
      blacklist_(blacklist),
      text_max_(text_max) {}

std::variant<SendResult, int> MessageService::send(const SendRequest& request) {
  const auto text = trim(request.text);
  if (request.to == 0 || request.from == request.to || text.empty() ||
      utf8_length(text) > text_max_ || !valid_client_id(request.client_msg_id)) {
    return 42201;
  }

  auto lease = pool_.acquire();
  try {
    lease.begin();
    users_.ensure(lease, request.to, "");
    if (request.from != 0 && blacklist_.exists_either(lease, request.from, request.to)) {
      lease.rollback();
      return 40302;
    }

    if (auto existing = messages_.find_by_client(lease, request.from,
                                                 request.client_msg_id)) {
      if (existing->to_id != request.to) {
        lease.rollback();
        return 42201;
      }
      lease.commit();
      return result_for(*existing, users_);
    }

    const int64_t now = now_ms();
    const auto conversation =
        conversations_.lock_pair(lease, request.from, request.to, now);
    const uint64_t seq = conversation.last_seq + 1;
    const std::string body = nlohmann::json{{"text", text}}.dump();

    uint64_t msg_id = 0;
    try {
      msg_id = messages_.insert(lease, conversation.id, seq, request.from, request.to, 1,
                                body, request.client_msg_id, now);
    } catch (const MysqlError& error) {
      if (error.code() != 1062) {
        throw;
      }
      lease.rollback();
      if (auto existing = messages_.find_by_client(request.from, request.client_msg_id)) {
        if (existing->to_id != request.to) {
          return 42201;
        }
        return result_for(*existing, users_);
      }
      return 50001;
    }

    conversations_.touch(lease, conversation.id, seq, msg_id, now);
    conversations_.upsert_state(lease, request.to, conversation.id, 1, now);
    if (request.from != 0) {
      conversations_.upsert_state(lease, request.from, conversation.id, 0, now);
    }
    lease.commit();

    SendResult result;
    result.msg_id = msg_id;
    result.seq = seq;
    result.ts = now;
    if (auto profile = users_.get(request.from)) {
      result.from_nickname = profile->nickname;
      result.from_avatar = profile->avatar;
    }
    return result;
  } catch (const std::exception& error) {
    try {
      lease.rollback();
    } catch (const std::exception&) {
    }
    log_error("send_failed", {{"from", std::to_string(request.from)},
                              {"to", std::to_string(request.to)},
                              {"error", error.what()}});
    return 50001;
  }
}
