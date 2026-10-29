#include "util/ratelimit.h"

#include <algorithm>
#include <iterator>
#include <utility>

#include "util/log.h"

TokenBucket::TokenBucket(double rate_per_second, double burst)
    : rate_(rate_per_second), burst_(burst), tokens_(burst) {}

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

RateTable::RateTable(double rate_per_second, double burst, std::size_t max_entries)
    : rate_(rate_per_second), burst_(burst), max_entries_(std::max<std::size_t>(max_entries, 1)) {}

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

std::size_t RateTable::size() const {
  const std::lock_guard<std::mutex> lock(mutex_);
  return entries_.size();
}

void RateTable::evict_locked(int64_t now_ms) {
  for (auto it = entries_.begin(); it != entries_.end();) {
    it = (now_ms - it->second.seen_ms > 600000) ? entries_.erase(it) : std::next(it);
  }
  if (entries_.size() >= max_entries_) {
    log_warn("rate_table_reset", {{"size", std::to_string(entries_.size())}});
    entries_.clear();
  }
}
