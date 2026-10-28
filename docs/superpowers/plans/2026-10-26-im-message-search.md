# 聊天记录搜索 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> 本项目约定：**一律内联执行**（用户 2026-10-04 明确要求），不要为执行计划派发子 agent。

**Goal:** 自建 IM 后端下支持按关键词搜索单聊文本消息，点结果进聊天页并定位到那条消息（App + Web 双端）。

**Architecture:** imserver 新增 `GET /im/api/search`（`LIKE` 扫描「我参与的会话」+ 游标分页 + 每 uid 限流）；App/Web 通过能力位 `search` 决定入口可见性，搜索页调 IM 客户端新增的 `searchMessages`，点击结果带 `?focus=<msg_id>` 进聊天页，聊天页用 `before_seq` 回溯历史并滚动高亮。

**Tech Stack:** C++20 + Boost.Beast + MySQL 8（imserver）；Flutter 3.47 + Riverpod（App）；Vue 3 + Pinia + vue-router（Web）。

## Global Constraints

- 规格：`docs/superpowers/specs/2026-10-26-im-message-search-design.md`（已批准）。
- 搜索只搜 `kind=1` 文本、未撤回、我参与、会话未删、未被我拉黑、非系统通知（uid=0）。
- 关键词：去首尾空白后 1–150 字节；`LIKE` 转义字符固定 `!`，SQL 写 `ESCAPE '!'`。
- 限流：每 uid 60 次/分钟、burst 20，超限 `42901` / HTTP 429。
- 接口鉴权与 `/im/api/messages` 完全一致（Bearer IM token）；错误体沿用 `{"code","message"}`。
- App/Web 搜索入口只在 `capabilities.search == true` 时显示；腾讯后端抛 `42202`。
- 定位最多回溯 **5 页 × 50 条**、滚动最多 **24 次**，超限静默停在最新一条。
- 每步全绿再进下一步：imserver `test.sh`；App `flutter analyze` 零告警 + 全量测试；Web `type-check` + `lint --max-warnings 0` + `vitest`。
- 提交信息用中文 `feat(im)/docs(im)/test(im)` 前缀，沿用仓库风格。

---

### Task 1: 关键词转义工具 `like_pattern`

**Files:**
- Create: `imserver/src/util/like.h`
- Test: `imserver/tests/like_test.cpp`
- Modify: `imserver/tests/CMakeLists.txt:4-5`

**Interfaces:**
- Produces: `std::string like_pattern(const std::string& keyword)` → `%<escaped>%`；`std::string escape_like(const std::string&)`。

- [x] **Step 1: 写失败测试**

```cpp
// imserver/tests/like_test.cpp
#include <gtest/gtest.h>

#include "util/like.h"

TEST(LikeTest, WrapsKeywordWithPercent) {
  EXPECT_EQ(like_pattern("火锅"), "%火锅%");
}

TEST(LikeTest, EscapesWildcardsAndEscapeChar) {
  EXPECT_EQ(like_pattern("100%"), "%100!%%");
  EXPECT_EQ(like_pattern("a_b"), "%a!_b%");
  EXPECT_EQ(like_pattern("!!"), "%!!!!%");
}

TEST(LikeTest, KeepsPlainTextUntouched) {
  EXPECT_EQ(like_pattern("c++ 2.0"), "%c++ 2.0%");
  EXPECT_EQ(like_pattern(""), "%%");
}
```

- [x] **Step 2: 跑测试确认失败**

Run: `cd imserver && docker compose -f docker-compose.test.yml run --rm test bash -c "cmake -S /src -B /src/build -G Ninja -DCMAKE_BUILD_TYPE=Debug >/dev/null && cmake --build /src/build 2>&1 | tail -20"`
Expected: 编译失败 `util/like.h: No such file or directory`

- [x] **Step 3: 实现 `imserver/src/util/like.h`**

```cpp
#pragma once
#include <string>

/// 把 LIKE 模式里的特殊字符转义。
///
/// 转义字符选 `!` 而不是反斜杠:反斜杠在 SQL 字符串字面量里要写两次、
/// 且受 `NO_BACKSLASH_ESCAPES` 影响,而 `!` 在 SQL 里没有特殊含义。
/// 调用方 SQL 必须写 `LIKE ? ESCAPE '!'`。
inline std::string escape_like(const std::string& input) {
  std::string out;
  out.reserve(input.size() + 8);
  for (const char c : input) {
    if (c == '!' || c == '%' || c == '_') {
      out.push_back('!');
    }
    out.push_back(c);
  }
  return out;
}

/// 用户关键词 → `%关键词%` 模式串(供 prepared statement 绑定)。
inline std::string like_pattern(const std::string& keyword) {
  return "%" + escape_like(keyword) + "%";
}
```

- [x] **Step 4: 把测试加进构建**

`imserver/tests/CMakeLists.txt` 的 `add_executable(im_unit_tests ...)` 里追加 `like_test.cpp`：

```cmake
add_executable(im_unit_tests config_test.cpp token_test.cpp ratelimit_test.cpp hmac_test.cpp
                             media_sign_test.cpp like_test.cpp)
```

- [x] **Step 5: 跑测试确认通过**

Run: `cd imserver && docker compose -f docker-compose.test.yml run --rm test bash -c "cmake -S /src -B /src/build -G Ninja >/dev/null && cmake --build /src/build >/dev/null && /src/build/im_unit_tests --gtest_filter='LikeTest.*'"`
Expected: `[  PASSED  ] 3 tests.`

- [x] **Step 6: 提交**

```bash
git add imserver/src/util/like.h imserver/tests/like_test.cpp imserver/tests/CMakeLists.txt
git commit -m "feat(imserver): LIKE 关键词转义工具"
```

---

### Task 2: 迁移器泛化 + 迁移 v2（`im_conversation.user_b` 索引）

**Files:**
- Create: `imserver/migrations/002_search_index.sql`
- Modify: `imserver/src/migrate.cpp:47-66`

**Interfaces:**
- Produces: schema v2；`im_conversation` 新增 `idx_user_b`。后续任务依赖「`OR user_b = ?` 能走索引」，但不依赖具体索引名。

- [x] **Step 1: 写迁移文件**

```sql
-- imserver/migrations/002_search_index.sql
-- 搜索按 (user_a = ? OR user_b = ?) 过滤会话:user_a 有 uk_pair 前缀,user_b 没有索引。
ALTER TABLE im_conversation ADD KEY idx_user_b (user_b);
```

- [x] **Step 2: 改 `run_migrations` 为按版本表循环**

把 `imserver/src/migrate.cpp` 的 `run_migrations` 整体替换为：

```cpp
namespace {

struct Migration {
  int version;
  const char* file;
};

// 新增迁移只在这里加一行;版本号单调递增,已应用的跳过。
constexpr Migration kMigrations[] = {
    {1, "001_init.sql"},
    {2, "002_search_index.sql"},
};

}  // namespace

void run_migrations(const Config& cfg) {
  MysqlPool pool(parse_mysql_dsn(cfg.mysql_dsn), 1);
  auto lease = pool.acquire();
  lease.query(
      "CREATE TABLE IF NOT EXISTS im_schema_version ("
      "version INT NOT NULL PRIMARY KEY, applied_at BIGINT NOT NULL"
      ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4");

  for (const auto& migration : kMigrations) {
    const std::string version = std::to_string(migration.version);
    if (version_applied(lease, migration.version)) {
      log_info("migrated", {{"version", version}, {"skipped", "true"}});
      continue;
    }
    apply_sql(lease, read_file(cfg.migrations_dir + "/" + migration.file));
    lease.query("INSERT INTO im_schema_version (version, applied_at) VALUES (" + version + ", " +
                std::to_string(now_ms()) + ")");
    log_info("migrated", {{"version", version}});
  }
}
```

> 注意：原有的匿名 namespace 已在文件顶部，新增的 `Migration`/`kMigrations` 要放进**已有的**那个匿名 namespace（或就近再开一个，但 `run_migrations` 之前必须可见）。

- [x] **Step 3: 在测试库上跑两遍迁移，验证幂等**

Run:
```bash
cd imserver && docker compose -f docker-compose.test.yml run --rm test bash -c '
/src/build/imserver --migrate && /src/build/imserver --migrate && \
mysql -h$IM_MYSQL_HOST -u$IM_MYSQL_USER -p$IM_MYSQL_PASSWORD $IM_MYSQL_DATABASE \
  -e "SHOW INDEX FROM im_conversation" | grep idx_user_b'
```
（若测试镜像里 `imserver` 二进制路径不同，先按 `scripts/test.sh` 的方式 `cmake --build` 一次。）
Expected: 两遍都输出 `migrated version=2`（第二遍 `skipped=true`），最后一行能看到 `idx_user_b`。

- [x] **Step 4: 提交**

```bash
git add imserver/migrations/002_search_index.sql imserver/src/migrate.cpp
git commit -m "feat(imserver): 迁移器按版本表循环 + v2 会话 user_b 索引"
```

---

### Task 3: `MessageRepo::search` / `MessageService::search`

**Files:**
- Modify: `imserver/src/store/message_repo.h`（声明）、`imserver/src/store/message_repo.cpp`（实现）
- Modify: `imserver/src/service/message_service.h`、`imserver/src/service/message_service.cpp`
- Test: `imserver/tests/message_service_test.cpp`（DB 测试，已有该文件）

**Interfaces:**
- Consumes: `like_pattern()`（Task 1）、`im_blacklist`/`im_conversation_state` 表结构。
- Produces:
  - `std::vector<MessageRow> MessageRepo::search(MysqlPool::Lease&, uint64_t uid, const std::string& keyword, uint64_t before_id, int limit)`
  - `std::vector<MessageRow> MessageRepo::search(uint64_t uid, const std::string& keyword, uint64_t before_id, int limit)`
  - `std::vector<MessageRow> MessageService::search(uint64_t uid, const std::string& keyword, uint64_t before_id, int limit)`

- [x] **Step 1: 写失败测试（DB 级）**

在 `imserver/tests/message_service_test.cpp` 末尾追加（该文件已有 `MakeService()` 之类的夹具就先复用，没有就按下面写）：

```cpp
TEST(MessageServiceSearchTest, FindsOnlyMyUndeletedUnrevokedText) {
  const char* dsn = std::getenv("IM_TEST_MYSQL_DSN");
  ASSERT_NE(dsn, nullptr);
  MysqlPool pool(parse_mysql_dsn(dsn), 2);
  UserRepo users(pool);
  ConversationRepo conversations(pool);
  MessageRepo messages(pool);
  BlacklistRepo blacklist(pool);
  MessageService service(pool, users, conversations, messages, blacklist);

  const uint64_t base = 900000 + static_cast<uint64_t>(::getpid()) % 1000 * 10;
  const uint64_t me = base, peer = base + 1, stranger = base + 2;

  auto send = [&](uint64_t from, uint64_t to, const std::string& text) {
    SendRequest request;
    request.from = from;
    request.to = to;
    request.client_msg_id = "t-" + std::to_string(from) + "-" + text;
    request.text = text;
    service.send(request);
  };
  send(peer, me, "晚上吃火锅吗");
  send(me, peer, "火锅店在楼下");
  send(stranger, me, "火锅外卖到了");   // 别人发的也算「我参与的会话」
  send(me, stranger, "不吃火锅");
  send(peer, me, "今天天气不错");

  auto hits = service.search(me, "火锅", 0, 50);
  ASSERT_EQ(hits.size(), 4u);
  // 新 → 旧
  EXPECT_GT(hits[0].msg_id, hits[1].msg_id);

  // 撤回后不可见
  auto revoke_target = hits[0];
  service.revoke(me, revoke_target.msg_id);
  EXPECT_EQ(service.search(me, "火锅", 0, 50).size(), 3u);

  // 拉黑对端后,与他的会话全部不可见
  service.blacklist_add(me, peer);
  for (const auto& row : service.search(me, "火锅", 0, 50)) {
    EXPECT_NE(row.from_id, peer);
    EXPECT_NE(row.to_id, peer);
  }

  // 删除会话后不可见(只剩 stranger 的两条)
  service.delete_conversation(me, stranger);
  EXPECT_EQ(service.search(me, "火锅", 0, 50).size(), 0u);
}
```

- [x] **Step 2: 跑测试确认失败**

Run: `cd imserver && docker compose -f docker-compose.test.yml run --rm test bash -c "cmake -S /src -B /src/build -G Ninja >/dev/null && cmake --build /src/build 2>&1 | tail -5"`
Expected: 编译失败 `no member named 'search' in 'MessageService'`

- [x] **Step 3: 实现 repo 查询**

`message_repo.h` 增加：

```cpp
  /// 关键词搜索:只搜我参与的、未删除会话里的未撤回文本消息,按 msg_id 倒序。
  std::vector<MessageRow> search(MysqlPool::Lease& lease, uint64_t uid,
                                 const std::string& keyword, uint64_t before_id, int limit);
  std::vector<MessageRow> search(uint64_t uid, const std::string& keyword,
                                 uint64_t before_id, int limit);
```

`message_repo.cpp` 末尾追加（顶部 `#include "util/like.h"`）：

```cpp
std::vector<MessageRow> MessageRepo::search(MysqlPool::Lease& lease, uint64_t uid,
                                            const std::string& keyword, uint64_t before_id,
                                            int limit) {
  limit = std::clamp(limit, 1, 100);
  Stmt stmt(lease.get(),
            "SELECT m.msg_id,m.conv_id,m.seq,m.from_id,m.to_id,m.kind,m.body,"
            "m.client_msg_id,m.created_at,m.revoked_at "
            "FROM im_conversation c JOIN im_message m ON m.conv_id=c.id "
            "LEFT JOIN im_conversation_state s ON s.conv_id=c.id AND s.owner_id=? "
            "WHERE (c.user_a=? OR c.user_b=?) AND m.kind=1 AND m.revoked_at IS NULL "
            "AND (s.deleted IS NULL OR s.deleted=0) "
            "AND IF(c.user_a=?,c.user_b,c.user_a)<>0 "
            "AND NOT EXISTS (SELECT 1 FROM im_blacklist b WHERE b.owner_id=? "
            "AND b.peer_id=IF(c.user_a=?,c.user_b,c.user_a)) "
            "AND (?=0 OR m.msg_id<?) "
            "AND m.body LIKE ? ESCAPE '!' "
            "ORDER BY m.msg_id DESC LIMIT ?");
  stmt.bind_uint(0, uid);
  stmt.bind_uint(1, uid);
  stmt.bind_uint(2, uid);
  stmt.bind_uint(3, uid);
  stmt.bind_uint(4, uid);
  stmt.bind_uint(5, uid);
  stmt.bind_uint(6, before_id);
  stmt.bind_uint(7, before_id);
  stmt.bind_string(8, like_pattern(keyword));
  stmt.bind_uint(9, static_cast<uint64_t>(limit));
  stmt.execute();

  std::vector<MessageRow> rows;
  MYSQL_STMT* raw = stmt.raw();
  ...
}
```

> `Stmt` 目前只有 `execute()`（写语句）没有读接口。**先看 `stmt.h/.cpp`**：如果确实没有 `MYSQL_RES* result()` 之类的读方法，就改用现有的读路径——`lease.query()` 只能拼字符串，那么用 `lease.escape()` 转义关键词后拼 SQL（`lease.escape` 已处理引号与反斜杠，`like_pattern` 已处理 `%`/`_`/`!`），保持与 `find_by_client` 一致：

```cpp
  const auto escaped = lease.escape(like_pattern(keyword));
  auto* result = lease.query(std::string(kSelect) +
                             "WHERE msg_id IN (SELECT m.msg_id FROM im_conversation c "
                             "JOIN im_message m ON m.conv_id=c.id "
                             "LEFT JOIN im_conversation_state s ON s.conv_id=c.id AND s.owner_id=" +
                             std::to_string(uid) +
                             " WHERE (c.user_a=" + std::to_string(uid) +
                             " OR c.user_b=" + std::to_string(uid) + ") AND m.kind=1"
                             " AND m.revoked_at IS NULL AND (s.deleted IS NULL OR s.deleted=0)"
                             " AND IF(c.user_a=" + std::to_string(uid) +
                             ",c.user_b,c.user_a)<>0"
                             " AND NOT EXISTS (SELECT 1 FROM im_blacklist b WHERE b.owner_id=" +
                             std::to_string(uid) +
                             " AND b.peer_id=IF(c.user_a=" + std::to_string(uid) +
                             ",c.user_b,c.user_a))" +
                             (before_id > 0 ? " AND m.msg_id<" + std::to_string(before_id) : "") +
                             " AND m.body LIKE '" + escaped + "' ESCAPE '!'"
                             " ORDER BY m.msg_id DESC LIMIT " + std::to_string(limit) + ") "
                             "ORDER BY msg_id DESC");
  std::vector<MessageRow> rows;
  if (result != nullptr) {
    while (MYSQL_ROW values = mysql_fetch_row(result)) {
      rows.push_back(parse_row(values));
    }
    mysql_free_result(result);
  }
  return rows;
```

**二选一，不要两种都留**：`Stmt` 有读接口就用 prepared statement（推荐，免拼串）；没有就用上面的 `lease.query` 版本，并在 `message_repo.cpp` 顶部保留 `#include "util/like.h"`。

- [x] **Step 4: 实现 service 转发**

`message_service.h` 在 `list_messages` 后加声明：

```cpp
  std::vector<MessageRow> search(uint64_t uid, const std::string& keyword, uint64_t before_id,
                                 int limit);
```

`message_service.cpp` 实现（照 `list_messages` 的写法取 lease）：

```cpp
std::vector<MessageRow> MessageService::search(uint64_t uid, const std::string& keyword,
                                               uint64_t before_id, int limit) {
  auto lease = pool_.acquire();
  return messages_.search(lease, uid, keyword, before_id, limit);
}
```

- [x] **Step 5: 跑 DB 测试确认通过**

Run: `cd imserver && docker compose -f docker-compose.test.yml run --rm test bash -c "cmake -S /src -B /src/build -G Ninja >/dev/null && cmake --build /src/build >/dev/null && /src/build/im_db_tests --gtest_filter='MessageServiceSearchTest.*'"`
Expected: `[  PASSED  ] 1 test.`

- [x] **Step 6: 提交**

```bash
git add imserver/src/store/message_repo.h imserver/src/store/message_repo.cpp \
        imserver/src/service/message_service.h imserver/src/service/message_service.cpp \
        imserver/tests/message_service_test.cpp
git commit -m "feat(imserver): 消息关键词搜索查询(会话/撤回/拉黑/删除过滤)"
```

---

### Task 4: `GET /im/api/search` + 限流 + 集成测试

**Files:**
- Modify: `imserver/src/net/http_api.h`（限流成员与私有方法）、`imserver/src/net/http_api.cpp`（URL 解码、路由、响应）
- Create: `imserver/tests/integration/test_search.py`
- Modify: `imserver/scripts/test_http.sh:17-21`

**Interfaces:**
- Consumes: `MessageService::search`（Task 3）、`message_json` / `peer_id`（已有）。
- Produces: HTTP 契约 `GET /im/api/search?q&limit&before_id` → `{"items":[…],"has_more":bool}`；错误 `40101/42201/42901/50001`。

- [x] **Step 1: 写失败测试（集成）**

```python
# imserver/tests/integration/test_search.py
import asyncio
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

import jwt
import websockets

SECRET = os.environ["IM_JWT_SECRET"]
INTERNAL_SECRET = os.environ["IM_INTERNAL_SECRET"]
WS = os.environ.get("IM_TEST_WS", "ws://127.0.0.1:19100/im/ws")
HTTP = os.environ.get("IM_TEST_HTTP", "http://127.0.0.1:19101/im/api")


def token(uid: int) -> str:
    now = int(time.time())
    return jwt.encode(
        {"sub": f"u{uid}", "uid": uid, "iat": now, "exp": now + 3600, "jti": "test"},
        SECRET,
        algorithm="HS256",
    )


def search(uid: int, keyword: str, limit: int = 20, before_id: int = 0):
    query = {"q": keyword, "limit": str(limit)}
    if before_id:
        query["before_id"] = str(before_id)
    request = urllib.request.Request(
        HTTP + "/search?" + urllib.parse.urlencode(query),
        headers={"Authorization": f"Bearer {token(uid)}"},
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        return json.loads(response.read())


def status_of(uid: int, keyword: str) -> int:
    query = urllib.parse.urlencode({"q": keyword})
    request = urllib.request.Request(
        HTTP + "/search?" + query, headers={"Authorization": f"Bearer {token(uid)}"}
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


async def auth(uid: int):
    ws = await websockets.connect(WS)
    await ws.send(json.dumps({"v": 1, "type": "auth", "data": {"token": token(uid)}}))
    while True:
        message = json.loads(await asyncio.wait_for(ws.recv(), 3))
        if message["type"] == "auth_ok":
            return ws


async def recv(ws, type_):
    while True:
        message = json.loads(await asyncio.wait_for(ws.recv(), 3))
        if message["type"] == type_:
            return message


async def main():
    base = 300000 + (int(time.time() * 1000) + os.getpid()) % 100000
    me, peer = base, base + 1
    ws = await auth(peer)
    for index, text in enumerate(["晚上吃火锅吗", "火锅店在楼下", "今天天气不错"]):
        await ws.send(json.dumps({"v": 1, "type": "send", "id": f"s-{index}",
                                  "data": {"to": f"u{me}", "kind": "text", "text": text}}))
        await recv(ws, "ack")

    # 中文命中 + 新→旧 + peer 资料
    result = search(me, "火锅")
    assert [item["text"] for item in result["items"]] == ["火锅店在楼下", "晚上吃火锅吗"]
    assert result["items"][0]["peer"]["id"] == f"u{peer}"
    assert result["has_more"] is False

    # 分页游标
    first = search(me, "火锅", limit=1)
    assert first["has_more"] is True and len(first["items"]) == 1
    second = search(me, "火锅", limit=1, before_id=int(first["items"][0]["msg_id"]))
    assert [item["text"] for item in second["items"]] == ["晚上吃火锅吗"]

    # 无命中 / 空关键词 / 未认证
    assert search(me, "不存在")["items"] == []
    assert status_of(me, "   ") == 422
    anonymous = urllib.request.Request(HTTP + "/search?q=x")
    try:
        urllib.request.urlopen(anonymous, timeout=3)
        raise AssertionError("未认证应当 401")
    except urllib.error.HTTPError as error:
        assert error.code == 401

    # 撤回后不可见
    target = first["items"][0]["msg_id"]
    await ws.send(json.dumps({"v": 1, "type": "revoke", "id": "r-1", "data": {"msg_id": target}}))
    await recv(ws, "ack")
    assert all(item["msg_id"] != target for item in search(me, "火锅")["items"])

    # 限流:burst 20,连打 25 次应当出现 429
    codes = [status_of(me, "火锅") for _ in range(25)]
    assert 429 in codes

    await ws.close()


asyncio.run(main())
```

- [x] **Step 2: 跑测试确认失败**

Run: `cd imserver && docker compose -f docker-compose.test.yml run --rm test bash /src/scripts/test_http.sh`
Expected: `test_search.py` 报 `HTTP Error 404`（接口还没实现）

- [x] **Step 3: 实现 URL 解码与 trim（`http_api.cpp` 匿名 namespace）**

```cpp
int hex_value(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  return -1;
}

/// 百分号解码 + `+` 当空格(Web 端 URLSearchParams 就是这么编码空格的)。
std::string url_decode(const std::string& input) {
  std::string out;
  out.reserve(input.size());
  for (std::size_t i = 0; i < input.size(); ++i) {
    const char c = input[i];
    if (c == '+') {
      out.push_back(' ');
      continue;
    }
    if (c == '%' && i + 2 < input.size()) {
      const int high = hex_value(input[i + 1]);
      const int low = hex_value(input[i + 2]);
      if (high >= 0 && low >= 0) {
        out.push_back(static_cast<char>(high * 16 + low));
        i += 2;
        continue;
      }
    }
    out.push_back(c);
  }
  return out;
}

std::string trim_ascii(const std::string& input) {
  const auto begin = input.find_first_not_of(" \t\r\n");
  if (begin == std::string::npos) return "";
  const auto end = input.find_last_not_of(" \t\r\n");
  return input.substr(begin, end - begin + 1);
}
```

- [x] **Step 4: 限流成员（`http_api.h`）**

```cpp
#include <mutex>
#include <unordered_map>

#include "util/ratelimit.h"

// class HttpApi private:
  bool allow_search(uint64_t uid, int64_t now_ms);

  struct SearchBucket {
    TokenBucket bucket{1.0, 20.0};  // 60 次/分钟,burst 20
    int64_t seen_ms = 0;
  };
  std::mutex search_mutex_;
  std::unordered_map<uint64_t, SearchBucket> search_buckets_;
```

`http_api.cpp` 实现：

```cpp
bool HttpApi::allow_search(uint64_t uid, int64_t now_ms) {
  std::lock_guard<std::mutex> lock(search_mutex_);
  if (search_buckets_.size() > 4096) {
    for (auto it = search_buckets_.begin(); it != search_buckets_.end();) {
      it = (now_ms - it->second.seen_ms > 600000) ? search_buckets_.erase(it) : std::next(it);
    }
  }
  auto& bucket = search_buckets_[uid];
  bucket.seen_ms = now_ms;
  return bucket.bucket.allow(now_ms);
}
```

- [x] **Step 5: 路由放行 + 处理**

`route()` 里把路径白名单扩到三个：

```cpp
  if (target.path != "/im/api/conversations" && target.path != "/im/api/messages" &&
      target.path != "/im/api/search") {
    return error_response(req, http::status::not_found, 40401, "not found");
  }
```

在 `if (target.path == "/im/api/conversations") { ... }` 之后、`/im/api/messages` 之前插入：

```cpp
  if (target.path == "/im/api/search") {
    const int64_t now_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
                               std::chrono::system_clock::now().time_since_epoch())
                               .count();
    if (!allow_search(*uid, now_ms)) {
      return error_response(req, http::status::too_many_requests, 42901,
                            "搜索过于频繁,请稍后再试");
    }
    std::string keyword;
    if (const auto it = target.query.find("q"); it != target.query.end()) {
      keyword = trim_ascii(url_decode(it->second));
    }
    if (keyword.empty() || keyword.size() > 150) {
      return error_response(req, http::status::unprocessable_entity, 42201,
                            "关键词长度不合法");
    }
    const int limit = static_cast<int>(
        std::clamp<uint64_t>(query_uint(target, "limit", 20), 1, 50));
    const uint64_t before_id = query_uint(target, "before_id", 0);
    auto rows = messages_.search(*uid, keyword, before_id, limit + 1);
    const bool has_more = rows.size() > static_cast<std::size_t>(limit);
    if (has_more) {
      rows.resize(static_cast<std::size_t>(limit));
    }
    nlohmann::json items = nlohmann::json::array();
    for (const auto& row : rows) {
      nlohmann::json item = message_json(row, messages_.users(), messages_.signer());
      const uint64_t peer = row.from_id == *uid ? row.to_id : row.from_id;
      nlohmann::json profile = {{"id", peer_id(peer)}, {"nickname", ""}, {"avatar", ""}};
      if (auto user = messages_.users().get(peer)) {
        profile["nickname"] = user->nickname;
        profile["avatar"] = user->avatar;
      }
      item["peer"] = std::move(profile);
      items.push_back(std::move(item));
    }
    return json_response(req, http::status::ok, {{"items", items}, {"has_more", has_more}});
  }
```

- [x] **Step 6: 接进 `test_http.sh`**

在 `python3 /src/tests/integration/test_image.py` 之后加一行：

```bash
python3 /src/tests/integration/test_search.py
```

- [x] **Step 7: 跑全量 http 集成测试**

Run: `cd imserver && docker compose -f docker-compose.test.yml run --rm test bash /src/scripts/test_http.sh`
Expected: 四个 python 集成脚本全过（无 traceback，退出码 0）。

- [x] **Step 8: 提交**

```bash
git add imserver/src/net/http_api.h imserver/src/net/http_api.cpp \
        imserver/tests/integration/test_search.py imserver/scripts/test_http.sh
git commit -m "feat(imserver): GET /im/api/search 关键词搜索接口与限流"
```

---

### Task 5: 服务端文档（接口/设计/运维）

**Files:**
- Modify: `docs/api/im.md`（新增 6.4）
- Modify: `docs/superpowers/specs/2026-10-20-self-hosted-im-design.md`（§6 接口表、§6 错误码表）
- Modify: `docs/ops/imserver.md`（升级步骤加 `--migrate` 强调 + 搜索限流/已知限制）

**Interfaces:** 无代码产出；后续任务不改文档。

- [x] **Step 1: `docs/api/im.md` 追加 6.4**

按 6.2 的排版写：接口描述（自建后端专用，base = `user_sig.http_url`）、请求参数表（q/limit/before_id）、响应参数表（items 各字段 + peer）、请求示例（curl 带 `--data-urlencode`）、响应示例、错误码表（401/422/429/500）。

- [x] **Step 2: 设计 spec 补接口与错误码**

§6 的 HTTP 接口表加一行 `GET /im/api/search`；错误码表确认 `42901` 一行覆盖「发送过快/搜索过于频繁」。

- [x] **Step 3: ops 手册补三段**

1. 升级步骤：`docker compose run --rm imserver --migrate`（**v2 索引**）→ `up -d`；
2. 搜索限流 60 次/分钟；
3. 已知限制：LIKE 扫描，十万级消息后换 FULLTEXT/ES。

- [x] **Step 4: 提交**

```bash
git add docs/api/im.md docs/superpowers/specs/2026-10-20-self-hosted-im-design.md docs/ops/imserver.md
git commit -m "docs(im): 聊天记录搜索接口与运维说明"
```

---

### Task 6: App 能力位 / 客户端 / 模型

**Files:**
- Modify: `app/lib/im/im_client.dart`、`app/lib/im/self_im_client.dart`、`app/lib/im/tencent_im_client.dart`、`app/lib/im/routing_im_client.dart`
- Modify: `app/test/support/fake_im_client.dart`
- Test: `app/test/im/self_im_client_test.dart`（已有）、`app/test/im/im_client_test.dart`

**Interfaces:**
- Produces:
  - `ImCapabilities({required bool image, bool search = false})`
  - `class ImSearchHit { msgId, seq, peerId, text, timestamp, peerName?, peerAvatar? }`
  - `class ImSearchResult { List<ImSearchHit> items; bool hasMore }`
  - `ImClient.searchMessages(String keyword, {int limit = 20, String? beforeId})`
  - `ImClient.fetchHistory(String peerId, {int count = 50, int? beforeSeq})`
  - `ChatMessage.seq`（默认 0）

- [x] **Step 1: 写失败测试（self client 的 HTTP 参数）**

`app/test/im/self_im_client_test.dart` 里按现有假 `SelfHttpClient` 的写法追加：

```dart
  test('searchMessages 把关键词与游标带给 /search', () async {
    final http = _RecordingHttp({
      '/search': {
        'items': [
          {
            'msg_id': '42',
            'seq': 7,
            'from': 'u9',
            'to': 'u1',
            'ts': 1761465600000,
            'kind': 'text',
            'text': '晚上吃火锅吗',
            'peer': {'id': 'u9', 'nickname': '阿九', 'avatar': 'https://a/9.png'},
          },
        ],
        'has_more': true,
      },
    });
    final client = SelfImClient(httpClient: http);
    await client.init(_bootstrap());
    final result = await client.searchMessages('火锅', limit: 10, beforeId: '99');
    expect(http.calls.last, '/search?q=火锅&limit=10&before_id=99');
    expect(result.items.single.text, '晚上吃火锅吗');
    expect(result.items.single.peerId, 'u9');
    expect(result.items.single.peerName, '阿九');
    expect(result.items.single.seq, 7);
    expect(result.hasMore, isTrue);
  });

  test('fetchHistory 传 beforeSeq 时带上 before_seq', () async {
    final http = _RecordingHttp({'/messages': {'items': []}});
    final client = SelfImClient(httpClient: http);
    await client.init(_bootstrap());
    await client.fetchHistory('u9', count: 50, beforeSeq: 12);
    expect(http.calls.last, '/messages?peer=u9&limit=50&before_seq=12');
  });
```

（`_RecordingHttp` 就是测试文件里现有的假 HTTP 客户端；没有就照 `SelfHttpClient` 接口写一个，把每次 `get(path, query)` 记成 `'$path?${Uri(queryParameters: query).query}'`。）

- [x] **Step 2: 跑测试确认失败**

Run: `cd app && ../flutter/bin/flutter.bat test test/im/self_im_client_test.dart`
Expected: 编译失败 `The method 'searchMessages' isn't defined`

- [x] **Step 3: 改 `im_client.dart`**

```dart
class ImCapabilities {
  const ImCapabilities({required this.image, this.search = false});
  final bool image;
  final bool search;
}

/// 一条搜索命中(只可能是文本消息)。
class ImSearchHit {
  const ImSearchHit({
    required this.msgId,
    required this.seq,
    required this.peerId,
    required this.text,
    required this.timestamp,
    this.peerName,
    this.peerAvatar,
  });

  final String msgId;
  final int seq;
  final String peerId;
  final String text;
  final int timestamp;
  final String? peerName;
  final String? peerAvatar;
}

class ImSearchResult {
  const ImSearchResult({required this.items, required this.hasMore});
  final List<ImSearchHit> items;
  final bool hasMore;
}
```

`ChatMessage` 增加 `this.seq = 0` 与 `final int seq;`（`copyWith` 里透传 `seq: seq`）。

`ImClient` 里：

```dart
  /// 搜索聊天记录(仅自建后端支持;腾讯抛 [ImException] 42202)。
  Future<ImSearchResult> searchMessages(String keyword, {int limit = 20, String? beforeId}) =>
      throw const ImException(42202, '当前聊天服务暂不支持搜索');

  /// 单聊历史消息,按时间正序(旧 → 新);[beforeSeq] 用于往前翻页。
  Future<List<ChatMessage>> fetchHistory(String peerId, {int count = 50, int? beforeSeq});
```

- [x] **Step 4: 改 `self_im_client.dart`**

`fetchHistory` 加参数并带 `before_seq`；新增 `searchMessages`（见规格 §5.1，字段映射到 `ImSearchHit`）；`_messageFromJson` 增加 `seq: (json['seq'] as num?)?.toInt() ?? 0`；`capabilities` 改为 `const ImCapabilities(image: true, search: true)`。

- [x] **Step 5: 改腾讯与路由客户端**

- `tencent_im_client.dart`：`capabilities => const ImCapabilities(image: true)`（search 默认 false）；`fetchHistory` 签名加 `{int? beforeSeq}` 但忽略。
- `routing_im_client.dart`：`capabilities` 兜底 `const ImCapabilities(image: false)` 不变；`fetchHistory` 透传 `beforeSeq`；新增
  ```dart
  @override
  Future<ImSearchResult> searchMessages(String keyword, {int limit = 20, String? beforeId}) =>
      _active?.searchMessages(keyword, limit: limit, beforeId: beforeId) ??
      Future.error(const ImException(42202, '当前聊天服务暂不支持搜索'));
  ```

- [x] **Step 6: 扩展假客户端**

`app/test/support/fake_im_client.dart`：`fetchHistory` 加 `int? beforeSeq`；新增字段

```dart
  /// 搜索命中(按关键词过滤,测搜索页用)。
  List<ImSearchHit> searchHits = [];
  ImSearchResult Function(String keyword, int limit, String? beforeId)? searchHandler;
  bool searchCapability = true;
  Object? searchError;
```

`capabilities => ImCapabilities(image: imageCapability, search: searchCapability)`；实现：

```dart
  @override
  Future<ImSearchResult> searchMessages(String keyword, {int limit = 20, String? beforeId}) async {
    log.add('search:$keyword');
    if (searchError != null) throw searchError!;
    final handler = searchHandler;
    if (handler != null) return handler(keyword, limit, beforeId);
    final items = searchHits.where((hit) => hit.text.contains(keyword)).toList();
    return ImSearchResult(items: items.take(limit).toList(), hasMore: items.length > limit);
  }
```

- [x] **Step 7: 跑测试确认通过**

Run: `cd app && ../flutter/bin/flutter.bat analyze && ../flutter/bin/flutter.bat test test/im`
Expected: `No issues found!` + 全部通过

- [x] **Step 8: 提交**

```bash
git add app/lib/im app/test/im app/test/support/fake_im_client.dart
git commit -m "feat(app): IM 搜索能力位、searchMessages 与消息 seq"
```

---

### Task 7: App 搜索页 + 路由 + 入口

**Files:**
- Create: `app/lib/features/chat/search_page.dart`
- Modify: `app/lib/router.dart`（`/search`）、`app/lib/features/chat/chats_page.dart`（标题右侧图标）
- Test: `app/test/features/chat/search_page_test.dart`

**Interfaces:**
- Consumes: `ImClient.searchMessages`、`ImSearchHit`（Task 6）；`AppSubPageBar`、`AppAvatar`、`AppEmptyState`、`AppErrorView`、`AppSkeleton`、`AppText`/`AppColors`/`AppSpacing`。
- Produces: 路由名 `/search`；结果行 key `search.hit:<msgId>`、输入框 key `search.input`、加载更多 key `search.more`。

- [x] **Step 1: 写失败测试**

```dart
// app/test/features/chat/search_page_test.dart
import 'package:flutter_test/flutter_test.dart';
import 'package:chatapp_app/features/chat/search_page.dart';
import 'package:chatapp_app/im/im_client.dart';
import '../../support/harness.dart';
import '../../support/scripted_adapter.dart';

void main() {
  testWidgets('输入关键词后展示命中并高亮关键词', (tester) async {
    final adapter = ScriptedAdapter();
    final fake = await pumpApp(tester, adapter, prefs: {'auth.refresh': 'r'});
    fake.searchHits = [
      const ImSearchHit(msgId: '42', seq: 7, peerId: 'u9', text: '晚上吃火锅吗',
          timestamp: 1761465600000, peerName: '阿九'),
    ];
    await tester.pumpWidget(const _SearchHost());
    await tester.enterText(find.byKey(const Key('search.input')), '火锅');
    await tester.pump(const Duration(milliseconds: 350)); // 过防抖
    await pumpFrames(tester);
    expect(find.byKey(const Key('search.hit:42')), findsOneWidget);
    expect(find.textContaining('火锅'), findsWidgets);
  });

  testWidgets('无命中显示空态', (tester) async {
    final adapter = ScriptedAdapter();
    final fake = await pumpApp(tester, adapter, prefs: {'auth.refresh': 'r'});
    fake.searchHits = const [];
    await tester.pumpWidget(const _SearchHost());
    await tester.enterText(find.byKey(const Key('search.input')), '不存在');
    await tester.pump(const Duration(milliseconds: 350));
    await pumpFrames(tester);
    expect(find.text('没有找到相关消息'), findsOneWidget);
  });
}
```

`_SearchHost` 直接返回 `MaterialApp(home: SearchPage())`（页面本身不依赖路由），需要包 `ProviderScope`——`pumpApp` 已经起了整个 App，这里改成用 `pumpApp` 后 `tester.pumpWidget` 会替换整棵树导致 provider 丢失。**正确做法**：像 `chats_page_test.dart` 一样用 `pumpApp` 进消息页，再点搜索图标进 `/search`（走真实路由，顺便验证入口）。所以测试写成：

```dart
    await pumpApp(tester, adapter, prefs: {'auth.refresh': 'r'});
    fake.conversations = [...];               // 让消息页有内容/无内容都行
    await pumpFrames(tester);
    await tester.tap(find.byKey(const Key('chats.search')));
    await pumpFrames(tester);
    await tester.enterText(find.byKey(const Key('search.input')), '火锅');
```

- [x] **Step 2: 跑测试确认失败**

Run: `cd app && ../flutter/bin/flutter.bat test test/features/chat/search_page_test.dart`
Expected: 编译失败 `search_page.dart: No such file`

- [x] **Step 3: 实现 `search_page.dart`**

要点（完整实现按此结构写）：

```dart
class SearchPage extends ConsumerStatefulWidget {
  const SearchPage({super.key});
  @override
  ConsumerState<SearchPage> createState() => _SearchPageState();
}

class _SearchPageState extends ConsumerState<SearchPage> {
  final _input = TextEditingController();
  Timer? _debounce;
  List<ImSearchHit> _hits = const [];
  bool _loading = false;
  bool _hasMore = false;
  String? _error;
  String _keyword = '';
  int _requestSeq = 0;

  @override
  void dispose() {
    _debounce?.cancel();
    _input.dispose();
    super.dispose();
  }

  void _onChanged(String value) {
    _debounce?.cancel();
    final keyword = value.trim();
    if (keyword.isEmpty) {
      setState(() { _hits = const []; _keyword = ''; _error = null; _hasMore = false; _loading = false; });
      return;
    }
    _debounce = Timer(const Duration(milliseconds: 300), () => _run(keyword));
  }

  Future<void> _run(String keyword, {bool append = false}) async {
    final client = ref.read(imClientProvider);
    final seq = ++_requestSeq;
    setState(() { _loading = true; _error = null; if (!append) _keyword = keyword; });
    try {
      final result = await client.searchMessages(keyword, limit: 20,
          beforeId: append && _hits.isNotEmpty ? _hits.last.msgId : null);
      if (!mounted || seq != _requestSeq) return;   // 丢弃过期响应
      setState(() {
        _hits = append ? [..._hits, ...result.items] : result.items;
        _hasMore = result.hasMore;
        _loading = false;
      });
    } catch (error) {
      if (!mounted || seq != _requestSeq) return;
      setState(() { _error = apiMessageOf(error); _loading = false; });
    }
  }
  ...
}
```

布局：`Column` → `AppSubPageBar(title: '搜索')` + 输入框（`AppTextField` 或 `TextField` + `Key('search.input')`，`autofocus: true`，`textInputAction: search`）+ 结果区（`_loading && _hits.isEmpty` → `AppSkeleton`；`_error != null` → `AppErrorView(onRetry: () => _run(_keyword))`；空 → `AppEmptyState(title: '没有找到相关消息')`；否则 `ListView.builder`）。

结果行：

```dart
ListTile(
  key: Key('search.hit:${hit.msgId}'),
  onTap: () => context.push('/chat/${hit.peerId}?focus=${hit.msgId}'),
  leading: AppAvatar(imageUrl: hit.peerAvatar, size: 44, fallbackText: hit.peerName ?? hit.peerId),
  title: Text(hit.peerName ?? hit.peerId, style: AppText.subtitle),
  subtitle: RichText(text: TextSpan(children: _highlight(hit.text, _keyword))),
  trailing: Text(formatMessageTime(DateTime.fromMillisecondsSinceEpoch(hit.timestamp)),
      style: AppText.micro.copyWith(color: AppColors.text3)),
)
```

`_highlight` 返回 `TextSpan` 列表：按关键词（忽略大小写）切分，命中段 `AppText.body.copyWith(color: AppColors.brand, fontWeight: FontWeight.w600)`，其余 `AppText.body.copyWith(color: AppColors.text2)`；文本过长时前后各截 20 字（`…` 前缀）。

底部「加载更多」：`if (_hasMore) TextButton(key: const Key('search.more'), onPressed: () => _run(_keyword, append: true), child: const Text('加载更多'))`。

- [x] **Step 4: 挂路由与入口**

`router.dart`：import `search_page.dart`，在 `/chat/:peerId` 后加

```dart
      GoRoute(path: '/search', builder: (context, state) => const SearchPage()),
```

`chats_page.dart`：标题行改成 `Row`，标题 `Expanded`，右侧

```dart
            if (ref.read(imClientProvider).capabilities.search)
              IconButton(
                key: const Key('chats.search'),
                onPressed: () => context.push('/search'),
                icon: const Icon(Icons.search_rounded, color: AppColors.text1),
              ),
```

- [x] **Step 5: 跑测试确认通过**

Run: `cd app && ../flutter/bin/flutter.bat test test/features/chat/search_page_test.dart test/features/chat/chats_page_test.dart && ../flutter/bin/flutter.bat analyze`
Expected: 全过 + `No issues found!`

- [x] **Step 6: 提交**

```bash
git add app/lib/features/chat/search_page.dart app/lib/router.dart \
        app/lib/features/chat/chats_page.dart app/test/features/chat/search_page_test.dart
git commit -m "feat(app): 聊天记录搜索页与消息页入口"
```

---

### Task 8: App 聊天页定位到消息

**Files:**
- Modify: `app/lib/features/chat/chat_controller.dart`（`loadOlder`）
- Modify: `app/lib/features/chat/chat_page.dart`（`focusMsgId`、滚动定位、高亮）
- Modify: `app/lib/features/chat/widgets/message_bubble.dart`（`highlight`）
- Modify: `app/lib/router.dart`（读 `focus` query）
- Test: `app/test/features/chat/chat_page_test.dart`（已有，追加用例）

**Interfaces:**
- Consumes: `ChatMessage.seq`、`ImClient.fetchHistory(beforeSeq:)`。
- Produces: `ChatController.loadOlder({required String untilMsgId, int maxPages = 5})`；`ChatPage({required String peerId, String? focusMsgId})`；高亮 key `chat.highlight:<msgId>`。

- [x] **Step 1: 写失败测试**

在 `chat_page_test.dart` 追加：

```dart
  testWidgets('带 focus 进聊天页会回溯历史并高亮目标消息', (tester) async {
    final adapter = ScriptedAdapter();
    final fake = await pumpApp(tester, adapter, prefs: {'auth.refresh': 'r'});
    fake.conversations = [ImConversation(peerId: 'u9', unreadCount: 0, showName: '阿九')];
    // 最近 50 条里没有目标,目标在第一页更早的历史里
    fake.history['u9'] = List.generate(50, (i) => ChatMessage(
        msgId: 'm$i', seq: i + 100, peerId: 'u9', isSelf: i.isEven,
        timestamp: 1761465600000 + i * 1000, kind: ChatMessageKind.text, text: '消息 $i'));
    fake.olderHistory['u9'] = {
      100: [ChatMessage(msgId: 'target', seq: 99, peerId: 'u9', isSelf: false,
          timestamp: 1761465000000, kind: ChatMessageKind.text, text: '上周的地址')],
    };
    await pumpApp(tester, adapter, prefs: {'auth.refresh': 'r'}, imClient: fake);
    // 直接进 /chat/u9?focus=target(见下:用 router 跳转)
    ...
    expect(find.byKey(const Key('chat.highlight:target')), findsOneWidget);
  });
```

> 假客户端要支持按 `beforeSeq` 返回不同页：给 `FakeImClient` 加
> `Map<String, Map<int, List<ChatMessage>>> olderHistory`，`fetchHistory` 在 `beforeSeq != null` 时返回 `olderHistory[peerId]?[beforeSeq] ?? const []`。

- [x] **Step 2: 跑测试确认失败**

Run: `cd app && ../flutter/bin/flutter.bat test test/features/chat/chat_page_test.dart`
Expected: 失败（没有 `chat.highlight:*`）

- [x] **Step 3: `ChatController.loadOlder`**

```dart
  /// 往前翻历史,直到找到 [untilMsgId](或翻到顶 / 到页数上限)。
  Future<void> loadOlder({required String untilMsgId, int maxPages = 5}) async {
    var current = state.value ?? const <ChatMessage>[];
    if (current.isEmpty) return;
    final client = ref.read(imClientProvider);
    for (var page = 0; page < maxPages; page++) {
      if (current.any((item) => item.msgId == untilMsgId)) return;
      final oldestSeq = current.first.seq;
      if (oldestSeq <= 1) return;
      final older = await client.fetchHistory(peerId, count: 50, beforeSeq: oldestSeq);
      if (older.isEmpty) return;
      final known = {for (final item in current) item.msgId};
      current = [...older.where((item) => !known.contains(item.msgId)), ...current];
      state = AsyncValue.data(current);
      if (older.length < 50) return;
    }
  }
```

- [x] **Step 4: `ChatPage` 定位与高亮**

```dart
class ChatPage extends ConsumerStatefulWidget {
  const ChatPage({super.key, required this.peerId, this.focusMsgId,
      this.pickImage = pickChatImageFromGallery});
  final String? focusMsgId;
  ...
}
```

状态里加：

```dart
  final _scroll = ScrollController();
  final _itemKeys = <String, GlobalKey>{};
  String? _highlightMsgId;
  bool _focusStarted = false;

  @override
  void dispose() { _scroll.dispose(); ... }
```

`ListView.builder` 加 `controller: _scroll`，itemBuilder 里 `ChatMessageItem` 的 `Builder` 外层加 `key: _itemKeys.putIfAbsent(message.msgId, GlobalKey.new)`，并把 `highlight: message.msgId == _highlightMsgId` 传给 `MessageBubble`。

数据分支里，首次拿到非空列表后触发：

```dart
                if (!_focusStarted && widget.focusMsgId != null && items.isNotEmpty) {
                  _focusStarted = true;
                  WidgetsBinding.instance.addPostFrameCallback((_) => _focusOn(widget.focusMsgId!));
                }
```

```dart
  Future<void> _focusOn(String msgId) async {
    final controller = ref.read(chatProvider(widget.peerId).notifier);
    await controller.loadOlder(untilMsgId: msgId);
    if (!mounted) return;
    await WidgetsBinding.instance.endOfFrame;
    for (var attempt = 0; attempt < 24; attempt++) {
      if (_itemKeys[msgId]?.currentContext != null) break;
      if (!_scroll.hasClients) return;
      final position = _scroll.position;
      final next = (position.pixels + position.viewportDimension * 0.8)
          .clamp(0.0, position.maxScrollExtent);
      if (next <= position.pixels + 1) break;
      _scroll.jumpTo(next);
      await WidgetsBinding.instance.endOfFrame;
    }
    final context = _itemKeys[msgId]?.currentContext;
    if (context == null) return;
    await Scrollable.ensureVisible(context,
        alignment: 0.5, duration: const Duration(milliseconds: 250), curve: Curves.easeOut);
    if (!mounted) return;
    setState(() => _highlightMsgId = msgId);
    Timer(const Duration(milliseconds: 1500), () {
      if (mounted) setState(() => _highlightMsgId = null);
    });
  }
```

`router.dart` 的聊天路由改为：

```dart
      GoRoute(
        path: '/chat/:peerId',
        builder: (context, state) => ChatPage(
          peerId: state.pathParameters['peerId']!,
          focusMsgId: state.uri.queryParameters['focus'],
        ),
      ),
```

- [x] **Step 5: `MessageBubble` 支持高亮**

```dart
class MessageBubble extends StatelessWidget {
  const MessageBubble({..., this.highlight = false});
  final bool highlight;
```

外层包一层：

```dart
    return AnimatedContainer(
      key: highlight ? Key('chat.highlight:${message.msgId}') : null,
      duration: const Duration(milliseconds: 300),
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(
        color: highlight ? AppColors.brand.withValues(alpha: 0.08) : Colors.transparent,
        borderRadius: BorderRadius.circular(AppRadius.card),
      ),
      child: <原来的气泡>,
    );
```

- [x] **Step 6: 跑测试确认通过**

Run: `cd app && ../flutter/bin/flutter.bat test test/features/chat && ../flutter/bin/flutter.bat analyze`
Expected: 全过 + 零告警

- [x] **Step 7: 提交**

```bash
git add app/lib/features/chat/chat_controller.dart app/lib/features/chat/chat_page.dart \
        app/lib/features/chat/widgets/message_bubble.dart app/lib/router.dart \
        app/test/features/chat app/test/support/fake_im_client.dart
git commit -m "feat(app): 聊天页按 focus 回溯历史并高亮命中消息"
```

---

### Task 9: Web 客户端层（类型 / self / tencent / routing / store）

**Files:**
- Modify: `web/src/im/types.ts`、`web/src/im/self/client.ts`、`web/src/im/self/map.ts`、`web/src/im/client.ts`、`web/src/im/routing.ts`
- Modify: `web/src/stores/chat.ts`（`loadOlder`、`search`）
- Test: `web/tests/unit/im-self.spec.ts`、`web/tests/unit/chat-store.spec.ts`

**Interfaces:**
- Produces: `ImSearchHit`、`ImSearchResult`、`ImCapabilities.search`、`ImClient.searchMessages`、`ImClient.fetchHistory(peerId, count?, beforeSeq?)`、`ChatMessage.seq`、`useChatStore().loadOlder(peerId, untilMsgId)`。

- [x] **Step 1: 写失败测试**

`web/tests/unit/im-self.spec.ts` 追加：注入假 transport + 桩 `fetch`，断言 `searchMessages` 打到 `/im/api/search?q=…&limit=20` 并映射出 `ImSearchHit`。
`web/tests/unit/chat-store.spec.ts` 追加：`loadOlder` 用 `beforeSeq` 调 `fetchHistory` 并合并去重。

- [x] **Step 2: 跑测试确认失败**

Run: `cd web && npm run test:run -- tests/unit/im-self.spec.ts`
Expected: TS 报 `searchMessages` 不存在

- [x] **Step 3: 类型与实现**

`types.ts`：

```ts
export interface ImCapabilities {
  image: boolean
  search: boolean
}

export interface ImSearchHit {
  msgId: string
  seq: number
  peerId: string
  peerName: string
  peerAvatar: string | null
  text: string
  timestamp: number
}

export interface ImSearchResult {
  items: ImSearchHit[]
  hasMore: boolean
}

// ChatMessage 增加
//   /** 会话内序号,回溯翻页用(腾讯后端恒为 0) */
//   seq: number

// ImClient 增加
//   searchMessages(keyword: string, limit?: number, beforeId?: string): Promise<ImSearchResult>
//   fetchHistory(peerId: string, count?: number, beforeSeq?: number): Promise<ChatMessage[]>
```

`self/client.ts`：`capabilities = { image: true, search: true }`；`fetchHistory(peerId, count = 50, beforeSeq?)` 带 `before_seq`；新增

```ts
  async searchMessages(keyword: string, limit = 20, beforeId?: string): Promise<ImSearchResult> {
    const query: Record<string, string> = { q: keyword, limit: String(limit) }
    if (beforeId) query.before_id = beforeId
    const data = await this.get('/search', query)
    const items = ((data.items ?? []) as Record<string, unknown>[]).map((item) => {
      const peer = (item.peer ?? {}) as Record<string, unknown>
      return {
        msgId: String(item.msg_id ?? ''),
        seq: Number(item.seq ?? 0),
        peerId: String(peer.id ?? ''),
        peerName: String(peer.nickname ?? ''),
        peerAvatar: (peer.avatar as string | null) ?? null,
        text: String(item.text ?? ''),
        timestamp: Number(item.ts ?? 0),
      }
    })
    return { items, hasMore: data.has_more === true }
  }
```

`self/map.ts`：`messageFromJson` 增加 `seq: Number(json.seq ?? 0)`。
`client.ts`（腾讯）：`capabilities: { image: true, search: false }`，新增 `async searchMessages(): Promise<ImSearchResult> { throw new Error('当前聊天服务暂不支持搜索') }`，`fetchHistory(peerId, count = 20, beforeSeq?)` 忽略第三参。
`routing.ts`：两个方法透传给 `active`。

`stores/chat.ts`：

```ts
  /** 往前翻历史,直到找到 untilMsgId(最多 5 页)。 */
  async function loadOlder(peerId: string, untilMsgId: string, maxPages = 5): Promise<void> {
    await ensureConnected()
    let list = messagesOf(peerId)
    for (let page = 0; page < maxPages; page++) {
      if (list.some((item) => item.msgId === untilMsgId)) return
      const oldestSeq = list[0]?.seq ?? 0
      if (oldestSeq <= 1) return
      const older = await client.fetchHistory(peerId, 50, oldestSeq)
      if (!older.length) return
      list = mergeMessages(list, older)
      messages.value = { ...messages.value, [peerId]: list }
      if (older.length < 50) return
    }
  }
```

（`return` 出去时把 `loadOlder` 加进 store 的 return 对象。）

- [x] **Step 4: 跑测试确认通过**

Run: `cd web && npm run test:run -- tests/unit/im-self.spec.ts tests/unit/chat-store.spec.ts && npm run type-check`
Expected: 全过 + 零 TS 错误

- [x] **Step 5: 提交**

```bash
git add web/src/im web/src/stores/chat.ts web/tests/unit
git commit -m "feat(web): IM 搜索能力位与 searchMessages/loadOlder"
```

---

### Task 10: Web 搜索页 + 路由 + 入口

**Files:**
- Create: `web/src/features/chat/SearchPage.vue`
- Modify: `web/src/router/routes.ts`、`web/src/features/chat/ChatsPage.vue`
- Test: `web/tests/component/search-page.spec.ts`

**Interfaces:**
- Consumes: `useChatStore` / `getImClient().searchMessages`（Task 9）。
- Produces: 路由 `search`（`/search`）；DOM 钩子 `.search__hit`、`[data-msg-id]`、`.search__more`。

- [x] **Step 1: 写失败测试**（挂载页面 + 假 client，断言防抖后渲染命中、点击跳 `/chat/u9?focus=42`、空态）

- [x] **Step 2: 跑测试确认失败**

Run: `cd web && npm run test:run -- tests/component/search-page.spec.ts`
Expected: 找不到模块

- [x] **Step 3: 实现页面**

结构：`<section class="search">` → 头部（返回 `RouterLink` 到 `chats` + `AppInput` 搜索框，`v-model` + `watch` 300ms 防抖）→ 结果区（骨架 / `AppErrorView` / `AppEmpty` / `ul.search__list`）。每行：

```vue
      <li v-for="hit in hits" :key="hit.msgId">
        <button type="button" class="search__hit" :data-msg-id="hit.msgId"
                @click="router.push({ name: 'chat', params: { peerId: hit.peerId }, query: { focus: hit.msgId } })">
          <AppAvatar :src="hit.peerAvatar" :name="hit.peerName || hit.peerId" :size="44" />
          <span class="search__main">
            <span class="search__name">{{ hit.peerName || hit.peerId }}</span>
            <span class="search__snippet" v-html="highlight(hit.text)" />
          </span>
          <span class="search__time">{{ timeOf(hit.timestamp) }}</span>
        </button>
      </li>
```

`highlight()` 先 `escapeHtml` 再包 `<mark>`（**必须先转义**，否则搜索结果就是 XSS 面）；关键词里的正则元字符要转义。

- [x] **Step 4: 路由与入口**

`routes.ts` 在 `chat` 前加 `{ path: '/search', name: 'search', component: () => import('@/features/chat/SearchPage.vue') }`；
`ChatsPage.vue` 标题行加按钮（`v-if="searchEnabled"`，`@click="router.push({name:'search'})"`，`aria-label="搜索聊天记录"`）。

- [x] **Step 5: 跑测试与检查**

Run: `cd web && npm run test:run -- tests/component/search-page.spec.ts tests/unit/routes-resolve.spec.ts && npm run type-check && npm run lint`
Expected: 全过；`routes-resolve` 若断言了路由清单，同步补 `search`。

- [x] **Step 6: 提交**

```bash
git add web/src/features/chat/SearchPage.vue web/src/router/routes.ts \
        web/src/features/chat/ChatsPage.vue web/tests/component/search-page.spec.ts
git commit -m "feat(web): 聊天记录搜索页与消息页入口"
```

---

### Task 11: Web 聊天页定位到消息

**Files:**
- Modify: `web/src/features/chat/ChatPage.vue`
- Test: `web/tests/component/chat-page.spec.ts`（已有，追加用例）

**Interfaces:**
- Consumes: `useChatStore().loadOlder`、`route.query.focus`。
- Produces: 命中气泡 `data-msg-id` 与 `.chat__bubble--hit` 类（高亮 1.5s）。

- [x] **Step 1: 写失败测试**：假 client 最近一页不含目标、`fetchHistory(peer, 50, seq)` 返回目标页 → 挂载 `ChatPage` 且 `route.query.focus='target'` → `await flushPromises()` → 断言 `[data-msg-id="target"]` 带 `chat__bubble--hit`。

- [x] **Step 2: 跑测试确认失败**

Run: `cd web && npm run test:run -- tests/component/chat-page.spec.ts`
Expected: 找不到 `chat__bubble--hit`

- [x] **Step 3: 实现**

```ts
const route = useRoute()
const focusId = typeof route.query.focus === 'string' ? route.query.focus : ''
const hitId = ref('')
let highlightTimer: ReturnType<typeof setTimeout> | undefined

async function focusMessage(msgId: string): Promise<void> {
  await store.loadOlder(props.peerId, msgId)
  await nextTick()
  const element = document.querySelector<HTMLElement>(`[data-msg-id="${CSS.escape(msgId)}"]`)
  if (!element) return
  element.scrollIntoView({ block: 'center', behavior: 'smooth' })
  hitId.value = msgId
  clearTimeout(highlightTimer)
  highlightTimer = setTimeout(() => (hitId.value = ''), 1500)
}
```

`onMounted` 里 `await store.openConversation(...)` 之后：`if (focusId) await focusMessage(focusId)`；`onUnmounted` 清 timer。

`MessageBubble` 透传 `:hit="row.message.msgId === hitId"`，组件里 `:data-msg-id="message.msgId"` 与 `class="message__bubble--hit"`（样式：主色 8% 底，300ms 过渡）。

- [x] **Step 4: 跑测试确认通过**

Run: `cd web && npm run test:run -- tests/component/chat-page.spec.ts && npm run type-check && npm run lint`
Expected: 全过

- [x] **Step 5: 提交**

```bash
git add web/src/features/chat/ChatPage.vue web/src/features/chat/MessageBubble.vue \
        web/tests/component/chat-page.spec.ts
git commit -m "feat(web): 聊天页按 focus 回溯历史并高亮命中消息"
```

---

### Task 12: 全量回归与收尾

- [x] **Step 1: imserver 全量**

Run: `cd imserver && docker compose -f docker-compose.test.yml run --rm test bash /src/scripts/test.sh`
Expected: unit / db / http 全绿（含 `test_search.py`）

- [x] **Step 2: App 全量**

Run: `cd app && ../flutter/bin/flutter.bat analyze && ../flutter/bin/flutter.bat test`
Expected: 零告警 + 全部通过（新增用例计入总数）

- [x] **Step 3: Web 全量**

Run: `cd web && npm run type-check && npm run lint && npm run test:coverage`
Expected: 零错误/零告警/覆盖率过门槛

- [x] **Step 4: 后端全量**（本次未改 Django，但按纪律跑一遍确认没被误伤）

Run: `cd chatapp && python manage.py test`
Expected: 全绿

- [x] **Step 5: 更新 CLAUDE.md 的「下一步」段落**

加一句：聊天记录搜索已交付（`GET /im/api/search`，App/Web 双端定位），并保留「切换日观察 + 配置」为待办。

- [x] **Step 6: 提交并记录**

```bash
git add -A
git commit -m "docs: 聊天记录搜索交付记录"
```

---

## 自查记录

- 规格覆盖：§4 服务端（Task 1–4）、§5.1 能力位与接口（Task 6/9）、§5.2 搜索页（Task 7/10）、§5.3 定位（Task 8/11）、§6 错误码（Task 4）、§7 测试（各任务 + Task 12）、§8 文档（Task 5）。
- 类型一致性：`ImSearchHit`/`ImSearchResult` 在 Task 6 与 Task 9 字段同名同序；`beforeSeq`（App/Web 客户端）与 `before_seq`（HTTP 参数）对应关系在 Task 3/4 明确；`ChatMessage.seq` 两端都加。
- 已知待定：`Stmt` 是否提供读结果接口需在执行时确认（Task 3 Step 3 给了两条互斥路径，不构成占位符）。

---

---

## 执行记录

- **2026-10-27 全量回归通过后统一勾选**:此前执行未回写 checkbox,本次按交付结果补齐(Task 1–4 合并在同一个提交里)。
- 提交链路:`2cdaae2` 规格/计划 → `e9c65ab` imserver 搜索(Task 1–4)→ `7a0ced3` App 能力位/客户端(Task 6)→ `e31abc5` App 搜索页 + 定位(Task 7–8)→ `1c37029` Web 客户端/store(Task 9)→ `d010016` Web 搜索页 + 入口(Task 10)→ `fccc686` Web 定位高亮(Task 11)。
- 门禁结果:后端 486 / App 398(`flutter analyze` 零告警)/ Web 361(覆盖率 82.9 / 77.0 / 77.7 / 85.2)/ imserver unit 20 + db 12 + http 集成(含 `test_search.py` 与 `im_e2e.py`)全绿。
- 执行期额外修复(计划外,但为入口可见性/可测性所必需):
  1. **Web 能力位改由 store 响应式暴露**——`getImClient()` 每次返回未 `init` 的 `RoutingImClient`,`capabilities` 恒为兜底 `false`,直接读它会让搜索入口(以及 10-21 起就隐藏的图片入口)永远不显示;`ChatPage` 同步改用 `store.capabilities`。
  2. **`.gitattributes` 固定 `*.sh` 为 LF**——Windows 上 `core.autocrlf=true` 检出成 CRLF 后,容器里 `set -euo pipefail` 报 `invalid option name`,imserver 测试整套起不来。