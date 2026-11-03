#include "util/metrics.h"

#include <sstream>

namespace metrics {

std::atomic<uint64_t> sends_ok{0};
std::atomic<uint64_t> sends_failed{0};
std::atomic<uint64_t> deadlock_retries{0};
std::atomic<uint64_t> db_wait_count{0};
std::atomic<uint64_t> db_wait_us{0};

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
      << "im_db_pool_waits_total " << waits << "\n";
  return out.str();
}

}  // namespace metrics
