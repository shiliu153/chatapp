#include <gtest/gtest.h>

#include <chrono>
#include <cstdlib>
#include <string>
#include <thread>

#include "store/mysql_pool.h"
#include "store/redis_client.h"

TEST(StoreTest, TablesAndSystemUserExist) {
  const char* dsn = std::getenv("IM_TEST_MYSQL_DSN");
  ASSERT_NE(dsn, nullptr);
  MysqlPool pool(parse_mysql_dsn(dsn), 2);
  auto lease = pool.acquire();
  auto* result = lease.query("SELECT nickname FROM im_user WHERE user_id=0");
  ASSERT_NE(result, nullptr);
  MYSQL_ROW row = mysql_fetch_row(result);
  ASSERT_NE(row, nullptr);
  EXPECT_STREQ(row[0], "系统通知");
  mysql_free_result(result);
}

TEST(StoreTest, PoolReconnectsAfterServerKill) {
  // 复现 2026-10-22 的事故:MySQL 的 wait_timeout 会掐掉空闲连接,而池不做存活校验,
  // 之后每条 SQL 都在死连接上失败(readyz 503、发消息 50001),只能重启容器恢复。
  // idle_ping_ms=0 让池在每次 acquire 时都 ping,等价于「空闲足够久」的真实场景。
  const char* dsn = std::getenv("IM_TEST_MYSQL_DSN");
  ASSERT_NE(dsn, nullptr);
  const MysqlDsn parsed = parse_mysql_dsn(dsn);
  MysqlPool pool(parsed, 1, 0);

  unsigned long long victim = 0;
  {
    auto lease = pool.acquire();
    auto* result = lease.query("SELECT CONNECTION_ID()");
    ASSERT_NE(result, nullptr);
    MYSQL_ROW row = mysql_fetch_row(result);
    ASSERT_NE(row, nullptr);
    victim = std::stoull(row[0]);
    mysql_free_result(result);
  }

  MYSQL* killer = mysql_init(nullptr);
  ASSERT_NE(killer, nullptr);
  ASSERT_NE(mysql_real_connect(killer, parsed.host.c_str(), parsed.user.c_str(),
                               parsed.password.c_str(), parsed.database.c_str(),
                               parsed.port, nullptr, 0),
            nullptr);
  const std::string kill_sql = "KILL " + std::to_string(victim);
  ASSERT_EQ(mysql_real_query(killer, kill_sql.data(), kill_sql.size()), 0);
  mysql_close(killer);
  std::this_thread::sleep_for(std::chrono::milliseconds(100));

  auto lease = pool.acquire();
  auto* result = lease.query("SELECT 1");
  ASSERT_NE(result, nullptr);
  mysql_free_result(result);
}

TEST(StoreTest, RedisSetGetDel) {
  const char* url = std::getenv("IM_TEST_REDIS_URL");
  ASSERT_NE(url, nullptr);
  RedisClient redis(url);
  ASSERT_TRUE(redis.setex("im:test:key", 30, "v"));
  ASSERT_EQ(redis.get("im:test:key").value_or(""), "v");
  ASSERT_TRUE(redis.del("im:test:key"));
  EXPECT_FALSE(redis.get("im:test:key").has_value());
}
