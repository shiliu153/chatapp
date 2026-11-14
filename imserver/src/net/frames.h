/*********************************************************************************************************************
* chat_app 自建 IM 服务端（imserver）是本项目唯一的 IM 后端，C++20 实现，对外提供 WebSocket :9100 与 HTTP :9101
* Copyright (c) 2026 shiliu153
*
* 本文件是 chat_app 自建 IM 服务端的一部分
*
* 额外注明：
* 本文件使用 MIT 开源许可证协议 许可申明英文版见仓库根目录 LICENSE 文件
* 欢迎各位使用并传播本程序 但修改内容时必须保留作者的版权声明（即本声明）
* 本文件是三端(App / Web / imserver)唯一的线上帧契约源 改任何帧格式必须三端同改
*
* 文件名称          src/net/frames.h
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
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     序列化消息行 产出帧与 HTTP 共用的 data 对象
// 参数说明     row              库里的消息行 含 kind / body / revoked_at / ref_snapshot
//              from_profile     发送者画像 为空时不下发 from_profile 键
//              signer           媒体签名器 图片与语音 URL 在这里读时现签
// 返回参数     nlohmann::json     消息 data 对象 含 msg_id / seq / from / to / kind / ts / revoked
// 使用示例     const auto data = message_json(row, users.get(row.from_id), signer);
// 备注信息     WS 下行 message 帧与 /im/api/messages 必须共用这一份 两边各写一份就会漏字段
//              已撤回消息只把 kind 置成 text 不下发原 body 引用快照解析失败时静默丢弃 ref
//-------------------------------------------------------------------------------------------------------------------
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
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     构造下行 message 帧 包一层 v/type/data 信封
// 参数说明     row              库里的消息行
//              from_profile     发送者画像 为空时不下发 from_profile 键
//              signer           媒体签名器 图片与语音 URL 读时现签
// 返回参数     std::string      可直接下发的 JSON 文本
// 使用示例     registry_.send_to(uid, build_message_frame(row, profile, signer));
// 备注信息     数据体转调 message_json 库里存的是去掉 query 的规范 URL 签名只在读时做
//-------------------------------------------------------------------------------------------------------------------
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
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     构造 error 下行帧 携带业务码与中文文案
// 参数说明     code             业务错误码 如 40101 / 40302 / 42201
//              message          给客户端看的中文提示
// 返回参数     std::string      JSON 文本 形状为 {v,type:error,data:{code,message}}
// 使用示例     error_frame(40302, "尚未配对");
// 备注信息     只有需要让客户端感知失败时才回本帧 typing 这类可丢帧在异常路径上静默丢弃 不回错误
//-------------------------------------------------------------------------------------------------------------------
inline std::string error_frame(int code, const std::string& message) {
  return nlohmann::json{
      {"v", 1}, {"type", "error"}, {"data", {{"code", code}, {"message", message}}}}
      .dump();
}

/// 通用 ack(read/revoke/conversation_delete 用):`{v,type:ack,id,data:{ok}}`。
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     构造通用 ack 帧 回带请求 id 与处理结果
// 参数说明     id               客户端请求 id 原样回带
//              ok               是否处理成功
// 返回参数     std::string      JSON 文本 形状为 {v,type:ack,id,data:{ok}}
// 使用示例     ack_frame(id, true);
// 备注信息     用于 read / revoke / conversation_delete send 的 ack 形状不同 见 send_ack_frame
//-------------------------------------------------------------------------------------------------------------------
inline std::string ack_frame(const std::string& id, bool ok) {
  return nlohmann::json{{"v", 1}, {"type", "ack"}, {"id", id}, {"data", {{"ok", ok}}}}.dump();
}

/// send 的 ack(形状与通用 ack 不同):`{v,type:ack,id,data:{msg_id,seq,ts}}`。
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     构造 send 专用 ack 帧 回带落库结果
// 参数说明     id               客户端请求 id 原样回带
//              msg_id           落库后的消息 id 以字符串下发
//              seq              该消息在会话内的序号
//              ts               服务端落库时间 秒级时间戳
// 返回参数     std::string      JSON 文本 形状为 {v,type:ack,id,data:{msg_id,seq,ts}}
// 使用示例     send_ack_frame(id, msg_id, seq, ts);
// 备注信息     形状与通用 ack 不同 客户端要按 type 与字段区分 msg_id 用字符串与消息体保持一致
//-------------------------------------------------------------------------------------------------------------------
inline std::string send_ack_frame(const std::string& id, uint64_t msg_id, uint64_t seq,
                                  int64_t ts) {
  return nlohmann::json{{"v", 1},
                        {"type", "ack"},
                        {"id", id},
                        {"data", {{"msg_id", std::to_string(msg_id)}, {"seq", seq}, {"ts", ts}}}}
      .dump();
}

/// 鉴权成功帧。
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     构造鉴权成功帧 回带账号 id 与心跳间隔
// 参数说明     uid              账号数字 id
//              server_time      服务端当前时间 秒级时间戳
// 返回参数     std::string      JSON 文本 形状为 {v,type:auth_ok,data:{uid,server_time,heartbeat_sec}}
// 使用示例     auth_ok_frame(uid, now_sec);
// 备注信息     heartbeat_sec 固定写 25 客户端按这个间隔发 ping 服务端回 pong 帧
//-------------------------------------------------------------------------------------------------------------------
inline std::string auth_ok_frame(uint64_t uid, int64_t server_time) {
  return nlohmann::json{
      {"v", 1},
      {"type", "auth_ok"},
      {"data", {{"uid", uid}, {"server_time", server_time}, {"heartbeat_sec", 25}}}}
      .dump();
}

/// 心跳应答。
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     构造心跳应答 pong 帧
// 参数说明     server_time      服务端当前时间 秒级时间戳
// 返回参数     std::string      JSON 文本 形状为 {v,type:pong,data:{server_time}}
// 使用示例     pong_frame(now_sec);
// 备注信息     只回时间戳 不带其他字段 客户端靠 heartbeat_sec 决定发 ping 的频率
//-------------------------------------------------------------------------------------------------------------------
inline std::string pong_frame(int64_t server_time) {
  return nlohmann::json{{"v", 1}, {"type", "pong"}, {"data", {{"server_time", server_time}}}}.dump();
}

/// 下行已读回执:对端读到 `seq`。
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     构造下行已读回执帧 告知对端读到哪个序号
// 参数说明     peer             收帧者的对端 id 串 即已读的人
//              seq              对端已读到的会话内序号
// 返回参数     std::string      JSON 文本 形状为 {v,type:read,data:{peer,seq}}
// 使用示例     registry_.send_to(peer, read_frame(peer_id(uid), seq));
// 备注信息     语义是「对端读到 seq」只发给对端 同步自己的其他设备必须用 self_read_frame
//-------------------------------------------------------------------------------------------------------------------
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
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     构造跨端已读帧 同步本人其他设备的已读位置
// 参数说明     peer             会话对端的 id 串 形如 u12
//              seq              回读实库后的真实已读位置
// 返回参数     std::string      JSON 文本 形状为 {v,type:self_read,data:{peer,seq}}
// 使用示例     self_read_frame("u12", seq);
// 备注信息     只发给本人的其他端 不含发起这次已读的连接
//              不能复用下行 read 帧 否则自己的其他设备会把「我已读」读成「对方已读」造成假已读
//-------------------------------------------------------------------------------------------------------------------
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
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     构造跨端删除帧 通知本人其他设备移除会话
// 参数说明     peer             被删除会话的对端 id 串 形如 u12
// 返回参数     std::string      JSON 文本 形状为 {v,type:conversation_deleted,data:{peer}}
// 使用示例     conversation_deleted_frame("u12");
// 备注信息     只发给本人的其他端 绝不发给对方 删除会话是单方行为
//              收帧端把该会话从列表移除即可 不必再拉全量
//-------------------------------------------------------------------------------------------------------------------
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
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     构造输入中帧 只推给对端
// 参数说明     peer             收帧者的对端 id 串 即正在打字的人
// 返回参数     std::string      JSON 文本 形状为 {v,type:typing,data:{peer}}
// 使用示例     typing_frame(peer_id(uid));
// 备注信息     不落库 不补拉 没有 id 也不 ack 属于可丢信号
//              限流超限 未配对 目标不存在时服务端一律静默丢弃 绝不回错误帧
//-------------------------------------------------------------------------------------------------------------------
inline std::string typing_frame(const std::string& peer) {
  return nlohmann::json{{"v", 1}, {"type", "typing"}, {"data", {{"peer", peer}}}}.dump();
}

/// 撤回广播:双方各收一帧,`peer` 是收帧者的对端(即撤回者)。
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     构造撤回广播帧 双方各收一帧
// 参数说明     msg_id           被撤回的消息 id
//              seq              该消息在会话内的序号
//              peer             收帧者的对端 id 串 即发起撤回的人
//              ts               撤回发生时间 秒级时间戳
// 返回参数     std::string      JSON 文本 形状为 {v,type:revoked,data:{msg_id,seq,peer,ts}}
// 使用示例     revoked_frame(msg_id, seq, peer_id(uid), ts);
// 备注信息     peer 是收帧者视角的对端 同一条撤回对双方各构造一帧 msg_id 以字符串下发
//-------------------------------------------------------------------------------------------------------------------
inline std::string revoked_frame(uint64_t msg_id, uint64_t seq, const std::string& peer,
                                 int64_t ts) {
  return nlohmann::json{{"v", 1},
                        {"type", "revoked"},
                        {"data",
                         {{"msg_id", std::to_string(msg_id)}, {"seq", seq}, {"peer", peer}, {"ts", ts}}}}
      .dump();
}

/// 被顶下线通知(随后服务端以 4001 关闭连接)。
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     构造被顶下线通知帧
// 参数说明     reason           下线原因文案 如 multi_device / banned / deleted
// 返回参数     std::string      JSON 文本 形状为 {v,type:kicked,data:{reason}}
// 使用示例     kicked_frame("multi_device");
// 备注信息     发完本帧服务端随即以关闭码 4001 关闭连接 reason 原样取自调用方
//-------------------------------------------------------------------------------------------------------------------
inline std::string kicked_frame(const std::string& reason) {
  return nlohmann::json{{"v", 1}, {"type", "kicked"}, {"data", {{"reason", reason}}}}.dump();
}
