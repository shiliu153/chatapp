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
* 文件名称          tests/redis_url_test.cpp
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
/// `parse_redis_url` 的单元测试(E-6②)。
///
/// 这里只测「URL → 连接参数」的纯解析:真正发 `AUTH` 的部分需要一台开了
/// `requirepass` 的 Redis,由部署时的冒烟步骤覆盖(见 `docs/ops/imserver.md` §1.4)。
#include <gtest/gtest.h>

#include <stdexcept>

#include "store/redis_client.h"

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证解析最简 Redis URL
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R ParsesPlainUrl
// 备注信息     redis://127.0.0.1:6379/2 断言 host port db 以及账号与口令都为空
//-------------------------------------------------------------------------------------------------------------------
TEST(RedisUrlTest, ParsesPlainUrl) {
  const auto parts = parse_redis_url("redis://127.0.0.1:6379/2");
  EXPECT_EQ(parts.host, "127.0.0.1");
  EXPECT_EQ(parts.port, 6379);
  EXPECT_EQ(parts.db, 2);
  EXPECT_TRUE(parts.user.empty());
  EXPECT_TRUE(parts.password.empty());
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证缺省端口与库号
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R DefaultsPortAndDb
// 备注信息     只给 host 时 port 兜底 6379 db 兜底 0 口令为空
//-------------------------------------------------------------------------------------------------------------------
TEST(RedisUrlTest, DefaultsPortAndDb) {
  const auto parts = parse_redis_url("redis://redis");
  EXPECT_EQ(parts.host, "redis");
  EXPECT_EQ(parts.port, 6379);
  EXPECT_EQ(parts.db, 0);
  EXPECT_TRUE(parts.password.empty());
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证解析默认用户口令
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R ParsesPasswordForDefaultUser
// 备注信息     冒号前没有账号时 user 为空 password 取冒号后的值 库号仍为 2
//-------------------------------------------------------------------------------------------------------------------
TEST(RedisUrlTest, ParsesPasswordForDefaultUser) {
  const auto parts = parse_redis_url("redis://:s3cret@redis:6379/2");
  EXPECT_EQ(parts.host, "redis");
  EXPECT_EQ(parts.port, 6379);
  EXPECT_EQ(parts.db, 2);
  EXPECT_TRUE(parts.user.empty());
  EXPECT_EQ(parts.password, "s3cret");
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证解析 ACL 账号与口令
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R ParsesAclUserAndPassword
// 备注信息     redis://imuser:s3cret@redis:6379 断言 user 与 password 分别解析 库号兜底 0
//-------------------------------------------------------------------------------------------------------------------
TEST(RedisUrlTest, ParsesAclUserAndPassword) {
  const auto parts = parse_redis_url("redis://imuser:s3cret@redis:6379");
  EXPECT_EQ(parts.host, "redis");
  EXPECT_EQ(parts.user, "imuser");
  EXPECT_EQ(parts.password, "s3cret");
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证口令百分号编码还原
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R DecodesPercentEncodedPassword
// 备注信息     %40 与 %3A 分别还原成 @ 与冒号 断言口令为 p@ss:word 且库号为 3
//-------------------------------------------------------------------------------------------------------------------
TEST(RedisUrlTest, DecodesPercentEncodedPassword) {
  // 口令里带 @ 与冒号时必须百分号编码,解析时还原
  const auto parts = parse_redis_url("redis://:p%40ss%3Aword@redis:6379/3");
  EXPECT_EQ(parts.password, "p@ss:word");
  EXPECT_EQ(parts.db, 3);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证口令中允许出现斜杠
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R PasswordMayContainSlash
// 备注信息     口令 a/b 必须完整解析 不能被当成库号分隔 断言库号为 4
//-------------------------------------------------------------------------------------------------------------------
TEST(RedisUrlTest, PasswordMayContainSlash) {
  const auto parts = parse_redis_url("redis://:a/b@redis:6379/4");
  EXPECT_EQ(parts.host, "redis");
  EXPECT_EQ(parts.password, "a/b");
  EXPECT_EQ(parts.db, 4);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证非 redis 协议被拒
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R RejectsWrongScheme
// 备注信息     http 协议抛 std::invalid_argument 只接受 redis 前缀
//-------------------------------------------------------------------------------------------------------------------
TEST(RedisUrlTest, RejectsWrongScheme) {
  EXPECT_THROW(parse_redis_url("http://127.0.0.1:6379/0"), std::invalid_argument);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证端口非数字被拒
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R RejectsBadPort
// 备注信息     notaport 抛 std::invalid_argument 不做静默兜底
//-------------------------------------------------------------------------------------------------------------------
TEST(RedisUrlTest, RejectsBadPort) {
  EXPECT_THROW(parse_redis_url("redis://127.0.0.1:notaport/0"), std::invalid_argument);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证库号非数字被拒
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R RejectsBadDb
// 备注信息     abc 抛 std::invalid_argument 不做静默兜底
//-------------------------------------------------------------------------------------------------------------------
TEST(RedisUrlTest, RejectsBadDb) {
  EXPECT_THROW(parse_redis_url("redis://127.0.0.1:6379/abc"), std::invalid_argument);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证主机为空被拒
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R RejectsEmptyHost
// 备注信息     redis://:6379/0 缺主机抛 std::invalid_argument 不做兜底
//-------------------------------------------------------------------------------------------------------------------
TEST(RedisUrlTest, RejectsEmptyHost) {
  EXPECT_THROW(parse_redis_url("redis://:6379/0"), std::invalid_argument);
}
