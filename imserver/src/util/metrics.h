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
* 文件名称          src/util/metrics.h
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

/// 因命中敏感词被拒绝的发送次数(批次 Q)。>0 说明词表正在生效;
/// 长期为 0 且词表非空 = 词表可能没加载上(看启动日志 sensitive_words_loaded)。
extern std::atomic<uint64_t> sensitive_blocked;

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
//-------------------------------------------------------------------------------------------------------------------
// 函数简介     渲染 Prometheus 文本格式的指标快照
// 参数说明     online_connections 当前在线连接数 由 SessionRegistry 统计
// 返回参数     std::string      完整 exposition 文本 每条指标以换行结尾
// 使用示例     const std::string body = metrics::render(registry_.online_count());
// 备注信息     只读快照 不重置任何计数 输出 7 组指标 11 条时间序列
//-------------------------------------------------------------------------------------------------------------------
std::string render(std::size_t online_connections);

}  // namespace metrics
