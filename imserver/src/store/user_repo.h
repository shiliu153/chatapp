#pragma once
#include <cstdint>
#include <mutex>
#include <optional>
#include <string>
#include <unordered_map>
#include <unordered_set>

#include "store/models.h"
#include "store/mysql_pool.h"

class UserRepo {
 public:
  explicit UserRepo(MysqlPool& pool, std::size_t max_known = 100000);

  void ensure(MysqlPool::Lease& lease, uint64_t uid, const std::string& nickname);
  void ensure(uint64_t uid, const std::string& nickname);
  std::optional<UserRow> get(MysqlPool::Lease& lease, uint64_t uid);
  std::optional<UserRow> get(uint64_t uid);
  std::optional<int64_t> session_version(MysqlPool::Lease& lease, uint64_t uid);
  std::optional<int64_t> session_version(uint64_t uid);
  void set_session_version(MysqlPool::Lease& lease, uint64_t uid, int64_t version);
  void set_session_version(uint64_t uid, int64_t version);
  void update_profile(MysqlPool::Lease& lease, uint64_t uid,
                      const std::optional<std::string>& nickname,
                      const std::optional<std::string>& avatar, int64_t now_ms);
  void remove(MysqlPool::Lease& lease, uint64_t uid);
  /// 清空进程内缓存(测试清库后必须调用,否则 ensure 会误以为用户仍存在)。
  void clear_cache();

 private:
  bool is_known(uint64_t uid);
  void remember(uint64_t uid);
  void forget(uint64_t uid);

  MysqlPool& pool_;
  std::size_t max_known_;
  std::mutex known_mu_;
  std::unordered_set<uint64_t> known_;
  std::mutex profile_mu_;
  std::unordered_map<uint64_t, UserRow> profiles_;
};
