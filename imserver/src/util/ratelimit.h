#pragma once
#include <cstdint>

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
