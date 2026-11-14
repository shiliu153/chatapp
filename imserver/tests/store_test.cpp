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
* 文件名称          tests/store_test.cpp
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

#include <atomic>
#include <chrono>
#include <cstdlib>
#include <string>
#include <thread>
#include <vector>

#include "auth/token.h"
#include "store/conversation_repo.h"
#include "store/mysql_pool.h"
#include "store/redis_client.h"
#include "store/user_repo.h"

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证库表与系统账号存在
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R TablesAndSystemUserExist
// 备注信息     查 im_user 的 user_id=0 行 断言昵称为系统通知 迁移建表失败会在这里红
//-------------------------------------------------------------------------------------------------------------------
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证连接被杀后池能自愈
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R PoolReconnectsAfterServerKill
// 备注信息     idle_ping_ms=0 让每次 acquire 都 ping 另开连接 KILL 掉原连接 断言后续查询仍成功 复现 2026-10-22 空闲超时事故
//-------------------------------------------------------------------------------------------------------------------
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证冷启动建会话不死锁
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R ColdStartConversationCreationDoesNotDeadlock
// 备注信息     16 线程乘 20 个全新配对并发 lock_pair 断言失败数为 0 复现 2026-11-01 压测的 1213 死锁 用例结束清掉 im_conversation
//-------------------------------------------------------------------------------------------------------------------
TEST(StoreTest, ColdStartConversationCreationDoesNotDeadlock) {
  // 复现 2026-11-01 压测的 P0-1:500 对全新配对同时发第一条消息,819/1000 报 1213 死锁。
  // 根因是 lock_pair 先对「不存在的行」做 SELECT ... FOR UPDATE,RR 隔离级别下加的是
  // 间隙锁,几百个事务抢同一段唯一键间隙。修复后 INSERT 在最前面,并发插入退化成等锁。
  // 这里用 16 线程 × 20 个全新配对复现同一模式,断言 0 失败。
  const char* dsn = std::getenv("IM_TEST_MYSQL_DSN");
  ASSERT_NE(dsn, nullptr);
  MysqlPool pool(parse_mysql_dsn(dsn), 8);
  ConversationRepo conversations(pool);

  constexpr int kThreads = 16;
  constexpr int kPerThread = 20;
  constexpr uint64_t kBase = 900000000ULL;
  std::atomic<int> failures{0};
  std::vector<std::thread> workers;
  workers.reserve(kThreads);
  for (int t = 0; t < kThreads; ++t) {
    workers.emplace_back([&, t] {
      for (int i = 0; i < kPerThread; ++i) {
        const uint64_t a = kBase + static_cast<uint64_t>(t) * 1000 + i;
        const uint64_t b = a + 500000;
        try {
          auto lease = pool.acquire();
          lease.begin();
          conversations.lock_pair(lease, a, b, 1);
          lease.commit();
        } catch (const std::exception&) {
          ++failures;
        }
      }
    });
  }
  for (auto& worker : workers) {
    worker.join();
  }
  EXPECT_EQ(failures.load(), 0);

  {
    auto lease = pool.acquire();
    lease.query("DELETE FROM im_conversation WHERE user_a>=" + std::to_string(kBase) +
                " AND user_a<" + std::to_string(kBase + 100000));
  }
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证 Redis 写入读取与删除
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R RedisSetGetDel
// 备注信息     setex 以 30 秒 TTL 写入后 get 取到值 del 之后 get 返回空 读 IM_TEST_REDIS_URL
//-------------------------------------------------------------------------------------------------------------------
TEST(StoreTest, RedisSetGetDel) {
  const char* url = std::getenv("IM_TEST_REDIS_URL");
  ASSERT_NE(url, nullptr);
  RedisClient redis(url);
  ASSERT_TRUE(redis.setex("im:test:key", 30, "v"));
  ASSERT_EQ(redis.get("im:test:key").value_or(""), "v");
  ASSERT_TRUE(redis.del("im:test:key"));
  EXPECT_FALSE(redis.get("im:test:key").has_value());
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证会话版本按端隔离
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R SessionVersionIsPerClient
// 备注信息     app 写 5 web 写 7 两端互不覆盖 写 web 不动 app 那一行 从未写过的那一端读出来是空 用后清理 im_device_session
//-------------------------------------------------------------------------------------------------------------------
TEST(StoreTest, SessionVersionIsPerClient) {
  // 多端在线(K-2):版本按 (user_id, client_type) 存,两端互不覆盖;
  // 从未写过的那一端没有行,读出来是空(带 sv 的 token 因此会被拒)。
  const char* dsn = std::getenv("IM_TEST_MYSQL_DSN");
  ASSERT_NE(dsn, nullptr);
  MysqlPool pool(parse_mysql_dsn(dsn), 2);
  UserRepo users(pool);
  constexpr uint64_t kUid = 990000001ULL;
  {
    auto lease = pool.acquire();
    users.ensure(lease, kUid, "T");
    auto* cleanup = lease.query("DELETE FROM im_device_session WHERE user_id=" +
                                std::to_string(kUid));
    if (cleanup != nullptr) {
      mysql_free_result(cleanup);
    }
  }
  EXPECT_FALSE(users.session_version(kUid, kClientApp).has_value());

  users.set_session_version(kUid, kClientApp, 5);
  users.set_session_version(kUid, kClientWeb, 7);
  EXPECT_EQ(users.session_version(kUid, kClientApp), std::optional<int64_t>(5));
  EXPECT_EQ(users.session_version(kUid, kClientWeb), std::optional<int64_t>(7));

  // 写 web 不能碰 app 那一行(同类互顶靠这个隔离)
  users.set_session_version(kUid, kClientWeb, 8);
  EXPECT_EQ(users.session_version(kUid, kClientApp), std::optional<int64_t>(5));
  EXPECT_EQ(users.session_version(kUid, kClientWeb), std::optional<int64_t>(8));

  auto lease = pool.acquire();
  users.remove(lease, kUid);
  auto* cleanup = lease.query("DELETE FROM im_device_session WHERE user_id=" +
                              std::to_string(kUid));
  if (cleanup != nullptr) {
    mysql_free_result(cleanup);
  }
}
