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
* 文件名称          src/auth/token.h
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
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     签发 IM 用的 HS256 JWT
// 参数说明     uid              账号 id
//              secret           HS256 共享密钥
//              now_ms           当前毫秒时间戳
//              ttl_seconds      有效期秒数
//              ct               端类型 app 或 web 默认 app
// 返回参数     std::string      三段式 JWT 文本
// 使用示例     std::string jwt = mint_token(42, secret, now_ms, 86400, "web");
// 备注信息     payload 含 sub uid iat exp jti ct 与 Django 侧 mint_im_token 同口径 不校验密钥长度
//-------------------------------------------------------------------------------------------------------------------
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
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     把端类型归一化到 app 或 web
// 参数说明     value            token 里 ct claim 的原始值
// 返回参数     std::string      仅 web 保留 其余一律 app
// 使用示例     std::string ct = normalize_client_type("web");
// 备注信息     老 token 不带 ct 必须继续按 app 放行 未知取值不能凭空造出新的端会话行
//-------------------------------------------------------------------------------------------------------------------
std::string normalize_client_type(std::string_view value);

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     校验 IM token 并取出 claims
// 参数说明     token            三段式 JWT 文本
//              secret           HS256 共享密钥
//              now_ms           当前毫秒时间戳
// 返回参数     std::optional<TokenClaims>     校验通过返回 claims 否则为空
// 使用示例     auto claims = verify_token(jwt, secret, now_ms);
// 备注信息     依次校验段数 alg 为 HS256 HMAC 常量时间比对 exp 未过期 iat 不超前 60 秒 sub 与 uid 一致
//-------------------------------------------------------------------------------------------------------------------
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
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     判断 token 里的会话版本是否仍然有效
// 参数说明     token_sv         token 里的 sv 0 为过渡期旧 token
//              stored           该端在 im_device_session 的当前版本 无该端行为空
// 返回参数     bool             允许本次请求返回 true
// 使用示例     bool ok = session_version_matches(claims.sv, stored);
// 备注信息     WS 与 HTTP 两个入口共用 sv 为 0 直接放行 其余必须与库里的当前版本完全相等
//-------------------------------------------------------------------------------------------------------------------
bool session_version_matches(int64_t token_sv, const std::optional<int64_t>& stored);
