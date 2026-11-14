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
* 文件名称          tests/metrics_test.cpp
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

#include <string>

#include "util/metrics.h"

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证 Prometheus 渲染包含核心指标序列
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R MetricsTest.RenderExposesCoreSeries
// 备注信息     覆盖 im_connections 与发送成败两条 result 标签 死锁重试 连接池等待次数 敏感词拦截数 平均等待
//              2000us 除以 4 次得 0.0005s 用例用 exchange 暂存原值并在末尾复位 避免污染同进程其他用例
//-------------------------------------------------------------------------------------------------------------------
TEST(MetricsTest, RenderExposesCoreSeries) {
  // 指标是进程级原子量:用例结束后复位,避免影响同进程里的其他用例。
  const uint64_t ok = metrics::sends_ok.exchange(3);
  const uint64_t failed = metrics::sends_failed.exchange(1);
  const uint64_t retries = metrics::deadlock_retries.exchange(2);
  const uint64_t waits = metrics::db_wait_count.exchange(4);
  const uint64_t wait_us = metrics::db_wait_us.exchange(2000);
  const uint64_t blocked = metrics::sensitive_blocked.exchange(5);

  const std::string text = metrics::render(7);

  EXPECT_NE(text.find("im_connections 7"), std::string::npos);
  EXPECT_NE(text.find("im_sends_total{result=\"ok\"} 3"), std::string::npos);
  EXPECT_NE(text.find("im_sends_total{result=\"failed\"} 1"), std::string::npos);
  EXPECT_NE(text.find("im_deadlock_retries_total 2"), std::string::npos);
  EXPECT_NE(text.find("im_db_pool_waits_total 4"), std::string::npos);
  EXPECT_NE(text.find("im_sensitive_blocked_total 5"), std::string::npos);
  // 4 次等待共 2000us → 平均 0.0005s
  EXPECT_NE(text.find("im_db_pool_wait_seconds 0.0005"), std::string::npos);

  metrics::sends_ok.store(ok);
  metrics::sends_failed.store(failed);
  metrics::deadlock_retries.store(retries);
  metrics::db_wait_count.store(waits);
  metrics::db_wait_us.store(wait_us);
  metrics::sensitive_blocked.store(blocked);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     用例 验证连接池无等待时平均等待渲染为 0
// 参数说明     无
// 返回参数     void             无返回值
// 使用示例     ctest -R MetricsTest.EmptyPoolWaitRendersZero
// 备注信息     覆盖计数与累计微秒都为 0 时输出 im_db_pool_wait_seconds 0 且带换行 除零回退为 0 而不是 nan 同样用 exchange 复位原值
//-------------------------------------------------------------------------------------------------------------------
TEST(MetricsTest, EmptyPoolWaitRendersZero) {
  const uint64_t waits = metrics::db_wait_count.exchange(0);
  const uint64_t wait_us = metrics::db_wait_us.exchange(0);

  EXPECT_NE(metrics::render(0).find("im_db_pool_wait_seconds 0\n"), std::string::npos);

  metrics::db_wait_count.store(waits);
  metrics::db_wait_us.store(wait_us);
}
