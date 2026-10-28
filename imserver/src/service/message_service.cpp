#include "service/message_service.h"

#include <algorithm>
#include <chrono>
#include <cctype>
#include <cstdlib>
#include <stdexcept>
#include <thread>

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
                               BlacklistRepo& blacklist, std::size_t text_max,
                               std::string media_prefix, std::string media_sign_secret,
                               int media_sign_ttl)
    : pool_(pool),
      users_(users),
      conversations_(conversations),
      messages_(messages),
      blacklist_(blacklist),
      text_max_(text_max),
      media_prefix_(std::move(media_prefix)),
      signer_(std::move(media_sign_secret), media_sign_ttl, media_prefix_) {
  if (const char* slow = std::getenv("IM_SLOW_SEND_MS")) {
    slow_send_ms_ = std::atoi(slow);
  }
}

std::vector<ConversationView> MessageService::list_conversations(uint64_t uid, int limit) {
  auto lease = pool_.acquire();
  return conversations_.list(lease, uid, limit);
}

std::vector<MessageRow> MessageService::list_messages(uint64_t uid, uint64_t peer,
                                                      uint64_t before_seq, int limit) {
  auto lease = pool_.acquire();
  const auto conversation = conversations_.find_pair(lease, uid, peer);
  if (!conversation.has_value()) {
    return {};
  }
  return messages_.list(lease, conversation->id, before_seq, limit);
}

std::vector<MessageRow> MessageService::search(uint64_t uid, const std::string& keyword,
                                               uint64_t before_id, int limit) {
  auto lease = pool_.acquire();
  return messages_.search(lease, uid, keyword, before_id, limit);
}

bool MessageService::mark_read(uint64_t uid, uint64_t peer, uint64_t seq) {
  auto lease = pool_.acquire();
  const auto conversation = conversations_.find_pair(lease, uid, peer);
  if (!conversation.has_value()) {
    return false;
  }
  const uint64_t target = seq == 0 ? conversation->last_seq : seq;
  conversations_.mark_read(lease, uid, peer, target, now_ms());
  return true;
}

std::variant<RevokeResult, int> MessageService::revoke(uint64_t uid, uint64_t msg_id) {
  auto lease = pool_.acquire();
  const auto message = messages_.get(lease, msg_id);
  if (!message.has_value() || message->from_id != uid || message->revoked_at.has_value()) {
    return 41001;
  }
  const int64_t now = now_ms();
  if (now - message->created_at > 120000) {
    return 41001;
  }
  messages_.revoke(lease, msg_id, now);
  RevokeResult result;
  result.msg_id = message->msg_id;
  result.seq = message->seq;
  result.from_id = message->from_id;
  result.to_id = message->to_id;
  result.ts = now;
  return result;
}

bool MessageService::delete_conversation(uint64_t uid, uint64_t peer) {
  auto lease = pool_.acquire();
  const auto conversation = conversations_.find_pair(lease, uid, peer);
  if (!conversation.has_value()) {
    return false;
  }
  conversations_.set_deleted(lease, uid, peer, now_ms());
  return true;
}

bool MessageService::delete_account(uint64_t uid) {
  auto lease = pool_.acquire();
  try {
    lease.begin();
    messages_.delete_for_user(lease, uid);
    conversations_.delete_for_user(lease, uid);
    blacklist_.delete_for_user(lease, uid);
    lease.query("DELETE FROM im_pair WHERE user_a=" + std::to_string(uid) +
                " OR user_b=" + std::to_string(uid));
    users_.remove(lease, uid);
    lease.commit();
    return true;
  } catch (const std::exception& error) {
    try {
      lease.rollback();
    } catch (const std::exception&) {
    }
    log_error("delete_account_failed", {{"uid", std::to_string(uid)}, {"error", error.what()}});
    return false;
  }
}

bool MessageService::update_profile(uint64_t uid,
                                    const std::optional<std::string>& nickname,
                                    const std::optional<std::string>& avatar) {
  auto lease = pool_.acquire();
  users_.update_profile(lease, uid, nickname, avatar, now_ms());
  return true;
}

void MessageService::blacklist_add(uint64_t owner, uint64_t peer) {
  blacklist_.add(owner, peer);
}

void MessageService::blacklist_remove(uint64_t owner, uint64_t peer) {
  auto lease = pool_.acquire();
  blacklist_.remove(lease, owner, peer);
}

bool MessageService::pair_exists(MysqlPool::Lease& lease, uint64_t a, uint64_t b) {
  const uint64_t lo = std::min(a, b);
  const uint64_t hi = std::max(a, b);
  auto* result = lease.query("SELECT 1 FROM im_pair WHERE user_a=" + std::to_string(lo) +
                             " AND user_b=" + std::to_string(hi));
  if (result == nullptr) {
    return false;
  }
  const bool exists = mysql_fetch_row(result) != nullptr;
  mysql_free_result(result);
  return exists;
}

bool MessageService::pair_exists(uint64_t a, uint64_t b) {
  auto lease = pool_.acquire();
  return pair_exists(lease, a, b);
}

void MessageService::pair_add(uint64_t a, uint64_t b) {
  const uint64_t lo = std::min(a, b);
  const uint64_t hi = std::max(a, b);
  auto lease = pool_.acquire();
  Stmt stmt(lease.get(),
            "INSERT INTO im_pair (user_a,user_b,created_at) VALUES (?,?,?) "
            "ON DUPLICATE KEY UPDATE user_a=user_a");
  stmt.bind_uint(0, lo);
  stmt.bind_uint(1, hi);
  stmt.bind_uint(2, static_cast<uint64_t>(now_ms()));
  stmt.execute();
}

void MessageService::pair_remove(uint64_t a, uint64_t b) {
  const uint64_t lo = std::min(a, b);
  const uint64_t hi = std::max(a, b);
  auto lease = pool_.acquire();
  Stmt stmt(lease.get(), "DELETE FROM im_pair WHERE user_a=? AND user_b=?");
  stmt.bind_uint(0, lo);
  stmt.bind_uint(1, hi);
  stmt.execute();
}

bool MessageService::ready() {
  try {
    auto lease = pool_.acquire();
    auto* result = lease.query("SELECT 1");
    if (result != nullptr) {
      mysql_free_result(result);
    }
    return true;
  } catch (const std::exception&) {
    return false;
  }
}

std::variant<SendResult, int> MessageService::send(const SendRequest& request) {
  if (request.to == 0 || request.from == request.to ||
      !valid_client_id(request.client_msg_id)) {
    return 42201;
  }

  // 按 kind 分别校验并构造落库 body:1=text、2=custom、3=image、4=voice
  nlohmann::json body;
  try {
    if (request.kind == 1) {
      const auto text = trim(request.text);
      if (text.empty() || utf8_length(text) > text_max_) {
        return 42201;
      }
      body = {{"text", text}};
    } else if (request.kind == 2) {
      if (!request.custom.is_object() || request.custom.value("type", "").empty()) {
        return 42201;
      }
      body = request.custom;
    } else if (request.kind == 3) {
      // 图片只接受本服务媒体前缀下的 URL,并落**规范 URL**(去掉 query):
      // 客户端带上来的签名是上传那一刻的,存下来会在过期后变成死链,
      // 读的时候由 MediaSigner 现签(见 frames.h / http_api.cpp)。
      const auto& image = request.image;
      if (!image.is_object()) {
        return 42201;
      }
      const auto canonical_url = signer_.canonical(image.value("url", std::string()));
      const auto canonical_thumb = signer_.canonical(image.value("thumb_url", std::string()));
      if (!canonical_url.has_value() || !canonical_thumb.has_value()) {
        return 42201;
      }
      const auto width = image.value("width", 0ULL);
      const auto height = image.value("height", 0ULL);
      const auto size = image.value("size", 0ULL);
      if (canonical_url->size() > 512 || canonical_thumb->size() > 512 || width == 0 ||
          height == 0 || width > 4096 || height > 4096 || size == 0 ||
          size > 5 * 1024 * 1024) {
        return 42201;
      }
      nlohmann::json stored = image;
      stored["url"] = *canonical_url;
      stored["thumb_url"] = *canonical_thumb;
      body = {{"image", stored}};
    } else if (request.kind == 4) {
      // 语音与图片同理:只接受本服务媒体前缀下的 URL,落规范 URL,读时现签
      const auto& voice = request.voice;
      if (!voice.is_object()) {
        return 42201;
      }
      const auto canonical = signer_.canonical(voice.value("url", std::string()));
      if (!canonical.has_value() || canonical->size() > 512) {
        return 42201;
      }
      const auto duration = voice.value("duration_ms", 0LL);
      const auto size = voice.value("size", 0LL);
      if (duration < 1000 || duration > 60000 || size <= 0 ||
          size > 2 * 1024 * 1024) {
        return 42201;
      }
      nlohmann::json stored = voice;
      stored["url"] = *canonical;
      body = {{"voice", stored}};
    } else {
      return 42201;
    }
  } catch (const std::exception&) {
    return 42201;
  }

  // 冷启动时大量新会话并发创建会在 im_conversation 的唯一键上死锁;
  // 死锁(1213)与锁等待超时(1205)是 MySQL 的可重试错误,重试 3 次对上层无感。
  for (int attempt = 0; attempt < 3; ++attempt) {
    auto lease = pool_.acquire();
    try {
      lease.begin();
      const auto t0 = std::chrono::steady_clock::now();
      auto since = [&t0]() {
        return std::chrono::duration_cast<std::chrono::microseconds>(
                   std::chrono::steady_clock::now() - t0)
            .count();
      };
      // 聊天权限:只有配对关系才允许发消息(系统通知 from=0 豁免)。
      // 未配对直接 40302,不建 im_user 行,避免任意 uid 都能被写库(H4)。
      if (request.from != 0 && !pair_exists(lease, request.from, request.to)) {
        lease.rollback();
        return 40302;
      }
      if (!users_.get(lease, request.to).has_value()) {
        lease.rollback();
        return 42201;
      }
      if (request.from != 0) {
        users_.ensure(lease, request.from, "");
      }
      const bool blocked =
          request.from != 0 && blacklist_.exists_either(lease, request.from, request.to);
      const auto m_blacklist = since();
      if (blocked) {
        lease.rollback();
        return 40302;
      }

      const int64_t now = now_ms();
      const auto conversation =
          conversations_.lock_pair(lease, request.from, request.to, now);
      const auto m_lock = since();
      const uint64_t seq = conversation.last_seq + 1;
      const std::string body_json = body.dump();

      uint64_t msg_id = 0;
      try {
        msg_id = messages_.insert(lease, conversation.id, seq, request.from, request.to,
                                  request.kind, body_json, request.client_msg_id, now);
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
      const auto m_insert = since();

      conversations_.touch(lease, conversation.id, seq, msg_id, now);
      const auto m_touch = since();
      conversations_.upsert_states(lease, request.to, 1, request.from, 0, conversation.id, now);
      const auto m_state1 = since();
      const auto m_state2 = m_state1;
      lease.commit();
      const auto m_commit = since();

      SendResult result;
      result.msg_id = msg_id;
      result.seq = seq;
      result.ts = now;
      if (auto profile = users_.get(request.from)) {
        result.from_nickname = profile->nickname;
        result.from_avatar = profile->avatar;
      }
      const auto m_total = since();
      if (slow_send_ms_ > 0 && m_total >= slow_send_ms_ * 1000LL) {
        log_error("slow_send", {{"from", std::to_string(request.from)},
                                {"to", std::to_string(request.to)},
                                {"total_us", std::to_string(m_total)},
                                {"blacklist_us", std::to_string(m_blacklist)},
                                {"lock_us", std::to_string(m_lock - m_blacklist)},
                                {"insert_us", std::to_string(m_insert - m_lock)},
                                {"touch_us", std::to_string(m_touch - m_insert)},
                                {"state1_us", std::to_string(m_state1 - m_touch)},
                                {"state2_us", std::to_string(m_state2 - m_state1)},
                                {"commit_us", std::to_string(m_commit - m_state2)},
                                {"profile_us", std::to_string(m_total - m_commit)}});
      }
      return result;
    } catch (const MysqlError& error) {
      try {
        lease.rollback();
      } catch (const std::exception&) {
      }
      if (error.code() == 1213 || error.code() == 1205) {
        std::this_thread::sleep_for(std::chrono::milliseconds(2 * (attempt + 1)));
        continue;
      }
      log_error("send_failed", {{"from", std::to_string(request.from)},
                                {"to", std::to_string(request.to)},
                                {"error", error.what()}});
      return 50001;
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

  log_error("send_failed", {{"from", std::to_string(request.from)},
                            {"to", std::to_string(request.to)},
                            {"error", "deadlock retry exhausted"}});
  return 50001;
}
