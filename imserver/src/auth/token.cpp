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
* 文件名称          src/auth/token.cpp
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     把原始字节编码成无填充 base64url
// 参数说明     input            待编码字节
// 返回参数     std::string      不含等号的 base64url 文本
// 使用示例     base64url_encode(header.dump());
// 备注信息     基于 EVP_EncodeBlock 再把加号斜杠换成减号下划线 并去掉尾部等号
//-------------------------------------------------------------------------------------------------------------------
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     把 base64url 文本解码成原始字节
// 参数说明     input            无填充的 base64url 文本
// 返回参数     std::string      解码后的字节
// 使用示例     base64url_decode(std::string(parts[1]));
// 备注信息     先补等号到 4 的倍数 再按补的个数裁掉尾部 EVP_DecodeBlock 失败抛 std::runtime_error
//-------------------------------------------------------------------------------------------------------------------
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     计算 HMAC-SHA256 并 base64url 编码
// 参数说明     secret           共享密钥
//              data             待签名的 header.payload 文本
// 返回参数     std::string      JWT 第三段签名
// 使用示例     sign(secret, signing_input);
// 备注信息     输出 base64url 而非十六进制 与 JWT 第三段一致 HMAC 返回空抛 std::runtime_error
//-------------------------------------------------------------------------------------------------------------------
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     生成 16 字符随机 jti
// 参数说明     无
// 返回参数     std::string      小写十六进制串
// 使用示例     std::string jti = random_jti();
// 备注信息     用 std::random_device 播种 mt19937_64 只保证唯一性 不可当密钥材料
//-------------------------------------------------------------------------------------------------------------------
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     按点号切分 token
// 参数说明     token            JWT 文本
// 返回参数     std::vector<std::string_view>     各段视图 保留空段
// 使用示例     auto parts = split_dots(jwt);
// 备注信息     零拷贝 视图指向入参内存 入参生命周期必须覆盖使用期
//-------------------------------------------------------------------------------------------------------------------
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     把端类型归一化到 app 或 web
// 参数说明     value            token 里 ct claim 的原始值
// 返回参数     std::string      仅 web 保留 其余一律 app
// 使用示例     normalize_client_type("web");
// 备注信息     缺省与未知取值都落回 app 老 token 因此继续按 App 放行
//-------------------------------------------------------------------------------------------------------------------
std::string normalize_client_type(std::string_view value) {
  return value == kClientWeb ? std::string(kClientWeb) : std::string(kClientApp);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     签发 IM 用的 HS256 JWT
// 参数说明     uid              账号 id
//              secret           HS256 共享密钥
//              now_ms           当前毫秒时间戳
//              ttl_seconds      有效期秒数
//              ct               端类型 app 或 web
// 返回参数     std::string      三段式 JWT 文本
// 使用示例     std::string jwt = mint_token(42, secret, now_ms, 86400, "web");
// 备注信息     毫秒换算成秒 exp 等于 iat 加 ttl_seconds sub 固定为 u 加 uid ct 先归一化
//-------------------------------------------------------------------------------------------------------------------
std::string mint_token(uint64_t uid, std::string_view secret, int64_t now_ms,
                       int64_t ttl_seconds, std::string_view ct) {
  const int64_t now_s = now_ms / 1000;
  nlohmann::json header = {{"alg", "HS256"}, {"typ", "JWT"}};
  nlohmann::json payload = {{"sub", "u" + std::to_string(uid)},
                            {"uid", uid},
                            {"iat", now_s},
                            {"exp", now_s + ttl_seconds},
                            {"jti", random_jti()},
                            {"ct", normalize_client_type(ct)}};
  const auto header_part = base64url_encode(header.dump());
  const auto payload_part = base64url_encode(payload.dump());
  const auto signing_input = header_part + "." + payload_part;
  return signing_input + "." + sign(secret, signing_input);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     校验 IM token 并取出 claims
// 参数说明     token            三段式 JWT 文本
//              secret           HS256 共享密钥
//              now_ms           当前毫秒时间戳
// 返回参数     std::optional<TokenClaims>     校验通过返回 claims 否则为空
// 使用示例     auto claims = verify_token(jwt, secret, now_ms);
// 备注信息     先切段验 alg 与 HMAC 用 CRYPTO_memcmp 常量时间比较 再查 exp iat sub 所有失败路径统一返回空
//-------------------------------------------------------------------------------------------------------------------
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
    // ct 缺省 app:2026-11-08 之前签发的 token 没有这个 claim,必须继续按 App 放行。
    claims.ct = normalize_client_type(payload.value("ct", std::string(kClientApp)));

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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     判断 token 里的会话版本是否仍然有效
// 参数说明     token_sv         token 里的 sv 0 为过渡期旧 token
//              stored           该端在 im_device_session 的当前版本
// 返回参数     bool             允许本次请求返回 true
// 使用示例     session_version_matches(claims.sv, stored);
// 备注信息     sv 为 0 放行 其余要求 stored 有值且完全相等 不一致说明该端已在别处登录
//-------------------------------------------------------------------------------------------------------------------
bool session_version_matches(int64_t token_sv, const std::optional<int64_t>& stored) {
  // sv=0 是 2026-10-28 之前签发的旧 token(过渡期最多 24h),放行;
  // 其余必须与库里的当前版本完全一致 —— 不一致说明**该端**已在别处登录(同类互顶)。
  if (token_sv == 0) {
    return true;
  }
  return stored.has_value() && *stored == token_sv;
}
