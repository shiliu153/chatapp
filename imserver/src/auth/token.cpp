#include "auth/token.h"

#include <openssl/crypto.h>
#include <openssl/evp.h>
#include <openssl/hmac.h>

#include <array>
#include <cctype>
#include <random>
#include <stdexcept>
#include <vector>

#include <nlohmann/json.hpp>

namespace {

std::string base64url_encode(const std::string& input) {
  std::string encoded;
  encoded.resize(4 * ((input.size() + 2) / 3) + 1);
  const int length = EVP_EncodeBlock(
      reinterpret_cast<unsigned char*>(encoded.data()),
      reinterpret_cast<const unsigned char*>(input.data()),
      static_cast<int>(input.size()));
  encoded.resize(static_cast<std::size_t>(length));
  for (char& ch : encoded) {
    if (ch == '+') {
      ch = '-';
    } else if (ch == '/') {
      ch = '_';
    }
  }
  while (!encoded.empty() && encoded.back() == '=') {
    encoded.pop_back();
  }
  return encoded;
}

std::string base64url_decode(const std::string& input) {
  std::string padded = input;
  for (char& ch : padded) {
    if (ch == '-') {
      ch = '+';
    } else if (ch == '_') {
      ch = '/';
    }
  }
  while (padded.size() % 4 != 0) {
    padded.push_back('=');
  }
  std::string decoded;
  decoded.resize(3 * (padded.size() / 4) + 1);
  const int length = EVP_DecodeBlock(
      reinterpret_cast<unsigned char*>(decoded.data()),
      reinterpret_cast<const unsigned char*>(padded.data()),
      static_cast<int>(padded.size()));
  if (length < 0) {
    throw std::runtime_error("invalid base64url");
  }
  std::size_t padding = 0;
  for (auto it = padded.rbegin(); it != padded.rend() && *it == '='; ++it) {
    ++padding;
  }
  decoded.resize(static_cast<std::size_t>(length) - padding);
  return decoded;
}

std::string sign(std::string_view secret, std::string_view data) {
  std::array<unsigned char, EVP_MAX_MD_SIZE> digest{};
  unsigned int length = 0;
  if (HMAC(EVP_sha256(), secret.data(), static_cast<int>(secret.size()),
           reinterpret_cast<const unsigned char*>(data.data()), data.size(),
           digest.data(), &length) == nullptr) {
    throw std::runtime_error("hmac failed");
  }
  return base64url_encode(std::string(reinterpret_cast<const char*>(digest.data()), length));
}

std::string random_jti() {
  std::random_device device;
  std::mt19937_64 engine(device());
  const auto value = engine();
  static constexpr char kHex[] = "0123456789abcdef";
  std::string out(16, '0');
  for (int i = 15; i >= 0; --i) {
    out[static_cast<std::size_t>(i)] = kHex[value >> ((15 - i) * 4) & 0xF];
  }
  return out;
}

std::vector<std::string_view> split_dots(std::string_view token) {
  std::vector<std::string_view> parts;
  std::size_t start = 0;
  while (true) {
    const auto dot = token.find('.', start);
    parts.push_back(token.substr(start, dot == std::string_view::npos ? std::string_view::npos
                                                                    : dot - start));
    if (dot == std::string_view::npos) {
      break;
    }
    start = dot + 1;
  }
  return parts;
}

}  // namespace

std::string mint_token(uint64_t uid, std::string_view secret, int64_t now_ms,
                       int64_t ttl_seconds) {
  const int64_t now_s = now_ms / 1000;
  nlohmann::json header = {{"alg", "HS256"}, {"typ", "JWT"}};
  nlohmann::json payload = {{"sub", "u" + std::to_string(uid)},
                            {"uid", uid},
                            {"iat", now_s},
                            {"exp", now_s + ttl_seconds},
                            {"jti", random_jti()}};
  const auto header_part = base64url_encode(header.dump());
  const auto payload_part = base64url_encode(payload.dump());
  const auto signing_input = header_part + "." + payload_part;
  return signing_input + "." + sign(secret, signing_input);
}

std::optional<TokenClaims> verify_token(std::string_view token,
                                        std::string_view secret, int64_t now_ms) {
  const auto parts = split_dots(token);
  if (parts.size() != 3 || parts[0].empty() || parts[1].empty() || parts[2].empty()) {
    return std::nullopt;
  }
  try {
    const auto header = nlohmann::json::parse(base64url_decode(std::string(parts[0])));
    if (header.value("alg", "") != "HS256") {
      return std::nullopt;
    }

    const std::string signing_input =
        std::string(parts[0]) + "." + std::string(parts[1]);
    const auto expected = sign(secret, signing_input);
    const auto actual = std::string(parts[2]);
    if (expected.size() != actual.size() ||
        CRYPTO_memcmp(expected.data(), actual.data(), expected.size()) != 0) {
      return std::nullopt;
    }

    const auto payload = nlohmann::json::parse(base64url_decode(std::string(parts[1])));
    TokenClaims claims;
    claims.uid = payload.at("uid").get<uint64_t>();
    claims.sub = payload.at("sub").get<std::string>();
    claims.iat = payload.at("iat").get<int64_t>();
    claims.exp = payload.at("exp").get<int64_t>();
    claims.jti = payload.value("jti", "");
    claims.sv = payload.value("sv", 0);

    const int64_t now_s = now_ms / 1000;
    if (claims.exp <= now_s) {
      return std::nullopt;
    }
    if (claims.iat > now_s + 60) {
      return std::nullopt;
    }
    if (claims.sub != "u" + std::to_string(claims.uid)) {
      return std::nullopt;
    }
    return claims;
  } catch (const std::exception&) {
    return std::nullopt;
  }
}

bool session_version_matches(int64_t token_sv, const std::optional<int64_t>& stored) {
  // sv=0 是 2026-10-28 之前签发的旧 token(过渡期最多 24h),放行;
  // 其余必须与库里的当前版本完全一致 —— 不一致说明账号已在别处登录。
  if (token_sv == 0) {
    return true;
  }
  return stored.has_value() && *stored == token_sv;
}
