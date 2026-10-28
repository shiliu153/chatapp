#include <gtest/gtest.h>

#include <stdexcept>
#include <string>
#include <vector>

#include "net/guard.h"
#include "net/ws_server.h"

namespace {

boost::asio::ip::address ip(const std::string& value) {
  return boost::asio::ip::make_address(value);
}

}  // namespace

TEST(GuardTest, ParseListenAcceptsV4AndV6) {
  const auto v4 = net_guard::parse_listen("127.0.0.1:9100");
  EXPECT_TRUE(v4.address.is_v4());
  EXPECT_EQ(v4.port, 9100);
  const auto v6 = net_guard::parse_listen("::1:9101");
  EXPECT_TRUE(v6.address.is_v6());
  EXPECT_EQ(v6.port, 9101);
}

TEST(GuardTest, ParseListenRejectsGarbage) {
  EXPECT_THROW(net_guard::parse_listen("9100"), std::invalid_argument);
  EXPECT_THROW(net_guard::parse_listen("127.0.0.1:"), std::invalid_argument);
  EXPECT_THROW(net_guard::parse_listen("not-an-ip:9100"), std::invalid_argument);
  EXPECT_THROW(net_guard::parse_listen("127.0.0.1:70000"), std::invalid_argument);
}

TEST(GuardTest, DetectsLoopback) {
  EXPECT_TRUE(net_guard::is_loopback(ip("127.0.0.1")));
  EXPECT_TRUE(net_guard::is_loopback(ip("127.5.6.7")));
  EXPECT_TRUE(net_guard::is_loopback(ip("::1")));
  EXPECT_FALSE(net_guard::is_loopback(ip("10.0.0.1")));
  EXPECT_FALSE(net_guard::is_loopback(ip("0.0.0.0")));
}

TEST(GuardTest, DefaultTrustOnlyLoopback) {
  const auto trust = net_guard::ProxyTrust::loopback_only();
  EXPECT_TRUE(trust.trusted(ip("127.0.0.1")));
  EXPECT_TRUE(trust.trusted(ip("::1")));
  // IPv4-mapped IPv6 要按 IPv4 规则命中,否则双栈下限流会被绕过
  EXPECT_TRUE(trust.trusted(ip("::ffff:127.0.0.1")));
  EXPECT_FALSE(trust.trusted(ip("172.17.0.1")));
}

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

TEST(GuardTest, TrustListRejectsInvalidEntries) {
  EXPECT_THROW(net_guard::ProxyTrust::from_list({"10.0.0.0/33"}), std::invalid_argument);
  EXPECT_THROW(net_guard::ProxyTrust::from_list({"nope"}), std::invalid_argument);
}

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

TEST(GuardTest, OriginAllowsNativeClients) {
  EXPECT_TRUE(net_guard::origin_allowed("", "chat.example.com", {}));
  EXPECT_TRUE(net_guard::origin_allowed("", "chat.example.com", {"https://chat.example.com"}));
}

TEST(GuardTest, OriginWhitelist) {
  const std::vector<std::string> allowed{"https://chat.example.com"};
  EXPECT_TRUE(net_guard::origin_allowed("https://chat.example.com", "chat.example.com", allowed));
  EXPECT_TRUE(net_guard::origin_allowed("https://chat.example.com/", "chat.example.com", allowed));
  EXPECT_TRUE(net_guard::origin_allowed("HTTPS://Chat.Example.com", "chat.example.com", allowed));
  EXPECT_FALSE(net_guard::origin_allowed("https://evil.example.com", "chat.example.com", allowed));
  EXPECT_FALSE(net_guard::origin_allowed("null", "chat.example.com", allowed));
}

TEST(GuardTest, OriginFallsBackToSameOrigin) {
  EXPECT_TRUE(net_guard::origin_allowed("https://chat.example.com", "chat.example.com", {}));
  EXPECT_TRUE(net_guard::origin_allowed("https://chat.example.com:443", "chat.example.com", {}));
  EXPECT_TRUE(net_guard::origin_allowed("http://chat.example.com:8080", "chat.example.com:8080", {}));
  EXPECT_FALSE(net_guard::origin_allowed("https://evil.example.com", "chat.example.com", {}));
  EXPECT_FALSE(net_guard::origin_allowed("http://chat.example.com:8080", "chat.example.com", {}));
  EXPECT_FALSE(net_guard::origin_allowed("null", "chat.example.com", {}));
}

TEST(IpCounterTest, AuthBucketsAreBounded) {
  IpCounter counter(20, 1.0, 60.0, 8);
  for (int i = 0; i < 100; ++i) {
    counter.allow_auth("10.0.0." + std::to_string(i), 1000 + i);
  }
  EXPECT_LE(counter.auth_bucket_count(), 8u);
  // 清空只丢一个限流窗口,新 IP 仍然能正常鉴权
  EXPECT_TRUE(counter.allow_auth("10.0.1.1", 2000));
}

TEST(IpCounterTest, AuthBucketsDropIdleEntries) {
  IpCounter counter(20, 1.0, 60.0, 4);
  for (int i = 0; i < 4; ++i) {
    counter.allow_auth("10.0.0." + std::to_string(i), 1000);
  }
  // 11 分钟后再来新 IP:先淘汰空闲桶,不需要整体清空
  counter.allow_auth("10.0.9.9", 1000 + 11 * 60 * 1000);
  EXPECT_EQ(counter.auth_bucket_count(), 1u);
}
