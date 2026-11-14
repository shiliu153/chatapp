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
* 文件名称          tests/ratelimit_test.cpp
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

#include "util/ratelimit.h"

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证令牌桶突发与按时间补充
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R BurstThenRefill
// 备注信息     容量 40 连取 100 次只放行 40 次 时间前进 1000ms 后按每秒 20 补满再放行 20 次
//-------------------------------------------------------------------------------------------------------------------
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证按 key 独立限流
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R LimitsPerKeyIndependently
// 备注信息     同一 key 容量 3 第四次被拒 另一个 key 不受影响 表内 key 数为 2
//-------------------------------------------------------------------------------------------------------------------
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

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证表满时淘汰空闲 key
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R EvictsIdleEntriesWhenFull
// 备注信息     上限 2 时间前进 601000ms 后插入新 key 旧的两条都空闲先被淘汰 表不会超上限
//-------------------------------------------------------------------------------------------------------------------
TEST(RateTableTest, EvictsIdleEntriesWhenFull) {
  RateTable table(1.0, 3.0, 2);
  EXPECT_TRUE(table.allow(1, 0));
  EXPECT_TRUE(table.allow(2, 0));
  // 10 分钟后再来一个新 key:旧的两个都空闲,先被淘汰,表不会超上限
  EXPECT_TRUE(table.allow(3, 601000));
  EXPECT_LE(table.size(), 2u);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证无空闲条目时整体清空
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R ClearsWhenAllEntriesAreFresh
// 备注信息     同一时刻插入第三个 key 没有可淘汰的条目 整体清空后重新计数 表不超上限
//-------------------------------------------------------------------------------------------------------------------
TEST(RateTableTest, ClearsWhenAllEntriesAreFresh) {
  RateTable table(1.0, 3.0, 2);
  EXPECT_TRUE(table.allow(1, 0));
  EXPECT_TRUE(table.allow(2, 0));
  // 同一时刻插入第三个 key:没有空闲条目可淘汰,整体清空后重新计数
  EXPECT_TRUE(table.allow(3, 0));
  EXPECT_LE(table.size(), 2u);
}
