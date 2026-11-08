#pragma once
#include <cstdint>
#include <optional>
#include <string>
#include <string_view>

/// 端类型:`app`(手机)或 `web`(网页端)。多端在线后会话版本按端存放。
inline constexpr std::string_view kClientApp = "app";
inline constexpr std::string_view kClientWeb = "web";

struct TokenClaims {
  uint64_t uid = 0;
  std::string sub;
  int64_t iat = 0;
  int64_t exp = 0;
  std::string jti;
  int64_t sv = 0;   // 会话版本;0 = 旧版 token(过渡期放行)
  std::string ct = std::string(kClientApp);  // 端类型;缺 claim 的旧 token 按 app 兜底
};

/// 签一个 IM token。
///
/// Args:
///   uid: 账号 id。
///   secret: HS256 共享密钥。
///   now_ms: 当前毫秒时间戳。
///   ttl_seconds: 有效期(秒)。
///   ct: 端类型 `app` / `web`;缺省 `app`,与 Django 侧 `mint_im_token` 同口径。
///
/// Returns:
///   JWT 字符串(payload 含 `sv` 之外的 `ct` claim)。
std::string mint_token(uint64_t uid, std::string_view secret, int64_t now_ms,
                       int64_t ttl_seconds, std::string_view ct = kClientApp);

/// 把端类型归一化到已知取值。
///
/// 只认 `web`,其余(缺失、空、未知取值)一律 `app` —— 老 token 不带 `ct`,
/// 必须继续按 app 放行;未知取值也不该凭空造出新的端会话行。
///
/// Args:
///   value: token 里 `ct` claim 的原始值。
///
/// Returns:
///   `"web"` 或 `"app"`。
std::string normalize_client_type(std::string_view value);

std::optional<TokenClaims> verify_token(std::string_view token,
                                        std::string_view secret, int64_t now_ms);

/// 判断 token 里的会话版本是否仍然有效(H3)。
///
/// WS 与 HTTP 两个入口共用这一份判定,避免只在一个入口校验导致「踢下线不彻底」。
///
/// Args:
///   token_sv: token 里的 `sv`;0 表示过渡期旧 token,放行。
///   stored: 该端在 `im_device_session.session_version` 的当前值;没有该端的行时为空。
///
/// Returns:
///   允许本次请求返回 true。
bool session_version_matches(int64_t token_sv, const std::optional<int64_t>& stored);
