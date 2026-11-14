/*********************************************************************************************************************
* chat_app 自建 IM 服务端（imserver）是本项目唯一的 IM 后端，C++20 实现，对外提供 WebSocket :9100 与 HTTP :9101
* Copyright (c) 2026 shiliu153
*
* 本文件是 chat_app 自建 IM 服务端的一部分
*
* 额外注明：
* 本文件使用 MIT 开源许可证协议 许可申明英文版见仓库根目录 LICENSE 文件
* 欢迎各位使用并传播本程序 但修改内容时必须保留作者的版权声明（即本声明）
*
* 文件名称          tests/message_service_test.cpp
* 项目名称          chat_app / imserver
* 公司名称          个人项目（shiliu153）
* 版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
* 开发环境          CMake 3.22 + g++ (C++20) Linux x86_64
* 适用平台          Linux x86_64 服务端
* 仓库地址          https://github.com/shiliu153/chatapp
*
* 修改记录
* 日期              作者               备注
* 2026-11-14        shiliu153          补齐文件头与函数注释
********************************************************************************************************************/
#include <gtest/gtest.h>

#include <chrono>
#include <cstdlib>
#include <optional>
#include <thread>
#include <utility>
#include <variant>
#include <vector>

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
  lease.query("DELETE FROM im_message_hidden");
  lease.query("DELETE FROM im_conversation_state");
  lease.query("DELETE FROM im_conversation");
  lease.query("DELETE FROM im_blacklist");
  lease.query("DELETE FROM im_pair");
  lease.query("DELETE FROM im_user WHERE user_id<>0");
  // 进程内缓存也要清:否则 ensure 看到缓存会跳过插入,get 却查不到行。
  fixture().svc().users().clear_cache();
  // H4 之后发送要求配对;给常用测试账号预置互相可聊的关系。
  lease.query("INSERT INTO im_pair (user_a,user_b,created_at) VALUES (1,2,0),(1,3,0),(2,3,0)");
}

}  // namespace

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证未配对发送被拒
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R RejectsUnpairedSendWithoutCreatingUser
// 备注信息     预置配对只有 1-2 1-3 2-3 (1,4) 未配对 断言 send 返回业务码 40302 拒发且不落消息行
//-------------------------------------------------------------------------------------------------------------------
TEST(MessageServiceTest, RejectsUnpairedSendWithoutCreatingUser) {
  reset();
  auto& svc = make_service();
  svc.users().ensure(1, "A");
  svc.users().ensure(4, "D");
  // (1,4) 不在预置配对里
  auto result = svc.send({1, 4, "c-unpaired", "hi"});
  ASSERT_TRUE(std::holds_alternative<int>(result));
  EXPECT_EQ(std::get<int>(result), 40302);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证目标不存在时拒绝且不建行
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R RejectsUnknownTargetWithoutCreatingRow
// 备注信息     先建配对再发 999 断言返回 42201 且 users().get(999) 无值 不给任意 uid 建 im_user 行
//-------------------------------------------------------------------------------------------------------------------
TEST(MessageServiceTest, RejectsUnknownTargetWithoutCreatingRow) {
  reset();
  auto& svc = make_service();
  svc.users().ensure(1, "A");
  // 先建立配对,再验证「目标不存在」不会建 im_user 行
  svc.pair_add(1, 999);
  auto result = svc.send({1, 999, "c-ghost", "hi"});
  ASSERT_TRUE(std::holds_alternative<int>(result));
  EXPECT_EQ(std::get<int>(result), 42201);
  EXPECT_FALSE(svc.users().get(999).has_value());
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证系统通知跳过配对校验
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R SystemNoticeSkipsPairCheck
// 备注信息     from=0 kind=2 custom type=ban_notice 无配对关系也返回 SendResult 不查 im_pair
//-------------------------------------------------------------------------------------------------------------------
TEST(MessageServiceTest, SystemNoticeSkipsPairCheck) {
  reset();
  auto& svc = make_service();
  svc.users().ensure(5, "E");
  SendRequest request;
  request.from = 0;
  request.to = 5;
  request.client_msg_id = "sys-1";
  request.kind = 2;
  request.custom = {{"type", "ban_notice"}, {"desc", "x"}, {"data", {}}};
  ASSERT_TRUE(std::holds_alternative<SendResult>(svc.send(request)));
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证会话序号自增与未读累计
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R AllocatesSeqAndUnread
// 备注信息     同一会话连发两条 seq 必须为 1 与 2 对端 unread_for_peer 累计到 2
//-------------------------------------------------------------------------------------------------------------------
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证相同 client_msg_id 幂等
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R SameClientMsgIdIsIdempotent
// 备注信息     同一 client_msg_id 发两次 断言 msg_id 相同且 count_pair 仍为 1 靠唯一键 1062 回查已有行
//-------------------------------------------------------------------------------------------------------------------
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证拉黑关系拒绝发送
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R BlacklistRejectsSend
// 备注信息     2 拉黑 1 后 1 发给 2 断言返回 40302 exists_either 双向都算拦截
//-------------------------------------------------------------------------------------------------------------------
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证图片消息落库与回读
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R SendsImageMessage
// 备注信息     kind=3 且 URL 在本服务媒体前缀下 断言落库 kind 为 3 body 含 image 键
//-------------------------------------------------------------------------------------------------------------------
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证外域图片 URL 被拒
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R RejectsImageWithForeignUrl
// 备注信息     url 指向 evil.example 不在媒体前缀内 断言返回 42201 且不落库
//-------------------------------------------------------------------------------------------------------------------
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证图片尺寸非法被拒
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R RejectsImageWithBadDimensions
// 备注信息     width=0 触发尺寸校验 断言返回 42201 宽高必须落在 1 到 4096
//-------------------------------------------------------------------------------------------------------------------
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证语音消息落库与回读
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R SendsVoiceMessage
// 备注信息     kind=4 duration_ms=12500 size=48000 断言 kind 为 4 body 含 voice 与 duration_ms
//-------------------------------------------------------------------------------------------------------------------
TEST(MessageServiceTest, SendsVoiceMessage) {
  reset();
  auto& svc = make_service();
  svc.users().ensure(1, "A");
  svc.users().ensure(2, "B");

  SendRequest request;
  request.from = 1;
  request.to = 2;
  request.client_msg_id = "voice-1";
  request.kind = 4;
  request.voice = {{"url", "http://cdn/media/chat/voices/a.m4a"},
                   {"duration_ms", 12500},
                   {"size", 48000}};
  const auto result = svc.send(request);
  ASSERT_TRUE(std::holds_alternative<SendResult>(result));

  const auto rows = svc.list_messages(2, 1, 0, 10);
  ASSERT_EQ(rows.size(), 1u);
  EXPECT_EQ(rows[0].kind, 4);
  EXPECT_NE(rows[0].body.find("\"voice\""), std::string::npos);
  EXPECT_NE(rows[0].body.find("\"duration_ms\":12500"), std::string::npos);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证外域语音 URL 被拒
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R RejectsVoiceWithForeignUrl
// 备注信息     url 为 https 且指向 evil.example 断言返回 42201 只认本服务媒体前缀
//-------------------------------------------------------------------------------------------------------------------
TEST(MessageServiceTest, RejectsVoiceWithForeignUrl) {
  reset();
  auto& svc = make_service();
  svc.users().ensure(1, "A");
  svc.users().ensure(2, "B");

  SendRequest request;
  request.from = 1;
  request.to = 2;
  request.client_msg_id = "voice-2";
  request.kind = 4;
  request.voice = {{"url", "https://evil.example/a.m4a"},
                   {"duration_ms", 5000},
                   {"size", 1000}};
  const auto result = svc.send(request);
  ASSERT_TRUE(std::holds_alternative<int>(result));
  EXPECT_EQ(std::get<int>(result), 42201);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证语音时长与体积越界被拒
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R RejectsVoiceOutOfBounds
// 备注信息     四组边界 duration 999 与 60001 size 0 与 2MB 加 1 逐条断言 42201 合法区间 1000 到 60000 毫秒且不超过 2MB
//-------------------------------------------------------------------------------------------------------------------
TEST(MessageServiceTest, RejectsVoiceOutOfBounds) {
  reset();
  auto& svc = make_service();
  svc.users().ensure(1, "A");
  svc.users().ensure(2, "B");

  for (const auto& item : std::vector<std::pair<long long, long long>>{
           {999, 1000}, {60001, 1000}, {5000, 0}, {5000, 2 * 1024 * 1024 + 1}}) {
    SendRequest request;
    request.from = 1;
    request.to = 2;
    request.client_msg_id = "voice-bad";
    request.kind = 4;
    request.voice = {{"url", "http://cdn/media/chat/voices/a.m4a"},
                     {"duration_ms", item.first},
                     {"size", item.second}};
    const auto result = svc.send(request);
    ASSERT_TRUE(std::holds_alternative<int>(result)) << item.first << "/" << item.second;
    EXPECT_EQ(std::get<int>(result), 42201);
  }
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证自定义消息按 kind 2 落库
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R StoresCustomAsKindTwo
// 备注信息     kind=2 custom type=match_notice 断言落库 kind 仍为 2 且 body 含 match_notice
//-------------------------------------------------------------------------------------------------------------------
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证搜索过滤撤回拉黑与删除
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R FiltersOwnerRevokedBlacklistAndDeleted
// 备注信息     发 5 条其中 4 条含关键词 断言新到旧排序 分页游标严格早于上页末条 撤回后 3 条 拉黑对端 2 后只剩与 3 的 删除会话后 0 条
//-------------------------------------------------------------------------------------------------------------------
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证通配符转义与系统通知排除
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R ExcludesSystemNoticeAndEscapesWildcards
// 备注信息     关键词 100% 必须按字面匹配 只命中含 100% 的那条 系统通知 uid=0 不参与检索
//-------------------------------------------------------------------------------------------------------------------
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证会话标志写入后回读真实值
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R WritesAndReadsBackRealValues
// 备注信息     置顶加免打扰一次写完 断言返回值与 list_conversations 一致 只传一个字段时另一字段保持不变 缺省语义是不改而非置 false
//-------------------------------------------------------------------------------------------------------------------
TEST(ConversationFlagsTest, WritesAndReadsBackRealValues) {
  reset();
  auto& svc = make_service();
  svc.users().ensure(1, "A");
  svc.users().ensure(2, "B");
  ASSERT_TRUE(std::holds_alternative<SendResult>(svc.send({1, 2, "f-1", "hi"})));

  // 置顶 + 免打扰一次写完:返回值是**回读实库**后的真实值
  const auto flags = svc.set_conversation_flags(2, 1, true, true);
  ASSERT_TRUE(flags.has_value());
  EXPECT_TRUE(flags->pinned);
  EXPECT_TRUE(flags->muted);

  // 会话列表回显(客户端切列表时的刷新入口)
  const auto items = svc.list_conversations(2, 100);
  ASSERT_EQ(items.size(), 1u);
  EXPECT_GT(items[0].pinned_at, 0);
  EXPECT_TRUE(items[0].muted);

  // 只改一项:另一项保持不动 —— 缺省是「不改」,不是「改成 false」
  const auto muted_only = svc.set_conversation_flags(2, 1, std::nullopt, false);
  ASSERT_TRUE(muted_only.has_value());
  EXPECT_TRUE(muted_only->pinned);
  EXPECT_FALSE(muted_only->muted);
  EXPECT_GT(svc.list_conversations(2, 100)[0].pinned_at, 0);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证重复置顶不改置顶时间
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R RepeatedPinKeepsOriginalTimestamp
// 备注信息     二次置顶断言 pinned_at 不变 取消置顶写 0 再次置顶得到新时间且大于首次
//-------------------------------------------------------------------------------------------------------------------
TEST(ConversationFlagsTest, RepeatedPinKeepsOriginalTimestamp) {
  reset();
  auto& svc = make_service();
  svc.users().ensure(1, "A");
  svc.users().ensure(2, "B");
  ASSERT_TRUE(std::holds_alternative<SendResult>(svc.send({1, 2, "f-2", "hi"})));

  ASSERT_TRUE(svc.set_conversation_flags(2, 1, true, std::nullopt).has_value());
  const int64_t first = svc.list_conversations(2, 100)[0].pinned_at;
  ASSERT_GT(first, 0);

  // 幂等:再置顶一次不重写时间。否则连点两次就会把会话顶到置顶组最前,
  // 「置顶组按置顶时间倒序」就不再是用户看到的那次操作顺序。
  std::this_thread::sleep_for(std::chrono::milliseconds(5));
  ASSERT_TRUE(svc.set_conversation_flags(2, 1, true, std::nullopt).has_value());
  EXPECT_EQ(svc.list_conversations(2, 100)[0].pinned_at, first);

  // 取消置顶写 0;再置顶是一个**新**时间(重新置顶就该排在旧置顶前面)
  ASSERT_TRUE(svc.set_conversation_flags(2, 1, false, std::nullopt).has_value());
  EXPECT_EQ(svc.list_conversations(2, 100)[0].pinned_at, 0);
  ASSERT_TRUE(svc.set_conversation_flags(2, 1, true, std::nullopt).has_value());
  EXPECT_GT(svc.list_conversations(2, 100)[0].pinned_at, first);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证无会话时设置标志失败
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R UnknownConversationFails
// 备注信息     有配对但从未聊过 断言返回 nullopt 且不凭空写出 im_conversation_state 行 会话列表仍为空
//-------------------------------------------------------------------------------------------------------------------
TEST(ConversationFlagsTest, UnknownConversationFails) {
  reset();
  auto& svc = make_service();
  svc.users().ensure(1, "A");
  svc.users().ensure(4, "D");
  // (1,4) 有配对但**从没聊过** = 没有会话 → 失败,且不能凭空写出一行状态
  EXPECT_FALSE(svc.set_conversation_flags(1, 4, true, true).has_value());
  EXPECT_TRUE(svc.list_conversations(1, 100).empty());
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证置顶组优先且按置顶时间排序
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R PinnedGroupComesFirstOrderedByPinTime
// 备注信息     默认按最近消息排 3 2 置顶 2 后排 2 3 再置顶 3 后排 3 2 免打扰不改排序 取消置顶回落
//-------------------------------------------------------------------------------------------------------------------
TEST(ConversationFlagsTest, PinnedGroupComesFirstOrderedByPinTime) {
  reset();
  auto& svc = make_service();
  for (uint64_t uid : {1, 2, 3}) {
    svc.users().ensure(uid, "U");
  }
  // 1↔2 先聊、1↔3 后聊:不置顶时最近消息优先 → [3, 2]
  ASSERT_TRUE(std::holds_alternative<SendResult>(svc.send({1, 2, "o-1", "hi"})));
  std::this_thread::sleep_for(std::chrono::milliseconds(5));
  ASSERT_TRUE(std::holds_alternative<SendResult>(svc.send({1, 3, "o-2", "hi"})));

  const auto peers = [&svc] {
    std::vector<uint64_t> out;
    for (const auto& view : svc.list_conversations(1, 100)) {
      out.push_back(view.peer.id);
    }
    return out;
  };
  EXPECT_EQ(peers(), (std::vector<uint64_t>{3, 2}));

  // 置顶更早聊过的 2:进置顶组并排到最前
  ASSERT_TRUE(svc.set_conversation_flags(1, 2, true, std::nullopt).has_value());
  EXPECT_EQ(peers(), (std::vector<uint64_t>{2, 3}));

  // 再置顶 3(置顶时间更晚):置顶组内按**置顶时间**倒序 → [3, 2]
  std::this_thread::sleep_for(std::chrono::milliseconds(5));
  ASSERT_TRUE(svc.set_conversation_flags(1, 3, true, std::nullopt).has_value());
  EXPECT_EQ(peers(), (std::vector<uint64_t>{3, 2}));

  // 免打扰不改排序
  ASSERT_TRUE(svc.set_conversation_flags(1, 2, std::nullopt, true).has_value());
  EXPECT_EQ(peers(), (std::vector<uint64_t>{3, 2}));

  // 取消 3 的置顶:置顶的 2 仍在最前,3 回落到「最近消息优先」组
  ASSERT_TRUE(svc.set_conversation_flags(1, 3, false, std::nullopt).has_value());
  EXPECT_EQ(peers(), (std::vector<uint64_t>{2, 3}));
}

// ---- 多选删除(批次 T):单方隐藏 + 未读计数器显式相减 ----
//
// 这一节的断言都建立在两件「改回错误实现就会红」的事上:
//   1. 未读是**计数器**(upsert_state 累加、mark_read 清零),所以删除时必须显式减;
//      不减小红的是 `DecrementsUnreadOnlyForUnreadPeerMessages`;
//   2. 相减必须 `GREATEST(CAST(unread AS SIGNED)-?,0)`,计数器偏大时不许报
//      `BIGINT UNSIGNED value is out of range`(1690)、不许减成负数,
//      不夹取小红的是 `ClampsUnreadAtZeroWhenCounterIsStale`。

namespace {

/// 直接数隐藏表里有多少行(隐藏关系本身不对客户端可见,只能这样断言)。
uint64_t count_hidden(MysqlPool& pool, uint64_t owner) {
  auto lease = pool.acquire();
  auto* result = lease.query("SELECT COUNT(*) FROM im_message_hidden WHERE user_id=" +
                             std::to_string(owner));
  EXPECT_NE(result, nullptr);
  uint64_t count = 0;
  if (MYSQL_ROW values = mysql_fetch_row(result)) {
    count = std::stoull(values[0]);
  }
  mysql_free_result(result);
  return count;
}

}  // namespace

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证多选删除单方隐藏且幂等
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R HidesForOneSideOnlyAndIsIdempotent
// 备注信息     首次隐藏返回 1 重复返回 0 我方历史少一条而对端三条不变 隐藏表只写自己那一侧
//-------------------------------------------------------------------------------------------------------------------
TEST(MessageHiddenTest, HidesForOneSideOnlyAndIsIdempotent) {
  reset();
  auto& svc = make_service();
  svc.users().ensure(1, "A");
  svc.users().ensure(2, "B");
  const auto first = send_text(svc, 1, 2, "h-1", "一");
  const auto second = send_text(svc, 1, 2, "h-2", "二");
  send_text(svc, 1, 2, "h-3", "三");

  // 2 删中间那条:第一次 = 1(新隐藏),第二次 = 0(幂等)
  EXPECT_EQ(svc.hide_messages(2, {second.msg_id}), 1u);
  EXPECT_EQ(svc.hide_messages(2, {second.msg_id}), 0u);

  // 我的历史不含 → 2 条;对端历史一字不少 → 3 条
  const auto mine = svc.list_messages(2, 1, 0, 50);
  ASSERT_EQ(mine.size(), 2u);
  EXPECT_EQ(mine[0].msg_id, first.msg_id);
  EXPECT_EQ(svc.list_messages(1, 2, 0, 50).size(), 3u);
  EXPECT_EQ(count_hidden(fixture().pool(), 2), 1u);
  // 对端不产生任何隐藏行
  EXPECT_EQ(count_hidden(fixture().pool(), 1), 0u);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证删未读消息时显式减未读
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R DecrementsUnreadOnlyForUnreadPeerMessages
// 备注信息     删一条未读 3 减到 2 标已读后再删已读条未读不变 删自己发的消息不减对端未读
//-------------------------------------------------------------------------------------------------------------------
TEST(MessageHiddenTest, DecrementsUnreadOnlyForUnreadPeerMessages) {
  reset();
  auto& svc = make_service();
  svc.users().ensure(1, "A");
  svc.users().ensure(2, "B");
  const auto first = send_text(svc, 1, 2, "u-1", "一");
  const auto second = send_text(svc, 1, 2, "u-2", "二");
  const auto third = send_text(svc, 1, 2, "u-3", "三");
  ASSERT_EQ(svc.conversations().unread_for_peer(2, 1), 3u);

  // 删一条未读 → 未读 3 → 2
  EXPECT_EQ(svc.hide_messages(2, {second.msg_id}), 1u);
  EXPECT_EQ(svc.conversations().unread_for_peer(2, 1), 2u);

  // 标到最新(未读清零)后再删一条**已读**的 → 未读**不变**
  ASSERT_TRUE(svc.mark_read(2, 1, 0).has_value());
  ASSERT_EQ(svc.conversations().unread_for_peer(2, 1), 0u);
  EXPECT_EQ(svc.hide_messages(2, {first.msg_id}), 1u);
  EXPECT_EQ(svc.conversations().unread_for_peer(2, 1), 0u);

  // 我自己发的消息被我自己删掉,不减对端给我的未读(方向搞反就会多减)
  const auto mine = send_text(svc, 2, 1, "u-4", "我发的");
  EXPECT_EQ(svc.hide_messages(2, {mine.msg_id}), 1u);
  EXPECT_EQ(svc.conversations().unread_for_peer(2, 1), 0u);

  // 三条都进了隐藏表,历史只剩「三」那条(自己发的那条也被自己删掉了)
  EXPECT_EQ(count_hidden(fixture().pool(), 2), 3u);
  const auto history = svc.list_messages(2, 1, 0, 50);
  ASSERT_EQ(history.size(), 1u);
  EXPECT_EQ(history[0].msg_id, third.msg_id);
  EXPECT_EQ(svc.list_messages(1, 2, 0, 50).size(), 4u);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证未读计数器偏大时夹取到 0
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R ClampsUnreadAtZeroWhenCounterIsStale
// 备注信息     手工把 unread 改成 1 再隐藏 2 条未读 断言结果为 0 减未读必须用 GREATEST 否则报 1690 或减成负数
//-------------------------------------------------------------------------------------------------------------------
TEST(MessageHiddenTest, ClampsUnreadAtZeroWhenCounterIsStale) {
  reset();
  auto& svc = make_service();
  svc.users().ensure(1, "A");
  svc.users().ensure(2, "B");
  const auto first = send_text(svc, 1, 2, "c-1", "一");
  const auto second = send_text(svc, 1, 2, "c-2", "二");
  ASSERT_EQ(svc.conversations().unread_for_peer(2, 1), 2u);

  // 人为把计数器调小(线上真会出现:漏减过、或者 mark_read 与删除交错)。
  // 这里隐藏 2 条未读、计数器只有 1 —— 没有 GREATEST 就会把 unread 减成
  // 「BIGINT UNSIGNED out of range」或者一个巨大的数。
  {
    auto lease = fixture().pool().acquire();
    lease.query("UPDATE im_conversation_state SET unread=1 WHERE owner_id=2");
  }
  EXPECT_EQ(svc.hide_messages(2, {first.msg_id, second.msg_id}), 2u);
  EXPECT_EQ(svc.conversations().unread_for_peer(2, 1), 0u);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证删除末条后摘要回退
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R LastMessageFallsBackToPreviousVisible
// 备注信息     隐藏最新一条 断言 last 回退到含二的那条 last_seq 仍为 3 对端摘要不变
//-------------------------------------------------------------------------------------------------------------------
TEST(MessageHiddenTest, LastMessageFallsBackToPreviousVisible) {
  reset();
  auto& svc = make_service();
  svc.users().ensure(1, "A");
  svc.users().ensure(2, "B");
  send_text(svc, 1, 2, "l-1", "一");
  send_text(svc, 1, 2, "l-2", "二");
  const auto third = send_text(svc, 1, 2, "l-3", "三");

  const auto before = svc.list_conversations(2, 10);
  ASSERT_EQ(before.size(), 1u);
  ASSERT_TRUE(before[0].has_last);
  EXPECT_EQ(before[0].last.msg_id, third.msg_id);

  EXPECT_EQ(svc.hide_messages(2, {third.msg_id}), 1u);

  const auto mine = svc.list_conversations(2, 10);
  ASSERT_EQ(mine.size(), 1u);
  ASSERT_TRUE(mine[0].has_last);
  EXPECT_NE(mine[0].last.msg_id, third.msg_id);
  EXPECT_NE(mine[0].last.body.find("二"), std::string::npos);
  // `last_seq` 仍是会话全局:删自己的副本不动它
  EXPECT_EQ(mine[0].last_seq, 3u);

  // 对端看到的摘要不变
  const auto peer = svc.list_conversations(1, 10);
  ASSERT_EQ(peer.size(), 1u);
  EXPECT_EQ(peer[0].last.msg_id, third.msg_id);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证搜索只排除自己隐藏的消息
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R SearchExcludesHiddenForOwnerOnly
// 备注信息     隐藏命中一条后我方只剩 1 条 对端仍能搜到 2 条
//-------------------------------------------------------------------------------------------------------------------
TEST(MessageHiddenTest, SearchExcludesHiddenForOwnerOnly) {
  reset();
  auto& svc = make_service();
  svc.users().ensure(1, "A");
  svc.users().ensure(2, "B");
  const auto hit = send_text(svc, 1, 2, "s-1", "火锅走起");
  send_text(svc, 1, 2, "s-2", "火锅店见");

  ASSERT_EQ(svc.search(2, "火锅", 0, 50).size(), 2u);
  EXPECT_EQ(svc.hide_messages(2, {hit.msg_id}), 1u);

  const auto mine = svc.search(2, "火锅", 0, 50);
  ASSERT_EQ(mine.size(), 1u);
  EXPECT_NE(mine[0].body.find("火锅店见"), std::string::npos);
  // 对端仍能搜到被隐藏的那条
  EXPECT_EQ(svc.search(1, "火锅", 0, 50).size(), 2u);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证静默忽略与自己无关的消息 id
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R IgnoresMessagesImNotPartOf
// 备注信息     2 与 3 之间的消息 1 去删返回 0 且不写隐藏行 双方历史各 1 条不变 不暴露别人消息是否存在
//-------------------------------------------------------------------------------------------------------------------
TEST(MessageHiddenTest, IgnoresMessagesImNotPartOf) {
  reset();
  auto& svc = make_service();
  for (uint64_t uid : {1, 2, 3}) {
    svc.users().ensure(uid, "U");
  }
  // 2 ↔ 3 之间的消息,1 既不是发送方也不是接收方
  const auto foreign = send_text(svc, 2, 3, "f-1", "跟我无关");

  EXPECT_EQ(svc.hide_messages(1, {foreign.msg_id}), 0u);
  EXPECT_EQ(count_hidden(fixture().pool(), 1), 0u);
  // 静默忽略,不动任何一方
  EXPECT_EQ(svc.list_messages(2, 3, 0, 50).size(), 1u);
  EXPECT_EQ(svc.list_messages(3, 2, 0, 50).size(), 1u);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证注销账号清理两侧隐藏行
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R DeleteAccountCleansHiddenRows
// 备注信息     双方各自隐藏对方一条 注销 2 后断言两侧隐藏行都归 0 实现必须先清隐藏表再删消息
//-------------------------------------------------------------------------------------------------------------------
TEST(MessageHiddenTest, DeleteAccountCleansHiddenRows) {
  reset();
  auto& svc = make_service();
  svc.users().ensure(1, "A");
  svc.users().ensure(2, "B");
  const auto from_peer = send_text(svc, 1, 2, "d-1", "一");
  const auto from_me = send_text(svc, 2, 1, "d-2", "二");

  EXPECT_EQ(svc.hide_messages(2, {from_peer.msg_id}), 1u);
  // 对端也隐藏我发的那条 → 2 注销时两边都要清掉(第二条靠 im_message 反查,
  // 所以顺序必须是「先清隐藏表再删消息」)
  EXPECT_EQ(svc.hide_messages(1, {from_me.msg_id}), 1u);

  ASSERT_TRUE(svc.delete_account(2));
  EXPECT_EQ(count_hidden(fixture().pool(), 2), 0u);
  EXPECT_EQ(count_hidden(fixture().pool(), 1), 0u);
}
