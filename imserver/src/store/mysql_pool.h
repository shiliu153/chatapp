#pragma once
#include <mysql/mysql.h>

#include <condition_variable>
#include <cstdint>
#include <mutex>
#include <string>
#include <vector>

#include "config.h"

class MysqlPool {
 public:
  class Lease {
   public:
    Lease(MysqlPool& pool, MYSQL* conn);
    ~Lease();
    Lease(const Lease&) = delete;
    Lease& operator=(const Lease&) = delete;
    Lease(Lease&& other) noexcept;
    Lease& operator=(Lease&& other) noexcept;

    MYSQL* get() const { return conn_; }
    MYSQL_RES* query(const std::string& sql);
    std::string escape(const std::string& input) const;
    void begin();
    void commit();
    void rollback();

   private:
    void release();

    MysqlPool* pool_ = nullptr;
    MYSQL* conn_ = nullptr;
  };

  /// 建池。
  ///
  /// Args:
  ///   dsn: MySQL 连接串。
  ///   size: 连接数(启动时全部建好,连不上直接抛,属于配置错误)。
  ///   idle_ping_ms: 连接空闲超过该毫秒数就先 ping 一次再交给调用方;
  ///     0 表示每次都 ping(测试用),负数表示关闭探测。
  MysqlPool(const MysqlDsn& dsn, int size, int64_t idle_ping_ms = 5000);
  ~MysqlPool();
  MysqlPool(const MysqlPool&) = delete;
  MysqlPool& operator=(const MysqlPool&) = delete;

  Lease acquire();

 private:
  struct Slot {
    MYSQL* conn = nullptr;
    int64_t last_used_ms = 0;
  };

  void release(MYSQL* conn);
  void discard(MYSQL* conn);
  MYSQL* connect_with_retry(int attempts);

  MysqlDsn dsn_;
  int64_t idle_ping_ms_ = 5000;
  std::mutex mutex_;
  std::condition_variable cv_;
  std::vector<Slot> idle_;
  int size_ = 0;
  bool closed_ = false;
};
