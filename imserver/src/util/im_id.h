#pragma once
#include <cstdint>
#include <string>

/// 账号 id → IM id(`u12`);0 是系统通知,用固定串(与 Django 侧常量是跨栈契约)。
///
/// 为什么收在一个头里:下行 `message` 帧、`/im/api/*` 的响应、引用快照
/// (`ref.from`)三处都要这个映射。三处各写一份,迟早出现「一边 `u0`、
/// 一边 `system_notice`」这种对不上的情况 —— 老代码里就有一份是 `"u"+id`。
///
/// Args:
///   uid: 账号 id;0 表示系统通知。
///
/// Returns:
///   `u<uid>`,或系统通知的 `system_notice`。
inline std::string peer_id(uint64_t uid) {
  return uid == 0 ? "system_notice" : "u" + std::to_string(uid);
}
