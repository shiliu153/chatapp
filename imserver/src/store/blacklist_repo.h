#pragma once
#include <cstdint>

#include "store/mysql_pool.h"

class BlacklistRepo {
 public:
  explicit BlacklistRepo(MysqlPool& pool);

  void add(MysqlPool::Lease& lease, uint64_t owner, uint64_t peer, int64_t now_ms);
  void add(uint64_t owner, uint64_t peer);
  void remove(MysqlPool::Lease& lease, uint64_t owner, uint64_t peer);
  bool exists_either(MysqlPool::Lease& lease, uint64_t a, uint64_t b);
  bool exists_either(uint64_t a, uint64_t b);

 private:
  MysqlPool& pool_;
};
