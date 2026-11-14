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
* 文件名称          tests/media_sign_test.cpp
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

#include <optional>
#include <string>

#include "util/media_sign.h"

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证媒体 URL 签名与 Django 共享测试向量一致
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R MediaSignerTest.MatchesSharedVector
// 备注信息     覆盖 exp 按整点对齐 1761782400 在 ttl 86400 下得 1761868800 以及
//              ?e= 与 s= 的拼接顺序 签名逐字节等于 Django im/media_sign.py 的输出
//-------------------------------------------------------------------------------------------------------------------
TEST(MediaSignerTest, MatchesSharedVector) {
  // 与 Django im/media_sign.py 的共享测试向量必须一致(exp 由整点对齐 + ttl 算出)
  MediaSigner signer("test-media-secret", 86400, "http://cdn/media/chat/");
  const auto signed_url =
      signer.sign_url("http://cdn/media/chat/2026/10/12-abc.jpg", 1761782400);
  EXPECT_EQ(signed_url,
            "http://cdn/media/chat/2026/10/12-abc.jpg?e=1761868800&s="
            "b57407845446ea5b208d43263f9b8d1a404ee807c8f77aeadaf02d6ab8aba718");
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证规范化剥掉 query 并拒绝前缀外的 URL
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R MediaSignerTest.CanonicalStripsQueryAndRejectsForeignUrl
// 备注信息     覆盖已有 ?e= 与 s= 被剥掉 前缀不匹配的域名与空串返回 nullopt 前缀比对保证不给外站 URL 签名
//-------------------------------------------------------------------------------------------------------------------
TEST(MediaSignerTest, CanonicalStripsQueryAndRejectsForeignUrl) {
  MediaSigner signer("s", 86400, "http://cdn/media/chat/");
  EXPECT_EQ(signer.canonical("http://cdn/media/chat/a.jpg?e=1&s=2"),
            std::optional<std::string>("http://cdn/media/chat/a.jpg"));
  EXPECT_FALSE(signer.canonical("http://evil/a.jpg").has_value());
  EXPECT_FALSE(signer.canonical("").has_value());
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证密钥为空时不启用签名并原样返回 URL
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R MediaSignerTest.DisabledSignerLeavesUrlUntouched
// 备注信息     覆盖 enabled 为 false 且 sign_url 不加任何 query 空密钥只允许开发环境使用 生产缺 IM_MEDIA_SIGN_SECRET 应启动失败
//-------------------------------------------------------------------------------------------------------------------
TEST(MediaSignerTest, DisabledSignerLeavesUrlUntouched) {
  MediaSigner signer("", 86400, "http://cdn/media/chat/");
  EXPECT_FALSE(signer.enabled());
  const std::string url = "http://cdn/media/chat/a.jpg";
  EXPECT_EQ(signer.sign_url(url, 1761782400), url);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证图片对象的 url 与 thumb_url 就地重新签名
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R MediaSignerTest.SignsImageObjectInPlace
// 备注信息     覆盖旧签名 s=old 被替换 两个字段都带上 ?e= 就地修改传入的 JSON 对象 不返回新对象
//-------------------------------------------------------------------------------------------------------------------
TEST(MediaSignerTest, SignsImageObjectInPlace) {
  MediaSigner signer("test-media-secret", 86400, "http://cdn/media/chat/");
  nlohmann::json image = {{"url", "http://cdn/media/chat/a.jpg?e=1&s=old"},
                          {"thumb_url", "http://cdn/media/chat/a_thumb.jpg"}};
  signer.sign_image(image, 1761782400);
  EXPECT_EQ(image["url"].get<std::string>().find("s=old"), std::string::npos);
  EXPECT_NE(image["thumb_url"].get<std::string>().find("?e="), std::string::npos);
}
