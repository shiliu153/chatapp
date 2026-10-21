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
