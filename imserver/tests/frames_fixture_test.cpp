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
    ASSERT_TRUE(kind == "text" || kind == "image" || kind == "voice") << name;
    if (kind == "text") {
      ASSERT_TRUE(data.at("text").is_string()) << name;
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
  } else {
    FAIL() << name << " 是未知的上行帧类型: " << type;
  }
}

}  // namespace

TEST(ProtocolFixture, ServerToClientFramesMatchRealSerialization) {
  const auto document = load_fixture("server_to_client.json");
  ASSERT_EQ(document.at("protocol_version"), 1);

  const MediaSigner signer("test-media-secret", 86400, "http://cdn/media/chat/");

  // 固定值:fixture 里的 msg_id / seq / ts / server_time 都是这些常量。
  SendResult result;
  result.msg_id = 900124;
  result.seq = 42;
  result.ts = 1720000000000;
  result.from_nickname = "小九";
  result.from_avatar = "http://cdn/avatar/u2.jpg";

  SendRequest text;
  text.from = 2;
  text.to = 9;
  text.kind = 1;
  text.text = "你好";

  SendRequest image = text;
  image.kind = 3;
  image.image = {{"url", "http://cdn/media/chat/a.jpg"},
                 {"thumb_url", "http://cdn/media/chat/a_thumb.jpg"},
                 {"width", 1080},
                 {"height", 1440},
                 {"size", 345678}};

  SendRequest voice = text;
  voice.kind = 4;
  voice.voice = {{"url", "http://cdn/media/chat/v.m4a"}, {"duration_ms", 3200}, {"size", 12345}};

  SendResult image_result = result;
  image_result.msg_id = 900125;
  image_result.seq = 43;
  image_result.ts = 1720000000001;

  SendResult voice_result = result;
  voice_result.msg_id = 900126;
  voice_result.seq = 44;
  voice_result.ts = 1720000000002;

  const std::map<std::string, std::string> generated = {
      {"auth_ok", auth_ok_frame(9, 1720000000000)},
      {"pong", pong_frame(1720000000000)},
      {"kicked", kicked_frame("kicked")},
      {"error_40101", error_frame(40101, "登录已过期")},
      {"error_42201", error_frame(42201, "未知帧类型")},
      {"ack_send", send_ack_frame("c-1", 900124, 42, 1720000000000)},
      {"ack_ok", ack_frame("read-1", true)},
      {"message_text", build_message_frame(result, text, signer)},
      {"message_image", build_message_frame(image_result, image, signer)},
      {"message_voice", build_message_frame(voice_result, voice, signer)},
      {"read_down", read_frame("u2", 42)},
      {"revoked", revoked_frame(900124, 42, "u2", 1720000000000)},
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

TEST(ProtocolFixture, ClientToServerFramesAreWellFormed) {
  const auto document = load_fixture("client_to_server.json");
  ASSERT_EQ(document.at("protocol_version"), 1);

  for (const auto& item : document.at("frames")) {
    expect_client_frame(item.at("name").get<std::string>(), item.at("frame"));
  }
}
