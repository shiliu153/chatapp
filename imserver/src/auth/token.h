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
};

std::string mint_token(uint64_t uid, std::string_view secret, int64_t now_ms,
                       int64_t ttl_seconds);

std::optional<TokenClaims> verify_token(std::string_view token,
                                        std::string_view secret, int64_t now_ms);
