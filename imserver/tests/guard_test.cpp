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
* 文件名称          tests/guard_test.cpp
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

#include <stdexcept>
#include <string>
#include <vector>

#include "net/guard.h"
#include "net/ws_server.h"

namespace {

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     把 IP 字面量文本转成 boost asio 地址对象
// 参数说明     value            IP 字面量文本 如 127.0.0.1 或 ::1
// 返回参数     boost::asio::ip::address     解析后的地址对象
// 使用示例     const auto addr = ip("127.0.0.1");
// 备注信息     只给测试构造地址用 字面量非法时 boost 抛异常 因此调用点只传合法串
//-------------------------------------------------------------------------------------------------------------------
boost::asio::ip::address ip(const std::string& value) {
  return boost::asio::ip::make_address(value);
}

}  // namespace

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证监听地址解析同时支持 IPv4 与 IPv6 字面量
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R GuardTest.ParseListenAcceptsV4AndV6
// 备注信息     覆盖 127.0.0.1:9100 解析出 v4 地址与端口 9100 ::1:9101 解析出 v6 地址与端口 9101 端口以无符号短整型返回
//-------------------------------------------------------------------------------------------------------------------
TEST(GuardTest, ParseListenAcceptsV4AndV6) {
  const auto v4 = net_guard::parse_listen("127.0.0.1:9100");
  EXPECT_TRUE(v4.address.is_v4());
  EXPECT_EQ(v4.port, 9100);
  const auto v6 = net_guard::parse_listen("::1:9101");
  EXPECT_TRUE(v6.address.is_v6());
  EXPECT_EQ(v6.port, 9101);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证非法监听地址一律抛 std::invalid_argument
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R GuardTest.ParseListenRejectsGarbage
// 备注信息     覆盖缺端口 缺端口号 非 IP 文本 端口 70000 越界四种非法输入 宁可启动失败也不猜一个地址
//-------------------------------------------------------------------------------------------------------------------
TEST(GuardTest, ParseListenRejectsGarbage) {
  EXPECT_THROW(net_guard::parse_listen("9100"), std::invalid_argument);
  EXPECT_THROW(net_guard::parse_listen("127.0.0.1:"), std::invalid_argument);
  EXPECT_THROW(net_guard::parse_listen("not-an-ip:9100"), std::invalid_argument);
  EXPECT_THROW(net_guard::parse_listen("127.0.0.1:70000"), std::invalid_argument);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证回环地址判定覆盖 127.0.0.0/8 与 ::1
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R GuardTest.DetectsLoopback
// 备注信息     覆盖 127.0.0.1 与 127.5.6.7 属回环 10.0.0.1 与 0.0.0.0 不属回环 0.0.0.0 不算回环才能让监听地址校验拦住全网卡绑定
//-------------------------------------------------------------------------------------------------------------------
TEST(GuardTest, DetectsLoopback) {
  EXPECT_TRUE(net_guard::is_loopback(ip("127.0.0.1")));
  EXPECT_TRUE(net_guard::is_loopback(ip("127.5.6.7")));
  EXPECT_TRUE(net_guard::is_loopback(ip("::1")));
  EXPECT_FALSE(net_guard::is_loopback(ip("10.0.0.1")));
  EXPECT_FALSE(net_guard::is_loopback(ip("0.0.0.0")));
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证默认可信代理表只信任本机
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R GuardTest.DefaultTrustOnlyLoopback
// 备注信息     覆盖 127.0.0.1 与 ::1 命中 IPv4-mapped IPv6 形式 ::ffff:127.0.0.1
//              必须按 IPv4 规则命中 否则双栈下限流会被绕过 172.17.0.1 不命中
//-------------------------------------------------------------------------------------------------------------------
TEST(GuardTest, DefaultTrustOnlyLoopback) {
  const auto trust = net_guard::ProxyTrust::loopback_only();
  EXPECT_TRUE(trust.trusted(ip("127.0.0.1")));
  EXPECT_TRUE(trust.trusted(ip("::1")));
  // IPv4-mapped IPv6 要按 IPv4 规则命中,否则双栈下限流会被绕过
  EXPECT_TRUE(trust.trusted(ip("::ffff:127.0.0.1")));
  EXPECT_FALSE(trust.trusted(ip("172.17.0.1")));
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证可信代理表支持 CIDR 与单个 IP 混配
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R GuardTest.TrustListSupportsCidr
// 备注信息     覆盖 10.0.0.0/8 与 fd00::/8 两个网段加 192.168.1.5 单 IP
//              共 3 条规则 段内地址命中 段外地址 192.168.1.6 与 11.0.0.1 不命中
//-------------------------------------------------------------------------------------------------------------------
TEST(GuardTest, TrustListSupportsCidr) {
  const auto trust =
      net_guard::ProxyTrust::from_list({"10.0.0.0/8", "fd00::/8", "192.168.1.5"});
  EXPECT_EQ(trust.size(), 3u);
  EXPECT_TRUE(trust.trusted(ip("10.1.2.3")));
  EXPECT_TRUE(trust.trusted(ip("fd00::1")));
  EXPECT_TRUE(trust.trusted(ip("192.168.1.5")));
  EXPECT_FALSE(trust.trusted(ip("192.168.1.6")));
  EXPECT_FALSE(trust.trusted(ip("11.0.0.1")));
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证非法代理网段条目抛 std::invalid_argument
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R GuardTest.TrustListRejectsInvalidEntries
// 备注信息     覆盖前缀长度越界 10.0.0.0/33 与非 IP 文本 nope 两种非法条目 非法即启动失败不静默跳过
//-------------------------------------------------------------------------------------------------------------------
TEST(GuardTest, TrustListRejectsInvalidEntries) {
  EXPECT_THROW(net_guard::ProxyTrust::from_list({"10.0.0.0/33"}), std::invalid_argument);
  EXPECT_THROW(net_guard::ProxyTrust::from_list({"nope"}), std::invalid_argument);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证客户端 IP 只在可信对端时才采信 X-Real-IP
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R GuardTest.ClientIpTrustsHeaderOnlyFromProxy
// 备注信息     覆盖可信对端采信头里的单 IP 非可信对端伪造头一律回退真实对端 头里多级拼接与纯空白同样回退 避免伪造串成为限流 key
//-------------------------------------------------------------------------------------------------------------------
TEST(GuardTest, ClientIpTrustsHeaderOnlyFromProxy) {
  const auto trust = net_guard::ProxyTrust::loopback_only();
  EXPECT_EQ(net_guard::client_ip(ip("127.0.0.1"), "203.0.113.9", trust), "203.0.113.9");
  // 非可信对端伪造头 → 一律用真实对端地址
  EXPECT_EQ(net_guard::client_ip(ip("198.51.100.7"), "203.0.113.9", trust), "198.51.100.7");
  // 头不合法(多级拼接 / 空白)→ 回退,避免伪造串成为限流 key
  EXPECT_EQ(net_guard::client_ip(ip("127.0.0.1"), "203.0.113.9, 198.51.100.1", trust),
            "127.0.0.1");
  EXPECT_EQ(net_guard::client_ip(ip("127.0.0.1"), "  ", trust), "127.0.0.1");
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证没有 Origin 头的原生客户端直接放行
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R GuardTest.OriginAllowsNativeClients
// 备注信息     覆盖空 Origin 在白名单为空与非空两种配置下都放行 原生 App 与压测脚本都不发这个头
//-------------------------------------------------------------------------------------------------------------------
TEST(GuardTest, OriginAllowsNativeClients) {
  EXPECT_TRUE(net_guard::origin_allowed("", "chat.example.com", {}));
  EXPECT_TRUE(net_guard::origin_allowed("", "chat.example.com", {"https://chat.example.com"}));
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证配置白名单后 Origin 必须命中白名单
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R GuardTest.OriginWhitelist
// 备注信息     覆盖大小写不敏感 结尾斜杠忽略 白名单外域名与 null 一律拒绝
//-------------------------------------------------------------------------------------------------------------------
TEST(GuardTest, OriginWhitelist) {
  const std::vector<std::string> allowed{"https://chat.example.com"};
  EXPECT_TRUE(net_guard::origin_allowed("https://chat.example.com", "chat.example.com", allowed));
  EXPECT_TRUE(net_guard::origin_allowed("https://chat.example.com/", "chat.example.com", allowed));
  EXPECT_TRUE(net_guard::origin_allowed("HTTPS://Chat.Example.com", "chat.example.com", allowed));
  EXPECT_FALSE(net_guard::origin_allowed("https://evil.example.com", "chat.example.com", allowed));
  EXPECT_FALSE(net_guard::origin_allowed("null", "chat.example.com", allowed));
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证未配白名单时 Origin 按同源兜底
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R GuardTest.OriginFallsBackToSameOrigin
// 备注信息     覆盖 443 默认端口忽略 非默认端口 8080 必须与 Host 完全一致 同源比较只比 host 与非默认端口 不比 scheme 跨源域名与 null 拒绝
//-------------------------------------------------------------------------------------------------------------------
TEST(GuardTest, OriginFallsBackToSameOrigin) {
  EXPECT_TRUE(net_guard::origin_allowed("https://chat.example.com", "chat.example.com", {}));
  EXPECT_TRUE(net_guard::origin_allowed("https://chat.example.com:443", "chat.example.com", {}));
  EXPECT_TRUE(net_guard::origin_allowed("http://chat.example.com:8080", "chat.example.com:8080", {}));
  EXPECT_FALSE(net_guard::origin_allowed("https://evil.example.com", "chat.example.com", {}));
  EXPECT_FALSE(net_guard::origin_allowed("http://chat.example.com:8080", "chat.example.com", {}));
  EXPECT_FALSE(net_guard::origin_allowed("null", "chat.example.com", {}));
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证鉴权令牌桶数量达到上限后不再增长
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R IpCounterTest.AuthBucketsAreBounded
// 备注信息     上限设为 8 连续 100 个不同 IP 后桶数不超过 8 整体清空只丢一个限流窗口 新 IP 仍能正常鉴权
//-------------------------------------------------------------------------------------------------------------------
TEST(IpCounterTest, AuthBucketsAreBounded) {
  IpCounter counter(20, 1.0, 60.0, 8);
  for (int i = 0; i < 100; ++i) {
    counter.allow_auth("10.0.0." + std::to_string(i), 1000 + i);
  }
  EXPECT_LE(counter.auth_bucket_count(), 8u);
  // 清空只丢一个限流窗口,新 IP 仍然能正常鉴权
  EXPECT_TRUE(counter.allow_auth("10.0.1.1", 2000));
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证超限时先淘汰空闲桶而不是整体清空
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R IpCounterTest.AuthBucketsDropIdleEntries
// 备注信息     上限设为 4 先填满 4 个桶 11 分钟后再来新 IP 触发淘汰 最后只剩 1 个桶 证明走的是淘汰分支
//-------------------------------------------------------------------------------------------------------------------
TEST(IpCounterTest, AuthBucketsDropIdleEntries) {
  IpCounter counter(20, 1.0, 60.0, 4);
  for (int i = 0; i < 4; ++i) {
    counter.allow_auth("10.0.0." + std::to_string(i), 1000);
  }
  // 11 分钟后再来新 IP:先淘汰空闲桶,不需要整体清空
  counter.allow_auth("10.0.9.9", 1000 + 11 * 60 * 1000);
  EXPECT_EQ(counter.auth_bucket_count(), 1u);
}
