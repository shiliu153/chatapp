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
* 文件名称          tests/token_test.cpp
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证签发与验签往返
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R MintThenVerify
// 备注信息     断言 uid sub 与 exp 字段 sub 为 u 加账号 有效期按秒算
//-------------------------------------------------------------------------------------------------------------------
TEST(TokenTest, MintThenVerify) {
  const auto token = mint_token(9, kSecret, kNow, 3600);
  const auto claims = verify_token(token, kSecret, kNow + 1000);
  ASSERT_TRUE(claims.has_value());
  EXPECT_EQ(claims->uid, 9u);
  EXPECT_EQ(claims->sub, "u9");
  EXPECT_EQ(claims->exp, kNow / 1000 + 3600);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证过期令牌被拒
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R RejectsExpired
// 备注信息     60 秒有效期 61 秒后验签返回 nullopt
//-------------------------------------------------------------------------------------------------------------------
TEST(TokenTest, RejectsExpired) {
  const auto token = mint_token(9, kSecret, kNow, 60);
  EXPECT_FALSE(verify_token(token, kSecret, kNow + 61000).has_value());
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证载荷被篡改即拒签
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R RejectsTamperedPayload
// 备注信息     改掉第一段载荷的一个字符 签名校验失败返回 nullopt
//-------------------------------------------------------------------------------------------------------------------
TEST(TokenTest, RejectsTamperedPayload) {
  auto token = mint_token(9, kSecret, kNow, 3600);
  const auto dot = token.find('.');
  ASSERT_NE(dot, std::string::npos);
  token[dot + 2] = token[dot + 2] == 'A' ? 'B' : 'A';
  EXPECT_FALSE(verify_token(token, kSecret, kNow).has_value());
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证密钥不符被拒
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R RejectsWrongSecret
// 备注信息     换一把同长度密钥验签 断言返回 nullopt
//-------------------------------------------------------------------------------------------------------------------
TEST(TokenTest, RejectsWrongSecret) {
  const auto token = mint_token(9, kSecret, kNow, 3600);
  EXPECT_FALSE(verify_token(token, "ffffffffffffffffffffffffffffffff", kNow).has_value());
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证 sub 与 uid 不一致被拒
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R RejectsSubUidMismatch
// 备注信息     用正确密钥伪造 sub=u10 而 uid=9 的令牌 断言验签失败 防止拿 sub 冒充别人
//-------------------------------------------------------------------------------------------------------------------
TEST(TokenTest, RejectsSubUidMismatch) {
  const auto forged = forge_token_with_sub("u10", 9);
  EXPECT_FALSE(verify_token(forged, kSecret, kNow).has_value());
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证解析会话版本 sv
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R ParsesSessionVersion
// 备注信息     payload 带 sv=7 断言 claims 的 sv 为 7 多端互顶的比对依据
//-------------------------------------------------------------------------------------------------------------------
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证到期边界即失效
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R RejectsExpiryAtBoundary
// 备注信息     exp 等于当前秒时验签失败 边界不宽限
//-------------------------------------------------------------------------------------------------------------------
TEST(TokenTest, RejectsExpiryAtBoundary) {
  nlohmann::json header = {{"alg", "HS256"}, {"typ", "JWT"}};
  nlohmann::json payload = {{"sub", "u9"}, {"uid", 9}, {"iat", kNow / 1000},
                            {"exp", kNow / 1000}, {"jti", "edge"}};
  const auto signing_input = b64url(header.dump()) + "." + b64url(payload.dump());
  const auto token = signing_input + "." + hmac_b64(signing_input);
  EXPECT_FALSE(verify_token(token, kSecret, kNow).has_value());
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证签发携带端类型 ct
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R MintCarriesClientType
// 备注信息     签 web 端令牌 验签后 ct 必须是 web 多端在线的判端依据
//-------------------------------------------------------------------------------------------------------------------
TEST(TokenTest, MintCarriesClientType) {
  // 多端在线(K-2):签 web 端令牌,验签后 ct 必须是 web
  const auto token = mint_token(9, kSecret, kNow, 3600, "web");
  const auto claims = verify_token(token, kSecret, kNow);
  ASSERT_TRUE(claims.has_value());
  EXPECT_EQ(claims->ct, "web");
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证端类型缺省为 app
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R ClientTypeDefaultsToApp
// 备注信息     不带 ct 的签发与线上老令牌都按 app 兜底 否则升级即集体掉线
//-------------------------------------------------------------------------------------------------------------------
TEST(TokenTest, ClientTypeDefaultsToApp) {
  // 不带 ct 的签发(以及线上 1.0.10 的老 token)必须按 app 兜底,否则升级即集体掉线
  const auto token = mint_token(9, kSecret, kNow, 3600);
  const auto claims = verify_token(token, kSecret, kNow);
  ASSERT_TRUE(claims.has_value());
  EXPECT_EQ(claims->ct, "app");
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证未知端类型归一到 app
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R UnknownClientTypeFallsBackToApp
// 备注信息     payload 带 ct=tablet 断言落到 app 同时校验 normalize_client_type 对空串与 WEB 都归 app
//-------------------------------------------------------------------------------------------------------------------
TEST(TokenTest, UnknownClientTypeFallsBackToApp) {
  // 未知取值不该凭空造出新的端会话行
  nlohmann::json header = {{"alg", "HS256"}, {"typ", "JWT"}};
  nlohmann::json payload = {{"sub", "u9"}, {"uid", 9}, {"iat", kNow / 1000},
                            {"exp", kNow / 1000 + 3600}, {"jti", "ct"}, {"ct", "tablet"}};
  const auto signing_input = b64url(header.dump()) + "." + b64url(payload.dump());
  const auto token = signing_input + "." + hmac_b64(signing_input);
  const auto claims = verify_token(token, kSecret, kNow);
  ASSERT_TRUE(claims.has_value());
  EXPECT_EQ(claims->ct, "app");
  EXPECT_EQ(normalize_client_type(""), "app");
  EXPECT_EQ(normalize_client_type("WEB"), "app");
  EXPECT_EQ(normalize_client_type("web"), "web");
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证会话版本比对语义
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R SessionVersionMatchesStored
// 备注信息     相等通过 不相等拒绝 库内无版本时拒绝 带 sv 的令牌必须有对应端会话行
//-------------------------------------------------------------------------------------------------------------------
TEST(TokenTest, SessionVersionMatchesStored) {
  EXPECT_TRUE(session_version_matches(7, std::optional<int64_t>(7)));
  EXPECT_FALSE(session_version_matches(7, std::optional<int64_t>(6)));
  EXPECT_FALSE(session_version_matches(7, std::nullopt));
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证旧令牌无版本时放行
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R LegacyTokenWithoutSessionVersionPasses
// 备注信息     sv=0 视为 2026-10-28 之前签发的旧令牌 过渡期放行 最多等 24 小时自然过期
//-------------------------------------------------------------------------------------------------------------------
TEST(TokenTest, LegacyTokenWithoutSessionVersionPasses) {
  // sv=0 是 2026-10-28 之前签发的旧 token,过渡期放行(最多 24h 自然过期)
  EXPECT_TRUE(session_version_matches(0, std::nullopt));
  EXPECT_TRUE(session_version_matches(0, std::optional<int64_t>(3)));
}
