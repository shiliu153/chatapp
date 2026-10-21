#pragma once
#include <mysql/mysql.h>

#include <condition_variable>
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

  MysqlPool(const MysqlDsn& dsn, int size);
  ~MysqlPool();
  MysqlPool(const MysqlPool&) = delete;
  MysqlPool& operator=(const MysqlPool&) = delete;

  Lease acquire();

 private:
  void release(MYSQL* conn);

  MysqlDsn dsn_;
  std::mutex mutex_;
  std::condition_variable cv_;
  std::vector<MYSQL*> idle_;
  int size_ = 0;
  bool closed_ = false;
};
