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
* 文件名称          src/store/models.h
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
#include <cstdint>
#include <optional>
#include <string>

// 简介 im_user 表的一行投影，只有 user_id / 昵称 / 头像三个字段
// 简介 会话列表的对端信息与消息下行帧的发送者信息都取自它
// 简介 查不到的行不会出现在结果里，调用方拿到的必是已存在账号
struct UserRow {
  uint64_t id = 0;
  std::string nickname;
  std::string avatar;
};

// 简介 im_conversation 表的一行，代表两人之间的唯一会话
// 简介 写入前统一经 ordered() 规范化成 user_a 小于 user_b，同一对账号只有一行，由 uk_pair 唯一键保证
// 简介 last_seq 是会话内已分配的最大序号，发消息时用它加一得到新 seq
struct ConversationRow {
  uint64_t id = 0;
  uint64_t user_a = 0;
  uint64_t user_b = 0;
  uint64_t last_seq = 0;
  uint64_t last_msg_id = 0;
  int64_t last_msg_at = 0;
};

// 简介 im_conversation_state 表的结构镜像，对应「某个人在某个会话」的状态
// 简介 unread 是计数器，read_seq 是我读到哪，deleted 是单方隐藏会话的标志
// 简介 主键 (owner_id, conv_id)，同一会话每人一行；当前没有调用方读取它
struct StateRow {
  uint64_t owner_id = 0;
  uint64_t conv_id = 0;
  uint32_t unread = 0;
  uint64_t read_seq = 0;
  bool deleted = false;
  int64_t updated_at = 0;
};

// 简介 im_message 表的一行，是会话里的一条消息
// 简介 seq 在会话内连续递增，from_id 与 client_msg_id 组成唯一键用于发送幂等
// 简介 可空列读出来是 std::optional：revoked_at 是撤回时刻，ref_msg_id 与 ref_snapshot 是引用
struct MessageRow {
  uint64_t msg_id = 0;
  uint64_t conv_id = 0;
  uint64_t seq = 0;
  uint64_t from_id = 0;
  uint64_t to_id = 0;
  int kind = 1;
  std::string body;
  std::string client_msg_id;
  int64_t created_at = 0;
  std::optional<int64_t> revoked_at;
  /// 引用的原消息 id(批次 L-2)。没有引用时为空 —— 这正是「`ref` 键只在有引用时出现」的源头。
  std::optional<uint64_t> ref_msg_id;
  /// **服务端生成的**引用快照(JSON 文本,字段同下行 `ref` 对象)。
  ///
  /// 为什么存快照而不是每次回查:历史分页意味着被引用消息常常不在当前页里,
  /// 只存 id 会让客户端大量显示「原消息不可见」。快照只由服务端生成,
  /// 客户端传上来的一律丢弃(见 `MessageService::send`)。
  std::optional<std::string> ref_snapshot;
};

// 简介 会话列表的一项，由状态行、对端资料与最后一条消息拼成
// 简介 last 是会话全局的最后一条消息，可能已被我隐藏，由 MessageRepo::apply_visible_last 事后修补
// 简介 peer_read_seq 站「我」的视角看对端读到哪，与 unread 是两条独立链路
struct ConversationView {
  UserRow peer;
  bool has_last = false;
  MessageRow last;
  uint32_t unread = 0;
  uint64_t last_seq = 0;
  int64_t updated_at = 0;
  /// **对端**读到哪(站在「我」的视角)。0 = 对端从没读过,不是错误。
  ///
  /// `unread` 是「我」没读的条数,`peer_read_seq` 是「对端」读到哪 —— 两者是
  /// 两条独立链路,别混。客户端用它把 `seq <= peer_read_seq` 的**我方**消息标成已读。
  uint64_t peer_read_seq = 0;
  /// 置顶时刻(毫秒时间戳)。0 = 未置顶 —— 存时间而不是 bool,是因为列表要按
  /// 「置顶时间倒序」排(批次 N)。
  int64_t pinned_at = 0;
  /// 免打扰。**只影响客户端表现**(静音图标 + 未读只显示灰点),服务端不抑制任何东西。
  bool muted = false;
};

// 简介 单个会话的置顶与免打扰标志位，按 owner 维度存在 im_conversation_state
// 简介 pinned 由 pinned_at 是否大于 0 推出，muted 由 muted 列推出，两者都是单方设置
// 简介 只影响列表排序与客户端表现，不改变消息投递
/// 一个会话的置顶 / 免打扰标志位(批次 N,owner 维度,存在 `im_conversation_state`)。
struct ConversationFlags {
  bool pinned = false;
  bool muted = false;
};

// 简介 撤回成功后的结果，携带被撤回消息的身份信息
// 简介 msg_id 与 seq 供客户端定位本地那条消息，ts 是撤回时刻的毫秒时间戳
// 简介 只有本人发的、120 秒内、未撤回过的消息才会产出这个结构
struct RevokeResult {
  uint64_t msg_id = 0;
  uint64_t seq = 0;
  uint64_t from_id = 0;
  uint64_t to_id = 0;
  int64_t ts = 0;
};
