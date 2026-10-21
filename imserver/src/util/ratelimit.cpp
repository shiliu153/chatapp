#include "util/ratelimit.h"

#include <algorithm>

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
