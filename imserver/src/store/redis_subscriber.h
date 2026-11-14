#pragma once
#include <hiredis/hiredis.h>

#include <atomic>
#include <condition_variable>
#include <functional>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

/// Redis 发布订阅的订阅端(专用连接 + 专用线程)。
///
/// 为什么不复用 ``RedisClient``:那条连接被 mutex 串行化,且 ``SUBSCRIBE`` 之后连接进入
/// 「只收推送」的阻塞模式 —— 借出去会让所有普通读写卡死。所以这里单开一条。
///
/// 退出机制:收包是**阻塞读**,不用 socket 超时轮询(那会导致空闲时每秒重连一次)。
/// ``stop()`` 直接 ``shutdown()`` 掉这条连接的 fd 来唤醒它,随后 join 线程。
///
/// 语义约定:
///   * ``start()`` 之后回调由**订阅线程**触发;**回调里不得直接操作 WsSession**,
///     应当 ``boost::asio::post`` 回 io_context(见 ``DeliveryBus``)。
///   * Redis 断开时自动重连(退避 1s → 30s 上限),期间回调不触发、进程不崩 ——
///     与「Redis 故障不阻断聊天」的既有取向一致。
///   * ``stop()`` 幂等,返回前保证线程已收尾。
class RedisSubscriber {
 public:
  /// 收到一条推送时的回调:``channel`` 是频道名,``payload`` 是消息体(JSON)。
  using Handler = std::function<void(const std::string& channel, const std::string& payload)>;

  /// 构造(不建连、不起线程;``start()`` 才真正开始)。
  ///
  /// Args:
  ///   url: 形如 ``redis://:pass@host:6379/2`` 的地址,与 ``RedisClient`` 同格式。
  ///   channels: 要订阅的频道名列表。
  ///   handler: 收到推送时的回调。
  RedisSubscriber(std::string url, std::vector<std::string> channels, Handler handler);
  ~RedisSubscriber();

  RedisSubscriber(const RedisSubscriber&) = delete;
  RedisSubscriber& operator=(const RedisSubscriber&) = delete;

  /// 起订阅线程;重复调用无副作用。
  void start();
  /// 停止订阅并回收线程;重复调用无副作用。
  void stop();

  /// 当前是否处于「已连上并在订阅」状态(供日志/排障)。
  bool connected() const { return connected_.load(); }

 private:
  /// 订阅线程主体:循环「连接 → 订阅 → 收包」,断开则退避重连,直到 stop_。
  void run();
  /// 用给定参数建立一条订阅连接并完成 SUBSCRIBE。
  ///
  /// Args:
  ///   ctx_out: 成功时写入连接指针;失败时为 nullptr。
  ///
  /// Returns:
  ///   订阅成功返回 true。
  bool connect_and_subscribe(redisContext** ctx_out);
  /// 可中断的退避等待,``stop`` 后立即返回 false。
  ///
  /// Args:
  ///   ms: 最长等待毫秒数。
  ///
  /// Returns:
  ///   仍在运行返回 true;已请求停止返回 false。
  bool wait_or_stop(int ms);
  /// 让阻塞在收包上的线程立刻醒来(``shutdown`` 掉 fd)。
  void wake_blocked_read();

  std::string url_;
  std::vector<std::string> channels_;
  Handler handler_;
  std::thread thread_;
  std::atomic<bool> running_{false};
  std::atomic<bool> stop_{false};
  std::atomic<bool> connected_{false};
  std::mutex wait_mu_;
  std::condition_variable wait_cv_;
  /// 当前活跃的订阅连接;``stop()`` 靠它 shutdown fd 唤醒阻塞读。
  std::mutex ctx_mu_;
  redisContext* live_ctx_ = nullptr;
};
