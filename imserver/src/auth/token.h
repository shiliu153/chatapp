#pragma once
#include <cstdint>
#include <optional>
#include <string>
#include <string_view>

struct TokenClaims {
  uint64_t uid = 0;
  std::string sub;
  int64_t iat = 0;
  int64_t exp = 0;
  std::string jti;
  int64_t sv = 0;   // 会话版本;0 = 旧版 token(过渡期放行)
};

std::string mint_token(uint64_t uid, std::string_view secret, int64_t now_ms,
                       int64_t ttl_seconds);

std::optional<TokenClaims> verify_token(std::string_view token,
                                        std::string_view secret, int64_t now_ms);

/// 判断 token 里的会话版本是否仍然有效(H3)。
///
/// WS 与 HTTP 两个入口共用这一份判定,避免只在一个入口校验导致「踢下线不彻底」。
///
/// Args:
///   token_sv: token 里的 `sv`;0 表示过渡期旧 token,放行。
///   stored: `im_user.session_version`;用户不存在时为空。
///
/// Returns:
///   允许本次请求返回 true。
bool session_version_matches(int64_t token_sv, const std::optional<int64_t>& stored);
