#include <gtest/gtest.h>

#include <string>

#include "util/metrics.h"

TEST(MetricsTest, RenderExposesCoreSeries) {
  // 指标是进程级原子量:用例结束后复位,避免影响同进程里的其他用例。
  const uint64_t ok = metrics::sends_ok.exchange(3);
  const uint64_t failed = metrics::sends_failed.exchange(1);
  const uint64_t retries = metrics::deadlock_retries.exchange(2);
  const uint64_t waits = metrics::db_wait_count.exchange(4);
  const uint64_t wait_us = metrics::db_wait_us.exchange(2000);

  const std::string text = metrics::render(7);

  EXPECT_NE(text.find("im_connections 7"), std::string::npos);
  EXPECT_NE(text.find("im_sends_total{result=\"ok\"} 3"), std::string::npos);
  EXPECT_NE(text.find("im_sends_total{result=\"failed\"} 1"), std::string::npos);
  EXPECT_NE(text.find("im_deadlock_retries_total 2"), std::string::npos);
  EXPECT_NE(text.find("im_db_pool_waits_total 4"), std::string::npos);
  // 4 次等待共 2000us → 平均 0.0005s
  EXPECT_NE(text.find("im_db_pool_wait_seconds 0.0005"), std::string::npos);

  metrics::sends_ok.store(ok);
  metrics::sends_failed.store(failed);
  metrics::deadlock_retries.store(retries);
  metrics::db_wait_count.store(waits);
  metrics::db_wait_us.store(wait_us);
}

TEST(MetricsTest, EmptyPoolWaitRendersZero) {
  const uint64_t waits = metrics::db_wait_count.exchange(0);
  const uint64_t wait_us = metrics::db_wait_us.exchange(0);

  EXPECT_NE(metrics::render(0).find("im_db_pool_wait_seconds 0\n"), std::string::npos);

  metrics::db_wait_count.store(waits);
  metrics::db_wait_us.store(wait_us);
}
