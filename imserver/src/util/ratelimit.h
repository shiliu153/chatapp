#pragma once
#include <cstddef>
#include <cstdint>
#include <mutex>
#include <unordered_map>

class TokenBucket {
 public:
  TokenBucket(double rate_per_second, double burst);

  bool allow(int64_t now_ms);

 private:
  double rate_;
  double burst_;
  double tokens_;
  int64_t last_ms_ = -1;
};

/// 按 key 共享令牌桶的限流表(线程安全)。
///
/// 设计要点:
///   1. 每个 key 一个令牌桶,第一次出现时按需创建;
///   2. 表有上限:先淘汰 10 分钟没再出现的 key,仍然满就整体清空并记警告 ——
///      只丢失一个限流窗口,绝不跟着任意 key 无限涨内存;
///   3. WS 与 HTTP 的多个入口共用这一份实现,避免每处各写一遍清理逻辑。
class RateTable {
 public:
  /// Args:
  ///   rate_per_second: 每秒补充的令牌数。
  ///   burst: 桶容量(允许的瞬时突发)。
  ///   max_entries: 表内 key 上限,超过即触发淘汰。
  RateTable(double rate_per_second, double burst, std::size_t max_entries = 4096);

  /// 记账一次请求。
  ///
  /// Args:
  ///   key: 限流维度(这里是账号 id)。
  ///   now_ms: 当前毫秒时间戳。
  ///
  /// Returns:
  ///   允许本次请求返回 true。
  bool allow(uint64_t key, int64_t now_ms);

  /// 当前表内 key 数量(测试与观测用)。
  std::size_t size() const;

 private:
  /// 一个 key 的令牌桶与最近出现时间(用于淘汰空闲 key)。
  struct Entry {
    TokenBucket bucket;
    int64_t seen_ms = 0;
  };

  /// 表满时淘汰空闲 key;调用方必须已持有 ``mutex_``。
  void evict_locked(int64_t now_ms);

  const double rate_;
  const double burst_;
  const std::size_t max_entries_;
  mutable std::mutex mutex_;
  std::unordered_map<uint64_t, Entry> entries_;
};
