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
        svc_(pool_, users_, conversations_, messages_, blacklist_, 2000,
             "http://cdn/media/chat/") {}

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

TEST(MessageServiceTest, SendsImageMessage) {
  reset();
  auto& svc = make_service();
  svc.users().ensure(1, "A");
  svc.users().ensure(2, "B");

  SendRequest request;
  request.from = 1;
  request.to = 2;
  request.client_msg_id = "img-1";
  request.kind = 3;
  request.image = {{"url", "http://cdn/media/chat/a.jpg"},
                   {"thumb_url", "http://cdn/media/chat/a_thumb.jpg"},
                   {"width", 1080}, {"height", 1440}, {"size", 345678}};
  const auto result = svc.send(request);
  ASSERT_TRUE(std::holds_alternative<SendResult>(result));

  const auto rows = svc.list_messages(2, 1, 0, 10);
  ASSERT_EQ(rows.size(), 1u);
  EXPECT_EQ(rows[0].kind, 3);
  EXPECT_NE(rows[0].body.find("\"image\""), std::string::npos);
}

TEST(MessageServiceTest, RejectsImageWithForeignUrl) {
  reset();
  auto& svc = make_service();
  svc.users().ensure(1, "A");
  svc.users().ensure(2, "B");

  SendRequest request;
  request.from = 1;
  request.to = 2;
  request.client_msg_id = "img-2";
  request.kind = 3;
  request.image = {{"url", "http://evil.example/a.jpg"},
                   {"thumb_url", "http://cdn/media/chat/a_thumb.jpg"},
                   {"width", 1080}, {"height", 1440}, {"size", 345678}};
  const auto result = svc.send(request);
  ASSERT_TRUE(std::holds_alternative<int>(result));
  EXPECT_EQ(std::get<int>(result), 42201);
}

TEST(MessageServiceTest, RejectsImageWithBadDimensions) {
  reset();
  auto& svc = make_service();
  svc.users().ensure(1, "A");
  svc.users().ensure(2, "B");

  SendRequest request;
  request.from = 1;
  request.to = 2;
  request.client_msg_id = "img-3";
  request.kind = 3;
  request.image = {{"url", "http://cdn/media/chat/a.jpg"},
                   {"thumb_url", "http://cdn/media/chat/a_thumb.jpg"},
                   {"width", 0}, {"height", 1440}, {"size", 345678}};
  const auto result = svc.send(request);
  ASSERT_TRUE(std::holds_alternative<int>(result));
  EXPECT_EQ(std::get<int>(result), 42201);
}

TEST(MessageServiceTest, StoresCustomAsKindTwo) {
  reset();
  auto& svc = make_service();
  svc.users().ensure(1, "A");
  svc.users().ensure(2, "B");

  SendRequest request;
  request.from = 1;
  request.to = 2;
  request.client_msg_id = "sys-1";
  request.kind = 2;
  request.custom = {{"type", "match_notice"}, {"desc", "你们已互相喜欢"}, {"data", {}}};
  ASSERT_TRUE(std::holds_alternative<SendResult>(svc.send(request)));

  const auto rows = svc.list_messages(2, 1, 0, 10);
  ASSERT_EQ(rows.size(), 1u);
  EXPECT_EQ(rows[0].kind, 2);
  EXPECT_NE(rows[0].body.find("match_notice"), std::string::npos);
}

namespace {

SendResult send_text(MessageService& svc, uint64_t from, uint64_t to,
                     const std::string& client_id, const std::string& text) {
  SendRequest request;
  request.from = from;
  request.to = to;
  request.client_msg_id = client_id;
  request.text = text;
  const auto result = svc.send(request);
  EXPECT_TRUE(std::holds_alternative<SendResult>(result));
  return std::get<SendResult>(result);
}

}  // namespace

TEST(MessageServiceSearchTest, FiltersOwnerRevokedBlacklistAndDeleted) {
  reset();
  auto& svc = make_service();
  svc.users().ensure(1, "A");
  svc.users().ensure(2, "B");
  svc.users().ensure(3, "C");

  send_text(svc, 2, 1, "s-1", "晚上吃火锅吗");
  send_text(svc, 1, 2, "s-2", "火锅店在楼下");
  send_text(svc, 3, 1, "s-3", "火锅外卖到了");
  send_text(svc, 1, 3, "s-4", "不吃火锅");
  send_text(svc, 2, 1, "s-5", "今天天气不错");

  auto hits = svc.search(1, "火锅", 0, 50);
  ASSERT_EQ(hits.size(), 4u);
  EXPECT_GT(hits[0].msg_id, hits[1].msg_id);  // 新 → 旧
  for (const auto& row : hits) {
    EXPECT_EQ(row.kind, 1);
  }

  // 分页:limit=2 + 游标(第二页严格早于第一页末条)
  auto page1 = svc.search(1, "火锅", 0, 2);
  ASSERT_EQ(page1.size(), 2u);
  auto page2 = svc.search(1, "火锅", page1.back().msg_id, 2);
  ASSERT_EQ(page2.size(), 2u);
  EXPECT_LT(page2.front().msg_id, page1.back().msg_id);

  // 撤回后不可见
  svc.revoke(1, hits[0].msg_id);
  EXPECT_EQ(svc.search(1, "火锅", 0, 50).size(), 3u);

  // 拉黑对端 2 后,与 2 的会话全部不可见
  svc.blacklist_add(1, 2);
  for (const auto& row : svc.search(1, "火锅", 0, 50)) {
    EXPECT_NE(row.from_id, 2u);
    EXPECT_NE(row.to_id, 2u);
  }

  // 再删掉与 3 的会话,就什么都不剩了
  svc.delete_conversation(1, 3);
  EXPECT_EQ(svc.search(1, "火锅", 0, 50).size(), 0u);
}

TEST(MessageServiceSearchTest, ExcludesSystemNoticeAndEscapesWildcards) {
  reset();
  auto& svc = make_service();
  svc.users().ensure(1, "A");
  svc.users().ensure(2, "B");

  send_text(svc, 2, 1, "w-1", "满100减20");
  send_text(svc, 2, 1, "w-2", "满100%减20");
  send_text(svc, 0, 1, "w-3", "系统通知:你的资料已通过");

  // `%` 是 LIKE 通配符,必须按字面匹配:只能命中 w-2
  const auto wildcard = svc.search(1, "100%", 0, 50);
  ASSERT_EQ(wildcard.size(), 1u);
  EXPECT_NE(wildcard[0].body.find("100%"), std::string::npos);

  // 系统通知(uid=0)不参与检索
  EXPECT_TRUE(svc.search(1, "系统通知", 0, 50).empty());
}
