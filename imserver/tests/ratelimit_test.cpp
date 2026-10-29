#include <gtest/gtest.h>

#include "util/ratelimit.h"

TEST(RateLimitTest, BurstThenRefill) {
  TokenBucket bucket(20, 40);
  int allowed = 0;
  for (int i = 0; i < 100; ++i) {
    if (bucket.allow(0)) {
      ++allowed;
    }
  }
  EXPECT_EQ(allowed, 40);
  int refilled = 0;
  for (int i = 0; i < 25; ++i) {
    if (bucket.allow(1000)) {
      ++refilled;
    }
  }
  EXPECT_EQ(refilled, 20);
}

TEST(RateTableTest, LimitsPerKeyIndependently) {
  RateTable table(1.0, 3.0);
  EXPECT_TRUE(table.allow(1, 0));
  EXPECT_TRUE(table.allow(1, 0));
  EXPECT_TRUE(table.allow(1, 0));
  EXPECT_FALSE(table.allow(1, 0));
  // 另一个账号不受影响
  EXPECT_TRUE(table.allow(2, 0));
  EXPECT_EQ(table.size(), 2u);
}

TEST(RateTableTest, EvictsIdleEntriesWhenFull) {
  RateTable table(1.0, 3.0, 2);
  EXPECT_TRUE(table.allow(1, 0));
  EXPECT_TRUE(table.allow(2, 0));
  // 10 分钟后再来一个新 key:旧的两个都空闲,先被淘汰,表不会超上限
  EXPECT_TRUE(table.allow(3, 601000));
  EXPECT_LE(table.size(), 2u);
}

TEST(RateTableTest, ClearsWhenAllEntriesAreFresh) {
  RateTable table(1.0, 3.0, 2);
  EXPECT_TRUE(table.allow(1, 0));
  EXPECT_TRUE(table.allow(2, 0));
  // 同一时刻插入第三个 key:没有空闲条目可淘汰,整体清空后重新计数
  EXPECT_TRUE(table.allow(3, 0));
  EXPECT_LE(table.size(), 2u);
}
