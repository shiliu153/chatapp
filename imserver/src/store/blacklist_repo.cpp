#include "store/blacklist_repo.h"

#include <chrono>

#include "store/stmt.h"

namespace {

int64_t now_ms() {
  return std::chrono::duration_cast<std::chrono::milliseconds>(
             std::chrono::system_clock::now().time_since_epoch())
      .count();
}

}  // namespace

BlacklistRepo::BlacklistRepo(MysqlPool& pool) : pool_(pool) {}

void BlacklistRepo::add(MysqlPool::Lease& lease, uint64_t owner, uint64_t peer,
                        int64_t now_ms) {
  Stmt stmt(lease.get(),
            "INSERT IGNORE INTO im_blacklist (owner_id,peer_id,created_at) VALUES (?,?,?)");
  stmt.bind_uint(0, owner);
  stmt.bind_uint(1, peer);
  stmt.bind_uint(2, static_cast<uint64_t>(now_ms));
  stmt.execute();
}

void BlacklistRepo::add(uint64_t owner, uint64_t peer) {
  auto lease = pool_.acquire();
  add(lease, owner, peer, now_ms());
}

void BlacklistRepo::remove(MysqlPool::Lease& lease, uint64_t owner, uint64_t peer) {
  Stmt stmt(lease.get(), "DELETE FROM im_blacklist WHERE owner_id=? AND peer_id=?");
  stmt.bind_uint(0, owner);
  stmt.bind_uint(1, peer);
  stmt.execute();
}

bool BlacklistRepo::exists_either(MysqlPool::Lease& lease, uint64_t a, uint64_t b) {
  auto* result = lease.query(
      "SELECT 1 FROM im_blacklist WHERE (owner_id=" + std::to_string(a) +
      " AND peer_id=" + std::to_string(b) + ") OR (owner_id=" + std::to_string(b) +
      " AND peer_id=" + std::to_string(a) + ") LIMIT 1");
  bool exists = false;
  if (result != nullptr) {
    exists = mysql_fetch_row(result) != nullptr;
    mysql_free_result(result);
  }
  return exists;
}

bool BlacklistRepo::exists_either(uint64_t a, uint64_t b) {
  auto lease = pool_.acquire();
  return exists_either(lease, a, b);
}
