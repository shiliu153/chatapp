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
* 文件名称          src/util/ratelimit.cpp
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
#include "util/ratelimit.h"

#include <algorithm>
#include <iterator>
#include <utility>

#include "util/log.h"

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     构造令牌桶 桶内初始装满
// 参数说明     rate_per_second  每秒补充的令牌数
//              burst            桶容量 即允许的瞬时突发上限
// 返回参数     void             无返回值
// 使用示例     TokenBucket bucket(20, 40);
// 备注信息     tokens_ 初值取 burst 初始化列表顺序为 rate_ burst_ tokens_
//-------------------------------------------------------------------------------------------------------------------
TokenBucket::TokenBucket(double rate_per_second, double burst)
    : rate_(rate_per_second), burst_(burst), tokens_(burst) {}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     按时间戳补充令牌并判定本次是否放行
// 参数说明     now_ms           当前毫秒时间戳
// 返回参数     bool             取到令牌返回 true 桶空返回 false
// 使用示例     if (bucket.allow(now_ms)) { /* 放行 */ }
// 备注信息     last_ms_ 为 -1 的首次调用只记时间不补令牌 时间回拨按 0 计
//              每次调用都刷新 last_ms_ 放行时扣 1 个令牌 非线程安全
//-------------------------------------------------------------------------------------------------------------------
bool TokenBucket::allow(int64_t now_ms) {
  if (last_ms_ < 0) {
    last_ms_ = now_ms;
  }
  const int64_t elapsed = std::max<int64_t>(0, now_ms - last_ms_);
  last_ms_ = now_ms;
  tokens_ = std::min(burst_, tokens_ + static_cast<double>(elapsed) / 1000.0 * rate_);
  if (tokens_ < 1.0) {
    return false;
  }
  tokens_ -= 1.0;
  return true;
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     构造限流表 记录令牌桶参数与 key 上限
// 参数说明     rate_per_second  每个 key 每秒补充的令牌数
//              burst            每个 key 的桶容量
//              max_entries      表内 key 上限 默认 4096 传 0 按 1 处理
// 返回参数     void             无返回值
// 使用示例     RateTable table(1.0, 3.0, 1024);
// 备注信息     max_entries_ 取 max(max_entries, 1) 保证至少能容纳一个 key
//-------------------------------------------------------------------------------------------------------------------
RateTable::RateTable(double rate_per_second, double burst, std::size_t max_entries)
    : rate_(rate_per_second), burst_(burst), max_entries_(std::max<std::size_t>(max_entries, 1)) {}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     记账一次请求 判定该 key 是否放行
// 参数说明     key              限流维度 这里是账号 id
//              now_ms           当前毫秒时间戳
// 返回参数     bool             允许本次请求返回 true
// 使用示例     if (table.allow(user_id, now_ms)) { /* 放行 */ }
// 备注信息     全程持 mutex_ 新 key 且表已满时先 evict_locked 再 try_emplace
//              每个新 key 的桶从满桶开始 命中后刷新 seen_ms 供淘汰使用
//-------------------------------------------------------------------------------------------------------------------
bool RateTable::allow(uint64_t key, int64_t now_ms) {
  const std::lock_guard<std::mutex> lock(mutex_);
  auto it = entries_.find(key);
  if (it == entries_.end()) {
    if (entries_.size() >= max_entries_) {
      evict_locked(now_ms);
    }
    it = entries_.try_emplace(key, Entry{TokenBucket{rate_, burst_}, now_ms}).first;
  }
  it->second.seen_ms = now_ms;
  return it->second.bucket.allow(now_ms);
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     返回当前表内 key 数量
// 参数说明     无
// 返回参数     std::size_t      已创建的令牌桶个数
// 使用示例     const auto n = table.size();
// 备注信息     const 成员但需加 mutex_ 因此 mutex_ 声明为 mutable
//-------------------------------------------------------------------------------------------------------------------
std::size_t RateTable::size() const {
  const std::lock_guard<std::mutex> lock(mutex_);
  return entries_.size();
}

//-------------------------------------------------------------------------------------------------------------------
// 函数简介     表满时淘汰空闲 key 仍满则整体清空
// 参数说明     now_ms           当前毫秒时间戳 用于算空闲时长
// 返回参数     void             无返回值
// 使用示例     evict_locked(now_ms);  // 调用方必须已持有 mutex_
// 备注信息     先删 seen_ms 距今超过 600000 毫秒(10 分钟)的 key
//              清完仍达上限则打 rate_table_reset 警告后 entries_.clear() 只丢一个限流窗口
//-------------------------------------------------------------------------------------------------------------------
void RateTable::evict_locked(int64_t now_ms) {
  for (auto it = entries_.begin(); it != entries_.end();) {
    it = (now_ms - it->second.seen_ms > 600000) ? entries_.erase(it) : std::next(it);
  }
  if (entries_.size() >= max_entries_) {
    log_warn("rate_table_reset", {{"size", std::to_string(entries_.size())}});
    entries_.clear();
  }
}
