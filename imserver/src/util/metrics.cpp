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
* 文件名称          src/util/metrics.cpp
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
#include "util/metrics.h"

#include <sstream>

namespace metrics {

std::atomic<uint64_t> sends_ok{0};
std::atomic<uint64_t> sends_failed{0};
std::atomic<uint64_t> deadlock_retries{0};
std::atomic<uint64_t> db_wait_count{0};
std::atomic<uint64_t> db_wait_us{0};
std::atomic<uint64_t> sensitive_blocked{0};
std::atomic<uint64_t> push_queued{0};
std::atomic<uint64_t> push_sent{0};
std::atomic<uint64_t> push_failed{0};
std::atomic<uint64_t> push_dropped{0};

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     渲染 Prometheus 文本格式的指标快照
// 参数说明     online_connections 当前在线连接数 由 SessionRegistry 统计
// 返回参数     std::string      完整 exposition 文本 每条指标以换行结尾
// 使用示例     const std::string body = metrics::render(registry_.online_count());
// 备注信息     全部计数按 memory_order_relaxed 读取 不重置任何计数 可在任意线程调用
//              池平均等待 = db_wait_us / 1e6 / db_wait_count 分母为 0 时该 gauge 输出 0
//              输出 7 组指标 11 条时间序列 每条以换行结尾 可直接被 Prometheus 抓取
//-------------------------------------------------------------------------------------------------------------------
std::string render(std::size_t online_connections) {
  std::ostringstream out;
  out << "# HELP im_connections 当前在线连接数\n"
      << "# TYPE im_connections gauge\n"
      << "im_connections " << online_connections << "\n"
      << "# HELP im_sends_total 消息发送次数(按结果)\n"
      << "# TYPE im_sends_total counter\n"
      << "im_sends_total{result=\"ok\"} " << sends_ok.load(std::memory_order_relaxed) << "\n"
      << "im_sends_total{result=\"failed\"} " << sends_failed.load(std::memory_order_relaxed)
      << "\n"
      << "# HELP im_deadlock_retries_total 因死锁/锁等待超时进入重试的次数\n"
      << "# TYPE im_deadlock_retries_total counter\n"
      << "im_deadlock_retries_total " << deadlock_retries.load(std::memory_order_relaxed)
      << "\n"
      << "# HELP im_db_pool_wait_seconds 从连接池取连接的平均等待时间\n"
      << "# TYPE im_db_pool_wait_seconds gauge\n";

  const uint64_t waits = db_wait_count.load(std::memory_order_relaxed);
  const double average = waits == 0
                             ? 0.0
                             : static_cast<double>(db_wait_us.load(std::memory_order_relaxed)) /
                                   1e6 / static_cast<double>(waits);
  out << "im_db_pool_wait_seconds " << average << "\n"
      << "# HELP im_db_pool_waits_total 从连接池取连接的次数\n"
      << "# TYPE im_db_pool_waits_total counter\n"
      << "im_db_pool_waits_total " << waits << "\n"
      << "# HELP im_sensitive_blocked_total 因命中敏感词被拒绝的发送次数\n"
      << "# TYPE im_sensitive_blocked_total counter\n"
      << "im_sensitive_blocked_total "
      << sensitive_blocked.load(std::memory_order_relaxed) << "\n"
      << "# HELP im_push_total 离线新消息推送事件(按结果)\n"
      << "# TYPE im_push_total counter\n"
      << "im_push_total{result=\"queued\"} " << push_queued.load(std::memory_order_relaxed)
      << "\n"
      << "im_push_total{result=\"sent\"} " << push_sent.load(std::memory_order_relaxed) << "\n"
      << "im_push_total{result=\"failed\"} " << push_failed.load(std::memory_order_relaxed)
      << "\n"
      << "im_push_total{result=\"dropped\"} " << push_dropped.load(std::memory_order_relaxed)
      << "\n";
  return out.str();
}

}  // namespace metrics
