#pragma once
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <string>

/// 进程内指标:只做原子累加,不引第三方库;`render()` 输出 Prometheus 文本格式。
///
/// 设计要点:
///   1. 全是无锁原子计数,热路径上只多一条 `fetch_add`(relaxed),不影响发送吞吐;
///   2. 只暴露「能回答故障问题」的少量指标(连接数/发送成败/死锁重试/池等待),
///      不做标签维度,避免 C++ 侧维护一套标签系统;
///   3. `/metrics` 由 `HttpApi` 只在回环来源上开放(与 `/internal/*` 同口径)。
namespace metrics {

/// 发送成功次数(含幂等重放命中)。
extern std::atomic<uint64_t> sends_ok;
/// 发送失败次数(50001)。
extern std::atomic<uint64_t> sends_failed;
/// 因 1213/1205 进入重试的次数(>0 说明发生了死锁或锁等待超时)。
extern std::atomic<uint64_t> deadlock_retries;
/// 从连接池取连接的等待次数与累计微秒(用于算平均等待)。
extern std::atomic<uint64_t> db_wait_count;
extern std::atomic<uint64_t> db_wait_us;

/// 离线新消息推送事件(C-1):已入队 / 投递成功 / 投递失败 / 队列满被丢弃。
/// 「没推送」和「推送失败」必须能分开看,否则排查时只能猜。
extern std::atomic<uint64_t> push_queued;
extern std::atomic<uint64_t> push_sent;
extern std::atomic<uint64_t> push_failed;
extern std::atomic<uint64_t> push_dropped;

/// 渲染 Prometheus 文本格式快照。
///
/// Args:
///   online_connections: 当前在线连接数(由 SessionRegistry 提供)。
///
/// Returns:
///   exposition 格式文本。
std::string render(std::size_t online_connections);

}  // namespace metrics
