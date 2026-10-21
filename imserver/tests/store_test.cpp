#include <gtest/gtest.h>

#include <cstdlib>
#include <string>

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

TEST(StoreTest, RedisSetGetDel) {
  const char* url = std::getenv("IM_TEST_REDIS_URL");
  ASSERT_NE(url, nullptr);
  RedisClient redis(url);
  ASSERT_TRUE(redis.setex("im:test:key", 30, "v"));
  ASSERT_EQ(redis.get("im:test:key").value_or(""), "v");
  ASSERT_TRUE(redis.del("im:test:key"));
  EXPECT_FALSE(redis.get("im:test:key").has_value());
}
