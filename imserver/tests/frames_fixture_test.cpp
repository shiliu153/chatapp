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
* 文件名称          tests/frames_fixture_test.cpp
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

/// 跨栈协议 fixture 契约测试(backlog E-2)。
///
/// 下行帧用 imserver **真实的序列化函数**生成,与
/// `tests/fixtures/ws/server_to_client.json` 逐字段比对;上行帧做结构校验
/// (字段 / 类型 / 枚举),保证 fixture 里的样例是服务端能理解的形状。
///
/// 为什么这样能防漂移:
///   - 服务端改了帧字段 → 这里红;
///   - 只改 fixture 不改服务端 → 这里也红;
///   - 只改 fixture 不改 App/Web → 那两端的 `protocol_fixture_test` 红。
/// 三端必须在同一次改动里一起改,才能全绿。契约与改法见
/// `tests/fixtures/ws/README.md`。
#include <gtest/gtest.h>

#include <fstream>
#include <map>
#include <string>

#include <nlohmann/json.hpp>

#include "net/frames.h"
#include "util/media_sign.h"

namespace {

using nlohmann::json;

/// 读取 fixture 目录下的 JSON 文件。
///
/// Args:
///   name: 文件名(如 `server_to_client.json`)。
///
/// Returns:
///   解析后的 JSON;打不开时记一次失败并返回空对象。
json load_fixture(const std::string& name) {
  std::ifstream input(std::string(IM_FIXTURE_DIR) + "/" + name);
  EXPECT_TRUE(input.good()) << "打不开 fixture: " << name;
  json document;
  input >> document;
  return document;
}

/// 按 name 找 fixture 里的帧。
///
/// Args:
///   document: 整个 fixture 文件。
///   name: 帧名。
///
/// Returns:
///   帧对象;找不到时记一次失败并返回整个文档(不会走到)。
const json& frame_of(const json& document, const std::string& name) {
  for (const auto& item : document.at("frames")) {
    if (item.at("name") == name) {
      return item.at("frame");
    }
  }
  ADD_FAILURE() << "fixture 里没有帧: " << name;
  return document;
}

/// 递归剥掉媒体 URL 的签名 query(`?e=&s=`)。
///
/// fixture 里存的是不带签名的规范地址;线上帧的 url/thumb_url 每次签名后都带
/// 一段随时间变化的 query,直接比对必然不等。签名算法本身由
/// `media_sign_test.cpp` 单独覆盖,这里只校验字段名与结构。
///
/// Args:
///   node: 待处理的 JSON 子树(就地修改)。
void strip_media_queries(json& node) {
  if (node.is_object()) {
    for (auto& [key, value] : node.items()) {
      if ((key == "url" || key == "thumb_url") && value.is_string()) {
        auto text = value.get<std::string>();
        const auto query = text.find('?');
        if (query != std::string::npos) {
          value = text.substr(0, query);
        }
      } else {
        strip_media_queries(value);
      }
    }
  } else if (node.is_array()) {
    for (auto& item : node) {
      strip_media_queries(item);
    }
  }
}

/// 校验一条上行帧的结构(服务端能不能理解它)。
///
/// Args:
///   name: 帧名,用于失败信息。
///   frame: 帧对象。
void expect_client_frame(const std::string& name, const json& frame) {
  ASSERT_TRUE(frame.is_object()) << name;
  ASSERT_EQ(frame.at("v"), 1) << name;
  const auto type = frame.at("type").get<std::string>();
  ASSERT_TRUE(frame.at("data").is_object()) << name;

  const auto& data = frame.at("data");
  if (type == "auth") {
    ASSERT_TRUE(data.at("token").is_string()) << name;
    EXPECT_FALSE(data.at("token").get<std::string>().empty()) << name;
  } else if (type == "ping") {
    EXPECT_TRUE(data.empty()) << name;
  } else if (type == "send") {
    ASSERT_TRUE(frame.at("id").is_string()) << name;
    EXPECT_EQ(data.at("client_msg_id"), frame.at("id")) << name;
    ASSERT_TRUE(data.at("to").is_string()) << name;
    EXPECT_EQ(data.at("to").get<std::string>().rfind("u", 0), 0U) << name;
    const auto kind = data.at("kind").get<std::string>();
    ASSERT_TRUE(kind == "text" || kind == "image" || kind == "voice" || kind == "custom")
        << name;
    if (kind == "text") {
      ASSERT_TRUE(data.at("text").is_string()) << name;
    } else if (kind == "custom") {
      // 贴纸(批次 J):上行 custom 只允许 type=sticker + sticker_NN 形状的 id。
      // match_notice / ban_notice 这类系统灰条不在上行白名单里(服务端会 42201)。
      const auto& custom = data.at("custom");
      ASSERT_TRUE(custom.is_object()) << name;
      EXPECT_EQ(custom.at("type"), "sticker") << name;
      const auto sticker = custom.at("id").get<std::string>();
      EXPECT_EQ(sticker.rfind("sticker_", 0), 0U) << name;
      EXPECT_EQ(sticker.size(), 10U) << name;
    } else if (kind == "image") {
      const auto& image = data.at("image");
      ASSERT_TRUE(image.is_object()) << name;
      for (const char* key : {"url", "thumb_url"}) {
        ASSERT_TRUE(image.at(key).is_string()) << name << " 缺 " << key;
      }
      for (const char* key : {"width", "height", "size"}) {
        ASSERT_TRUE(image.at(key).is_number()) << name << " 缺 " << key;
      }
    } else {
      const auto& voice = data.at("voice");
      ASSERT_TRUE(voice.is_object()) << name;
      ASSERT_TRUE(voice.at("url").is_string()) << name;
      ASSERT_TRUE(voice.at("duration_ms").is_number()) << name;
    }
    // 引用回复(批次 L-2):`ref_msg_id` 可选,出现时必须是正整数。
    // 上行**只允许**这一个字段 —— 夹带 `ref` 快照的帧在这里不算合法契约。
    if (data.contains("ref_msg_id")) {
      ASSERT_TRUE(data.at("ref_msg_id").is_number_unsigned() ||
                  data.at("ref_msg_id").is_number_integer())
          << name;
      EXPECT_GT(data.at("ref_msg_id").get<int64_t>(), 0) << name;
      EXPECT_FALSE(data.contains("ref")) << name;
    }
  } else if (type == "read") {
    ASSERT_TRUE(frame.at("id").is_string()) << name;
    ASSERT_TRUE(data.at("peer").is_string()) << name;
    EXPECT_EQ(data.at("peer").get<std::string>().rfind("u", 0), 0U) << name;
    ASSERT_TRUE(data.at("seq").is_number_unsigned() || data.at("seq").is_number_integer())
        << name;
  } else if (type == "revoke") {
    ASSERT_TRUE(frame.at("id").is_string()) << name;
    ASSERT_TRUE(data.at("msg_id").is_string()) << name;
  } else if (type == "conversation_delete") {
    ASSERT_TRUE(frame.at("id").is_string()) << name;
    ASSERT_TRUE(data.at("peer").is_string()) << name;
  } else if (type == "typing") {
    // 输入中状态(批次 L-1):**没有 id**(不 ack)、只有 `to`。
    // 这两条断言就是契约本身 —— 少了 id 才是「可丢信号」,多一个 id 就会诱使
    // 客户端等 ack,而服务端超限时是静默丢弃的,等不到。
    EXPECT_FALSE(frame.contains("id")) << name;
    ASSERT_TRUE(data.at("to").is_string()) << name;
    EXPECT_EQ(data.at("to").get<std::string>().rfind("u", 0), 0U) << name;
    EXPECT_EQ(data.size(), 1U) << name;
  } else {
    FAIL() << name << " 是未知的上行帧类型: " << type;
  }
}

}  // namespace

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证下行帧的真实序列化结果与 fixture 逐字段一致
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R ProtocolFixture.ServerToClientFramesMatchRealSerialization
// 备注信息     用真实构造函数生成 17 种下行帧 与 fixtures/ws/server_to_client.json 逐条比对 比对前递归剥掉媒体 URL
//              的 ?e= 与 s= 签名 query 覆盖 ack message read revoked self_read conversation_deleted
//              typing 断言 protocol_version 为 1 且 fixture 新增帧必须在服务端生成表里有对应构造
//-------------------------------------------------------------------------------------------------------------------
TEST(ProtocolFixture, ServerToClientFramesMatchRealSerialization) {
  const auto document = load_fixture("server_to_client.json");
  ASSERT_EQ(document.at("protocol_version"), 1);

  const MediaSigner signer("test-media-secret", 86400, "http://cdn/media/chat/");

  // 固定值:fixture 里的 msg_id / seq / ts / server_time 都是这些常量。
  // 下行 `message` 帧现在由 `message_json` 从**消息行**拼(批次 L-2 统一构造函数),
  // 所以这里造的是 MessageRow 而不是 SendRequest。
  const UserRow profile{2, "小九", "http://cdn/avatar/u2.jpg"};

  MessageRow text;
  text.msg_id = 900124;
  text.conv_id = 7;
  text.seq = 42;
  text.from_id = 2;
  text.to_id = 9;
  text.kind = 1;
  text.body = json{{"text", "你好"}}.dump();
  text.created_at = 1720000000000;

  MessageRow image = text;
  image.msg_id = 900125;
  image.seq = 43;
  image.created_at = 1720000000001;
  image.kind = 3;
  image.body = json{{"image", {{"url", "http://cdn/media/chat/a.jpg"},
                               {"thumb_url", "http://cdn/media/chat/a_thumb.jpg"},
                               {"width", 1080},
                               {"height", 1440},
                               {"size", 345678}}}}
                   .dump();

  MessageRow voice = text;
  voice.msg_id = 900126;
  voice.seq = 44;
  voice.created_at = 1720000000002;
  voice.kind = 4;
  voice.body = json{{"voice", {{"url", "http://cdn/media/chat/v.m4a"},
                               {"duration_ms", 3200},
                               {"size", 12345}}}}
                   .dump();

  // 贴纸:复用 kind=2 custom(批次 J),下行帧与灰条同构,只是 type=sticker
  MessageRow sticker = text;
  sticker.msg_id = 900127;
  sticker.seq = 45;
  sticker.created_at = 1720000000003;
  sticker.kind = 2;
  sticker.body = json{{"type", "sticker"}, {"id", "sticker_01"}}.dump();

  // 引用回复(批次 L-2):ref_snapshot 是服务端生成好存下来的 JSON 文本,
  // 读时原样透出(字段顺序无关,比较的是解析后的对象)。
  MessageRow quote = text;
  quote.msg_id = 900128;
  quote.seq = 46;
  quote.created_at = 1720000000004;
  quote.body = json{{"text", "好,六点"}}.dump();
  quote.ref_msg_id = 900120;
  quote.ref_snapshot = json{{"msg_id", 900120},
                            {"from", "u9"},
                            {"kind", "text"},
                            {"text", "今晚吃饭?"},
                            {"revoked", false}}
                           .dump();

  const std::map<std::string, std::string> generated = {
      {"auth_ok", auth_ok_frame(9, 1720000000000)},
      {"pong", pong_frame(1720000000000)},
      {"kicked", kicked_frame("kicked")},
      {"error_40101", error_frame(40101, "登录已过期")},
      {"error_42201", error_frame(42201, "未知帧类型")},
      {"ack_send", send_ack_frame("c-1", 900124, 42, 1720000000000)},
      {"ack_ok", ack_frame("read-1", true)},
      {"message_text", build_message_frame(text, profile, signer)},
      {"message_image", build_message_frame(image, profile, signer)},
      {"message_voice", build_message_frame(voice, profile, signer)},
      {"message_sticker", build_message_frame(sticker, profile, signer)},
      {"message_quote", build_message_frame(quote, profile, signer)},
      {"read_down", read_frame("u2", 42)},
      {"revoked", revoked_frame(900124, 42, "u2", 1720000000000)},
      // 多端在线(K-3):跨端已读 / 跨端删除。两者都只发给本人的其他端,
      // 与 `read` 帧(发给对端)语义不同,所以是独立的帧类型。
      {"self_read", self_read_frame("u8", 42)},
      {"conversation_deleted", conversation_deleted_frame("u8")},
      // 输入中状态(批次 L-1):可丢信号,无 id、不 ack,只发给对端。
      {"typing", typing_frame("u8")},
  };

  for (const auto& item : document.at("frames")) {
    const auto name = item.at("name").get<std::string>();
    const auto found = generated.find(name);
    ASSERT_NE(found, generated.end()) << "fixture 新增了帧但服务端没有对应构造: " << name;

    auto actual = json::parse(found->second);
    auto expected = item.at("frame");
    strip_media_queries(actual);
    strip_media_queries(expected);
    EXPECT_EQ(actual, expected) << "下行帧与 fixture 不一致: " << name;
  }
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证上行帧 fixture 的结构符合服务端约定
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R ProtocolFixture.ClientToServerFramesAreWellFormed
// 备注信息     逐类型校验 v 为 1 且 data 是对象 auth ping send read revoke conversation_delete typing
//              覆盖 send 的 text custom image voice 四种 kind 贴纸 id 必须是 sticker_ 前缀且长度 10 ref_msg_id
//              只允许正整数并禁止夹带 ref 快照 typing 帧必须没有 id 且 data 只有 to 未知类型直接失败
//-------------------------------------------------------------------------------------------------------------------
TEST(ProtocolFixture, ClientToServerFramesAreWellFormed) {
  const auto document = load_fixture("client_to_server.json");
  ASSERT_EQ(document.at("protocol_version"), 1);

  for (const auto& item : document.at("frames")) {
    expect_client_frame(item.at("name").get<std::string>(), item.at("frame"));
  }
}
