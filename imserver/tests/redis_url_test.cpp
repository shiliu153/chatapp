/// `parse_redis_url` 的单元测试(E-6②)。
///
/// 这里只测「URL → 连接参数」的纯解析:真正发 `AUTH` 的部分需要一台开了
/// `requirepass` 的 Redis,由部署时的冒烟步骤覆盖(见 `docs/ops/imserver.md` §1.4)。
#include <gtest/gtest.h>

#include <stdexcept>

#include "store/redis_client.h"

TEST(RedisUrlTest, ParsesPlainUrl) {
  const auto parts = parse_redis_url("redis://127.0.0.1:6379/2");
  EXPECT_EQ(parts.host, "127.0.0.1");
  EXPECT_EQ(parts.port, 6379);
  EXPECT_EQ(parts.db, 2);
  EXPECT_TRUE(parts.user.empty());
  EXPECT_TRUE(parts.password.empty());
}

TEST(RedisUrlTest, DefaultsPortAndDb) {
  const auto parts = parse_redis_url("redis://redis");
  EXPECT_EQ(parts.host, "redis");
  EXPECT_EQ(parts.port, 6379);
  EXPECT_EQ(parts.db, 0);
  EXPECT_TRUE(parts.password.empty());
}

TEST(RedisUrlTest, ParsesPasswordForDefaultUser) {
  const auto parts = parse_redis_url("redis://:s3cret@redis:6379/2");
  EXPECT_EQ(parts.host, "redis");
  EXPECT_EQ(parts.port, 6379);
  EXPECT_EQ(parts.db, 2);
  EXPECT_TRUE(parts.user.empty());
  EXPECT_EQ(parts.password, "s3cret");
}

TEST(RedisUrlTest, ParsesAclUserAndPassword) {
  const auto parts = parse_redis_url("redis://imuser:s3cret@redis:6379");
  EXPECT_EQ(parts.host, "redis");
  EXPECT_EQ(parts.user, "imuser");
  EXPECT_EQ(parts.password, "s3cret");
}

TEST(RedisUrlTest, DecodesPercentEncodedPassword) {
  // 口令里带 @ 与冒号时必须百分号编码,解析时还原
  const auto parts = parse_redis_url("redis://:p%40ss%3Aword@redis:6379/3");
  EXPECT_EQ(parts.password, "p@ss:word");
  EXPECT_EQ(parts.db, 3);
}

TEST(RedisUrlTest, PasswordMayContainSlash) {
  const auto parts = parse_redis_url("redis://:a/b@redis:6379/4");
  EXPECT_EQ(parts.host, "redis");
  EXPECT_EQ(parts.password, "a/b");
  EXPECT_EQ(parts.db, 4);
}

TEST(RedisUrlTest, RejectsWrongScheme) {
  EXPECT_THROW(parse_redis_url("http://127.0.0.1:6379/0"), std::invalid_argument);
}

TEST(RedisUrlTest, RejectsBadPort) {
  EXPECT_THROW(parse_redis_url("redis://127.0.0.1:notaport/0"), std::invalid_argument);
}

TEST(RedisUrlTest, RejectsBadDb) {
  EXPECT_THROW(parse_redis_url("redis://127.0.0.1:6379/abc"), std::invalid_argument);
}

TEST(RedisUrlTest, RejectsEmptyHost) {
  EXPECT_THROW(parse_redis_url("redis://:6379/0"), std::invalid_argument);
}
