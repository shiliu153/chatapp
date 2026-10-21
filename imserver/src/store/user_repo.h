#pragma once
#include <cstdint>
#include <optional>
#include <string>

#include "store/models.h"
#include "store/mysql_pool.h"

class UserRepo {
 public:
  explicit UserRepo(MysqlPool& pool);

  void ensure(MysqlPool::Lease& lease, uint64_t uid, const std::string& nickname);
  void ensure(uint64_t uid, const std::string& nickname);
  std::optional<UserRow> get(MysqlPool::Lease& lease, uint64_t uid);
  std::optional<UserRow> get(uint64_t uid);
  void update_profile(MysqlPool::Lease& lease, uint64_t uid,
                      const std::optional<std::string>& nickname,
                      const std::optional<std::string>& avatar, int64_t now_ms);

 private:
  MysqlPool& pool_;
};
