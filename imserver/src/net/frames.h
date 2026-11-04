#pragma once
#include <nlohmann/json.hpp>

#include <string>

#include "service/message_service.h"
#include "util/media_sign.h"

inline std::string kind_name(int kind) {
  switch (kind) {
    case 2:
      return "custom";
    case 3:
      return "image";
    case 4:
      return "voice";
    default:
      return "text";
  }
}

// 按 kind 拼推送帧:text 带 text,custom 带 custom,image 带 image。
// 图片 URL 在**读时**签名(库里存的是去掉 query 的规范 URL)。
inline std::string build_message_frame(const SendResult& result, const SendRequest& request,
                                       const MediaSigner& signer) {
  nlohmann::json data = {
      {"msg_id", std::to_string(result.msg_id)},
      {"seq", result.seq},
      {"from", "u" + std::to_string(request.from)},
      {"to", "u" + std::to_string(request.to)},
      {"kind", kind_name(request.kind)},
      {"ts", result.ts},
      {"revoked", false},
      {"from_profile",
       {{"nickname", result.from_nickname}, {"avatar", result.from_avatar}}}};
  if (request.kind == 2) {
    data["custom"] = request.custom;
  } else if (request.kind == 3) {
    data["image"] = request.image;
    signer.sign_image(data["image"]);
  } else if (request.kind == 4) {
    data["voice"] = request.voice;
    signer.sign_media(data["voice"], {"url"});
  } else {
    data["text"] = request.text;
  }
  return nlohmann::json{{"v", 1}, {"type", "message"}, {"data", data}}.dump();
}

// ---- 其余下行帧的构造 ----
// 统一放在这里(而不是散落在 ws_server.cpp 的匿名命名空间),是为了让
// `tests/frames_fixture_test.cpp` 用**真实序列化代码**与共享 fixture 比对:
// 服务端改了帧格式,fixture 契约测试立刻红。见 `tests/fixtures/ws/README.md`。

/// 错误帧:`{v,type:error,data:{code,message}}`。
inline std::string error_frame(int code, const std::string& message) {
  return nlohmann::json{
      {"v", 1}, {"type", "error"}, {"data", {{"code", code}, {"message", message}}}}
      .dump();
}

/// 通用 ack(read/revoke/conversation_delete 用):`{v,type:ack,id,data:{ok}}`。
inline std::string ack_frame(const std::string& id, bool ok) {
  return nlohmann::json{{"v", 1}, {"type", "ack"}, {"id", id}, {"data", {{"ok", ok}}}}.dump();
}

/// send 的 ack(形状与通用 ack 不同):`{v,type:ack,id,data:{msg_id,seq,ts}}`。
inline std::string send_ack_frame(const std::string& id, uint64_t msg_id, uint64_t seq,
                                  int64_t ts) {
  return nlohmann::json{{"v", 1},
                        {"type", "ack"},
                        {"id", id},
                        {"data", {{"msg_id", std::to_string(msg_id)}, {"seq", seq}, {"ts", ts}}}}
      .dump();
}

/// 鉴权成功帧。
inline std::string auth_ok_frame(uint64_t uid, int64_t server_time) {
  return nlohmann::json{
      {"v", 1},
      {"type", "auth_ok"},
      {"data", {{"uid", uid}, {"server_time", server_time}, {"heartbeat_sec", 25}}}}
      .dump();
}

/// 心跳应答。
inline std::string pong_frame(int64_t server_time) {
  return nlohmann::json{{"v", 1}, {"type", "pong"}, {"data", {{"server_time", server_time}}}}.dump();
}

/// 下行已读回执:对端读到 `seq`。
inline std::string read_frame(const std::string& peer, uint64_t seq) {
  return nlohmann::json{{"v", 1}, {"type", "read"}, {"data", {{"peer", peer}, {"seq", seq}}}}.dump();
}

/// 撤回广播:双方各收一帧,`peer` 是收帧者的对端(即撤回者)。
inline std::string revoked_frame(uint64_t msg_id, uint64_t seq, const std::string& peer,
                                 int64_t ts) {
  return nlohmann::json{{"v", 1},
                        {"type", "revoked"},
                        {"data",
                         {{"msg_id", std::to_string(msg_id)}, {"seq", seq}, {"peer", peer}, {"ts", ts}}}}
      .dump();
}

/// 被顶下线通知(随后服务端以 4001 关闭连接)。
inline std::string kicked_frame(const std::string& reason) {
  return nlohmann::json{{"v", 1}, {"type", "kicked"}, {"data", {{"reason", reason}}}}.dump();
}
