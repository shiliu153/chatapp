#include <gtest/gtest.h>
#include <openssl/evp.h>
#include <openssl/hmac.h>

#include <array>
#include <string>

#include <nlohmann/json.hpp>

#include "auth/token.h"

namespace {

constexpr int64_t kNow = 1760000000000;
constexpr const char* kSecret = "0123456789abcdef0123456789abcdef";

std::string b64url(const std::string& input) {
  std::string out;
  out.resize(4 * ((input.size() + 2) / 3) + 1);
  const int length = EVP_EncodeBlock(
      reinterpret_cast<unsigned char*>(out.data()),
      reinterpret_cast<const unsigned char*>(input.data()),
      static_cast<int>(input.size()));
  out.resize(static_cast<std::size_t>(length));
  for (char& ch : out) {
    if (ch == '+') {
      ch = '-';
    } else if (ch == '/') {
      ch = '_';
    }
  }
  while (!out.empty() && out.back() == '=') {
    out.pop_back();
  }
  return out;
}

std::string hmac_b64(const std::string& data) {
  std::array<unsigned char, EVP_MAX_MD_SIZE> digest{};
  unsigned int length = 0;
  HMAC(EVP_sha256(), kSecret, static_cast<int>(std::string(kSecret).size()),
       reinterpret_cast<const unsigned char*>(data.data()), data.size(),
       digest.data(), &length);
  return b64url(std::string(reinterpret_cast<const char*>(digest.data()), length));
}

std::string forge_token_with_sub(const std::string& sub, uint64_t uid) {
  nlohmann::json header = {{"alg", "HS256"}, {"typ", "JWT"}};
  nlohmann::json payload = {{"sub", sub}, {"uid", uid}, {"iat", kNow / 1000},
                            {"exp", kNow / 1000 + 3600}, {"jti", "forged"}};
  const auto signing_input = b64url(header.dump()) + "." + b64url(payload.dump());
  return signing_input + "." + hmac_b64(signing_input);
}

}  // namespace

TEST(TokenTest, MintThenVerify) {
  const auto token = mint_token(9, kSecret, kNow, 3600);
  const auto claims = verify_token(token, kSecret, kNow + 1000);
  ASSERT_TRUE(claims.has_value());
  EXPECT_EQ(claims->uid, 9u);
  EXPECT_EQ(claims->sub, "u9");
  EXPECT_EQ(claims->exp, kNow / 1000 + 3600);
}

TEST(TokenTest, RejectsExpired) {
  const auto token = mint_token(9, kSecret, kNow, 60);
  EXPECT_FALSE(verify_token(token, kSecret, kNow + 61000).has_value());
}

TEST(TokenTest, RejectsTamperedPayload) {
  auto token = mint_token(9, kSecret, kNow, 3600);
  const auto dot = token.find('.');
  ASSERT_NE(dot, std::string::npos);
  token[dot + 2] = token[dot + 2] == 'A' ? 'B' : 'A';
  EXPECT_FALSE(verify_token(token, kSecret, kNow).has_value());
}

TEST(TokenTest, RejectsWrongSecret) {
  const auto token = mint_token(9, kSecret, kNow, 3600);
  EXPECT_FALSE(verify_token(token, "ffffffffffffffffffffffffffffffff", kNow).has_value());
}

TEST(TokenTest, RejectsSubUidMismatch) {
  const auto forged = forge_token_with_sub("u10", 9);
  EXPECT_FALSE(verify_token(forged, kSecret, kNow).has_value());
}

TEST(TokenTest, ParsesSessionVersion) {
  nlohmann::json header = {{"alg", "HS256"}, {"typ", "JWT"}};
  nlohmann::json payload = {{"sub", "u9"}, {"uid", 9}, {"iat", kNow / 1000},
                            {"exp", kNow / 1000 + 3600}, {"jti", "sv"}, {"sv", 7}};
  const auto signing_input = b64url(header.dump()) + "." + b64url(payload.dump());
  const auto token = signing_input + "." + hmac_b64(signing_input);
  const auto claims = verify_token(token, kSecret, kNow);
  ASSERT_TRUE(claims.has_value());
  EXPECT_EQ(claims->sv, 7);
}

TEST(TokenTest, RejectsExpiryAtBoundary) {
  nlohmann::json header = {{"alg", "HS256"}, {"typ", "JWT"}};
  nlohmann::json payload = {{"sub", "u9"}, {"uid", 9}, {"iat", kNow / 1000},
                            {"exp", kNow / 1000}, {"jti", "edge"}};
  const auto signing_input = b64url(header.dump()) + "." + b64url(payload.dump());
  const auto token = signing_input + "." + hmac_b64(signing_input);
  EXPECT_FALSE(verify_token(token, kSecret, kNow).has_value());
}

TEST(TokenTest, SessionVersionMatchesStored) {
  EXPECT_TRUE(session_version_matches(7, std::optional<int64_t>(7)));
  EXPECT_FALSE(session_version_matches(7, std::optional<int64_t>(6)));
  EXPECT_FALSE(session_version_matches(7, std::nullopt));
}

TEST(TokenTest, LegacyTokenWithoutSessionVersionPasses) {
  // sv=0 是 2026-10-28 之前签发的旧 token,过渡期放行(最多 24h 自然过期)
  EXPECT_TRUE(session_version_matches(0, std::nullopt));
  EXPECT_TRUE(session_version_matches(0, std::optional<int64_t>(3)));
}
