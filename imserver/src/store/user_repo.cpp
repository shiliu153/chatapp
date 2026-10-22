#include "store/user_repo.h"

#include <chrono>

#include "store/stmt.h"

namespace {

int64_t now_ms() {
  return std::chrono::duration_cast<std::chrono::milliseconds>(
             std::chrono::system_clock::now().time_since_epoch())
      .count();
}

}  // namespace

UserRepo::UserRepo(MysqlPool& pool) : pool_(pool) {}

bool UserRepo::is_known(uint64_t uid) {
  const std::lock_guard<std::mutex> lock(known_mu_);
  return known_.count(uid) != 0;
}

void UserRepo::remember(uint64_t uid) {
  const std::lock_guard<std::mutex> lock(known_mu_);
  known_.insert(uid);
}

void UserRepo::forget(uint64_t uid) {
  const std::lock_guard<std::mutex> lock(known_mu_);
  known_.erase(uid);
}

void UserRepo::ensure(MysqlPool::Lease& lease, uint64_t uid, const std::string& nickname) {
  if (is_known(uid)) {
    return;
  }
  // 先做一次主键读(MVCC,不拿写锁):绝大多数调用是已存在的用户,
  // 可以完全避开 INSERT ... ON DUPLICATE KEY UPDATE 在相邻主键上的间隙锁互等。
  bool exists = false;
  auto* result = lease.query("SELECT 1 FROM im_user WHERE user_id=" +
                             std::to_string(uid));
  if (result != nullptr) {
    exists = mysql_fetch_row(result) != nullptr;
    mysql_free_result(result);
  }
  if (!exists) {
    Stmt stmt(lease.get(),
              "INSERT INTO im_user (user_id,nickname,avatar_url,updated_at) VALUES (?,?,'',?) "
              "ON DUPLICATE KEY UPDATE user_id=user_id");
    stmt.bind_uint(0, uid);
    stmt.bind_string(1, nickname);
    stmt.bind_uint(2, static_cast<uint64_t>(now_ms()));
    stmt.execute();
  }
  remember(uid);
}

void UserRepo::ensure(uint64_t uid, const std::string& nickname) {
  auto lease = pool_.acquire();
  ensure(lease, uid, nickname);
}

std::optional<UserRow> UserRepo::get(MysqlPool::Lease& lease, uint64_t uid) {
  {
    const std::lock_guard<std::mutex> lock(profile_mu_);
    const auto it = profiles_.find(uid);
    if (it != profiles_.end()) {
      return it->second;
    }
  }
  auto* result = lease.query(
      "SELECT user_id,nickname,avatar_url FROM im_user WHERE user_id=" +
      std::to_string(uid));
  if (result == nullptr) {
    return std::nullopt;
  }
  std::optional<UserRow> row;
  if (MYSQL_ROW values = mysql_fetch_row(result)) {
    UserRow user;
    user.id = std::stoull(values[0]);
    user.nickname = values[1] == nullptr ? "" : values[1];
    user.avatar = values[2] == nullptr ? "" : values[2];
    row = user;
  }
  mysql_free_result(result);
  if (row.has_value()) {
    remember(row->id);
    const std::lock_guard<std::mutex> lock(profile_mu_);
    profiles_[row->id] = *row;
  }
  return row;
}

std::optional<UserRow> UserRepo::get(uint64_t uid) {
  {
    const std::lock_guard<std::mutex> lock(profile_mu_);
    const auto it = profiles_.find(uid);
    if (it != profiles_.end()) {
      return it->second;
    }
  }
  auto lease = pool_.acquire();
  return get(lease, uid);
}

void UserRepo::remove(MysqlPool::Lease& lease, uint64_t uid) {
  Stmt stmt(lease.get(), "DELETE FROM im_user WHERE user_id=?");
  stmt.bind_uint(0, uid);
  stmt.execute();
  forget(uid);
  const std::lock_guard<std::mutex> lock(profile_mu_);
  profiles_.erase(uid);
}

void UserRepo::update_profile(MysqlPool::Lease& lease, uint64_t uid,
                              const std::optional<std::string>& nickname,
                              const std::optional<std::string>& avatar, int64_t now) {
  if (nickname.has_value()) {
    Stmt stmt(lease.get(), "UPDATE im_user SET nickname=?, updated_at=? WHERE user_id=?");
    stmt.bind_string(0, *nickname);
    stmt.bind_uint(1, static_cast<uint64_t>(now));
    stmt.bind_uint(2, uid);
    stmt.execute();
  }
  if (avatar.has_value()) {
    Stmt stmt(lease.get(), "UPDATE im_user SET avatar_url=?, updated_at=? WHERE user_id=?");
    stmt.bind_string(0, *avatar);
    stmt.bind_uint(1, static_cast<uint64_t>(now));
    stmt.bind_uint(2, uid);
    stmt.execute();
  }
  const std::lock_guard<std::mutex> lock(profile_mu_);
  profiles_.erase(uid);
}
