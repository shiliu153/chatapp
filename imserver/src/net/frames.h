#pragma once
#include <nlohmann/json.hpp>

#include <exception>
#include <optional>
#include <string>

#include "service/message_service.h"
#include "util/im_id.h"
#include "util/media_sign.h"
#include "util/message_kind.h"

/// **一条消息的唯一序列化入口**。
///
/// 为什么只能有一份:下行 `message` 帧(WS)与 `/im/api/messages`、会话列表的
/// `last_message`、搜索结果(HTTP)都表示「同一条消息」。以前两边各写一份构造函数,
/// 结果引用(`ref`)这种新字段只要漏改一处,就有一端看不到 —— 这正是批次 L-2
/// 踩的坑。现在 HTTP 侧与 WS 侧都调这里。
///
/// Args:
///   row: 库里的消息行(含 kind / body / revoked_at / ref_snapshot)。
///   from_profile: 发送者画像;为空时不下发 `from_profile`(系统通知就是这种)。
///   signer: 媒体签名器,图片 / 语音 URL 在这里**读时**现签。
///
/// Returns:
///   消息的 `data` 对象(`msg_id` / `seq` / `from` / `to` / `kind` / `ts` / `revoked` …)。
inline nlohmann::json message_json(const MessageRow& row,
                                   const std::optional<UserRow>& from_profile,
                                   const MediaSigner& signer) {
  nlohmann::json data = {{"msg_id", std::to_string(row.msg_id)},
                         {"seq", row.seq},
                         {"from", peer_id(row.from_id)},
                         {"to", peer_id(row.to_id)},
                         {"ts", row.created_at},
                         {"revoked", row.revoked_at.has_value()}};
  if (row.revoked_at.has_value()) {
    data["kind"] = "text";
  } else {
    const auto body = nlohmann::json::parse(row.body);
    if (row.kind == 3) {
      data["kind"] = "image";
      data["image"] = body.value("image", nlohmann::json::object());
      signer.sign_image(data["image"]);
    } else if (row.kind == 4) {
      data["kind"] = "voice";
      data["voice"] = body.value("voice", nlohmann::json::object());
      signer.sign_media(data["voice"], {"url"});
    } else if (row.kind == 2) {
      data["kind"] = "custom";
      data["custom"] = body;
    } else {
      data["kind"] = "text";
      data["text"] = body.value("text", "");
    }
  }
  // 引用(批次 L-2):**只在有引用时出现这个键** —— 老客户端不解析新键也不会崩。
  // 快照是服务端生成好存下来的,这里原样透出,不再回查被引用消息(那正是快照的意义)。
  if (row.ref_snapshot.has_value()) {
    try {
      data["ref"] = nlohmann::json::parse(*row.ref_snapshot);
    } catch (const std::exception&) {
      // 快照坏了宁可少一个引用块,也不能让整条消息读不出来。
    }
  }
  if (from_profile.has_value()) {
    data["from_profile"] = {{"nickname", from_profile->nickname},
                            {"avatar", from_profile->avatar}};
  }
  return data;
}

// 下行 `message` 帧:与 `/im/api/messages` 用同一个 `message_json`,只多一层信封。
// 图片 URL 在**读时**签名(库里存的是去掉 query 的规范 URL)。
inline std::string build_message_frame(const MessageRow& row,
                                       const std::optional<UserRow>& from_profile,
                                       const MediaSigner& signer) {
  return nlohmann::json{{"v", 1},
                        {"type", "message"},
                        {"data", message_json(row, from_profile, signer)}}
      .dump();
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

/// 跨端已读:告诉**我自己的其他设备**「我在这一端把与 `peer` 的会话读到了 seq」。
///
/// 为什么不能复用下行 `read` 帧:那一帧的语义是「**对端**读到 seq」,发给自己的
/// 另一台设备会被读成「对方已读」—— 表现为对方的红点莫名消失、自己的未读不动,
/// 是假已读。多端在线(K-3)起两个帧必须同时发:`read` 只给对端,`self_read`
/// 只给自己的其他端(不含发起的这条连接)。
///
/// Args:
///   peer: 会话对端的 id 串(`u12`)。
///   seq: 回读实库后的真实已读位置(`GREATEST` 之后的值)。
inline std::string self_read_frame(const std::string& peer, uint64_t seq) {
  return nlohmann::json{{"v", 1},
                        {"type", "self_read"},
                        {"data", {{"peer", peer}, {"seq", seq}}}}
      .dump();
}

/// 跨端删除:告诉**我自己的其他设备**「我在这一端删掉了与 `peer` 的会话」。
///
/// 只发给本人的其他端,**绝不发给对方**:删除会话是单方行为,对方不该知道,
/// 更不该因此丢掉自己那边的记录。收帧端把该会话从列表移除即可,不必再拉全量。
///
/// Args:
///   peer: 被删除会话的对端 id 串(`u12`)。
inline std::string conversation_deleted_frame(const std::string& peer) {
  return nlohmann::json{{"v", 1}, {"type", "conversation_deleted"}, {"data", {{"peer", peer}}}}
      .dump();
}

/// 输入中状态(批次 L-1):只发给**对端**,不落库、不补拉。
///
/// 为什么没有 id、也不 ack:它是「可丢」信号 —— 丢一帧最多是对方晚一点看到
/// 「正在输入」,而补发 / 重试只会放大流量。同理,服务端在任何异常路径
/// (限流超限 / 未配对 / 目标不存在)都**静默丢弃**,绝不回错误帧。
///
/// Args:
///   peer: **收帧者**的对端 id 串(`u12`),即正在打字的人。
inline std::string typing_frame(const std::string& peer) {
  return nlohmann::json{{"v", 1}, {"type", "typing"}, {"data", {{"peer", peer}}}}.dump();
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
