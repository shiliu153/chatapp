#include <gtest/gtest.h>

#include <cstdlib>
#include <variant>

#include "service/message_service.h"

namespace {

class Fixture {
 public:
  explicit Fixture(const char* dsn)
      : pool_(parse_mysql_dsn(dsn), 4),
        users_(pool_),
        conversations_(pool_),
        messages_(pool_),
        blacklist_(pool_),
        svc_(pool_, users_, conversations_, messages_, blacklist_) {}

  MysqlPool& pool() { return pool_; }
  MessageService& svc() { return svc_; }

 private:
  MysqlPool pool_;
  UserRepo users_;
  ConversationRepo conversations_;
  MessageRepo messages_;
  BlacklistRepo blacklist_;
  MessageService svc_;
};

Fixture& fixture() {
  static Fixture instance(std::getenv("IM_TEST_MYSQL_DSN"));
  return instance;
}

MessageService& make_service() { return fixture().svc(); }

void reset() {
  auto lease = fixture().pool().acquire();
  lease.query("DELETE FROM im_message");
  lease.query("DELETE FROM im_conversation_state");
  lease.query("DELETE FROM im_conversation");
  lease.query("DELETE FROM im_blacklist");
  lease.query("DELETE FROM im_user WHERE user_id<>0");
}

}  // namespace

TEST(MessageServiceTest, AllocatesSeqAndUnread) {
  reset();
  auto& svc = make_service();
  svc.users().ensure(1, "A");
  svc.users().ensure(2, "B");

  auto first = svc.send({1, 2, "c-1", "你好"});
  ASSERT_TRUE(std::holds_alternative<SendResult>(first));
  EXPECT_EQ(std::get<SendResult>(first).seq, 1u);

  auto second = svc.send({1, 2, "c-2", "在吗"});
  ASSERT_TRUE(std::holds_alternative<SendResult>(second));
  EXPECT_EQ(std::get<SendResult>(second).seq, 2u);

  EXPECT_EQ(svc.conversations().unread_for_peer(2, 1), 2u);
}

TEST(MessageServiceTest, SameClientMsgIdIsIdempotent) {
  reset();
  auto& svc = make_service();
  svc.users().ensure(1, "A");
  svc.users().ensure(2, "B");

  auto a = svc.send({1, 2, "same", "hi"});
  auto b = svc.send({1, 2, "same", "hi"});
  ASSERT_TRUE(std::holds_alternative<SendResult>(a));
  ASSERT_TRUE(std::holds_alternative<SendResult>(b));
  EXPECT_EQ(std::get<SendResult>(a).msg_id, std::get<SendResult>(b).msg_id);
  EXPECT_EQ(svc.messages().count_pair(1, 2), 1u);
}

TEST(MessageServiceTest, BlacklistRejectsSend) {
  reset();
  auto& svc = make_service();
  svc.users().ensure(1, "A");
  svc.users().ensure(2, "B");
  svc.blacklist().add(2, 1);

  auto result = svc.send({1, 2, "c-1", "hi"});
  ASSERT_TRUE(std::holds_alternative<int>(result));
  EXPECT_EQ(std::get<int>(result), 40302);
}
