#include "store/redis_subscriber.h"

#include <sys/socket.h>

#include <chrono>
#include <utility>

#include "store/redis_client.h"
#include "util/log.h"

namespace {

/// 建连与 SUBSCRIBE 阶段的超时:Redis 不可达时不能把订阅线程挂死在 connect 上。
constexpr int kConnectTimeoutMs = 3000;
/// 重连退避上限。
constexpr int kMaxBackoffMs = 30000;

}  // namespace

RedisSubscriber::RedisSubscriber(std::string url, std::vector<std::string> channels,
                                 Handler handler)
    : url_(std::move(url)), channels_(std::move(channels)), handler_(std::move(handler)) {}

RedisSubscriber::~RedisSubscriber() { stop(); }

void RedisSubscriber::start() {
  if (running_.exchange(true)) {
    return;
  }
  stop_.store(false);
  thread_ = std::thread([this] { run(); });
}

void RedisSubscriber::wake_blocked_read() {
  const std::lock_guard<std::mutex> lock(ctx_mu_);
  if (live_ctx_ != nullptr && live_ctx_->fd > 0) {
    // 半关闭这条 fd,阻塞中的 read 会立刻返回错误 —— 比等 socket 超时快得多,
    // 也避免「用超时轮询」导致的空闲期反复重连。
    ::shutdown(live_ctx_->fd, SHUT_RDWR);
  }
}

void RedisSubscriber::stop() {
  if (!running_.exchange(false)) {
    return;
  }
  stop_.store(true);
  wake_blocked_read();
  {
    const std::lock_guard<std::mutex> lock(wait_mu_);
    wait_cv_.notify_all();
  }
  if (thread_.joinable()) {
    thread_.join();
  }
  connected_.store(false);
}

bool RedisSubscriber::wait_or_stop(int ms) {
  std::unique_lock<std::mutex> lock(wait_mu_);
  wait_cv_.wait_for(lock, std::chrono::milliseconds(ms), [this] { return stop_.load(); });
  return !stop_.load();
}

bool RedisSubscriber::connect_and_subscribe(redisContext** ctx_out) {
  *ctx_out = nullptr;
  RedisUrlParts parts;
  try {
    parts = parse_redis_url(url_);
  } catch (const std::exception& error) {
    log_warn("redis_sub_bad_url", {{"error", error.what()}});
    return false;
  }

  auto* ctx = redisConnect(parts.host.c_str(), parts.port);
  if (ctx == nullptr || ctx->err != 0) {
    if (ctx != nullptr) {
      log_warn("redis_sub_connect_failed", {{"error", ctx->errstr}});
      redisFree(ctx);
    }
    return false;
  }
  struct timeval tv {};
  tv.tv_sec = kConnectTimeoutMs / 1000;
  tv.tv_usec = (kConnectTimeoutMs % 1000) * 1000;
  redisSetTimeout(ctx, tv);

  if (!parts.password.empty()) {
    auto* auth = static_cast<redisReply*>(
        parts.user.empty()
            ? redisCommand(ctx, "AUTH %s", parts.password.c_str())
            : redisCommand(ctx, "AUTH %s %s", parts.user.c_str(), parts.password.c_str()));
    const bool ok = auth != nullptr && auth->type == REDIS_REPLY_STATUS;
    if (auth != nullptr) {
      freeReplyObject(auth);
    }
    if (!ok) {
      log_warn("redis_sub_auth_failed", {});
      redisFree(ctx);
      return false;
    }
  }
  auto* select = static_cast<redisReply*>(redisCommand(ctx, "SELECT %d", parts.db));
  const bool select_ok = select != nullptr && select->type == REDIS_REPLY_STATUS;
  if (select != nullptr) {
    freeReplyObject(select);
  }
  if (!select_ok) {
    log_warn("redis_sub_select_failed", {{"db", std::to_string(parts.db)}});
    redisFree(ctx);
    return false;
  }

  std::vector<const char*> argv;
  std::vector<std::size_t> lens;
  argv.reserve(channels_.size() + 1);
  lens.reserve(channels_.size() + 1);
  argv.push_back("SUBSCRIBE");
  lens.push_back(9);
  for (const auto& channel : channels_) {
    argv.push_back(channel.c_str());
    lens.push_back(channel.size());
  }
  auto* reply = static_cast<redisReply*>(
      redisCommandArgv(ctx, static_cast<int>(argv.size()), argv.data(), lens.data()));
  if (reply == nullptr || reply->type == REDIS_REPLY_ERROR) {
    if (reply != nullptr) {
      freeReplyObject(reply);
    }
    redisFree(ctx);
    return false;
  }
  freeReplyObject(reply);

  // 订阅成功后必须**清掉 socket 超时**:收包是阻塞读,如果沿用建连时的 3s 超时,
  // 空闲 3 秒就会以 `EAGAIN`(Resource temporarily unavailable)返回 REDIS_ERR,
  // 被误判成「断线」而反复重连。hiredis 用 {0,0} 表示不限时。
  struct timeval no_timeout {};
  no_timeout.tv_sec = 0;
  no_timeout.tv_usec = 0;
  redisSetTimeout(ctx, no_timeout);

  *ctx_out = ctx;
  return true;
}

void RedisSubscriber::run() {
  int backoff_ms = 1000;
  while (!stop_.load()) {
    redisContext* ctx = nullptr;
    if (!connect_and_subscribe(&ctx)) {
      connected_.store(false);
      if (!wait_or_stop(backoff_ms)) {
        break;
      }
      backoff_ms = backoff_ms * 2 > kMaxBackoffMs ? kMaxBackoffMs : backoff_ms * 2;
      continue;
    }

    {
      const std::lock_guard<std::mutex> lock(ctx_mu_);
      live_ctx_ = ctx;
    }
    connected_.store(true);
    backoff_ms = 1000;
    log_info("redis_sub_subscribed", {{"channels", std::to_string(channels_.size())}});

    // 收包:阻塞读,没有超时轮询。stop() 会 shutdown 掉 fd 让这里返回错误。
    while (!stop_.load()) {
      void* raw = nullptr;
      if (redisGetReply(ctx, &raw) != REDIS_OK) {
        if (!stop_.load()) {
          log_warn("redis_sub_disconnected", {{"error", ctx->errstr}});
        }
        break;
      }
      auto* reply = static_cast<redisReply*>(raw);
      if (reply == nullptr) {
        continue;
      }
      if (reply->type == REDIS_REPLY_ARRAY && reply->elements == 3 &&
          reply->element[0] != nullptr && reply->element[0]->str != nullptr &&
          std::string(reply->element[0]->str) == "message") {
        const std::string channel =
            reply->element[1] != nullptr && reply->element[1]->str != nullptr
                ? std::string(reply->element[1]->str, reply->element[1]->len)
                : std::string();
        const std::string payload =
            reply->element[2] != nullptr && reply->element[2]->str != nullptr
                ? std::string(reply->element[2]->str, reply->element[2]->len)
                : std::string();
        freeReplyObject(reply);
        if (handler_) {
          handler_(channel, payload);
        }
        continue;
      }
      freeReplyObject(reply);
    }

    {
      const std::lock_guard<std::mutex> lock(ctx_mu_);
      live_ctx_ = nullptr;
    }
    connected_.store(false);
    redisFree(ctx);
    if (!wait_or_stop(backoff_ms)) {
      break;
    }
    backoff_ms = backoff_ms * 2 > kMaxBackoffMs ? kMaxBackoffMs : backoff_ms * 2;
  }
}
