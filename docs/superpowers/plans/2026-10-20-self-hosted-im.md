# 自建 IM（C++ 服务端）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 C++ 自建 IM 服务端替换腾讯云 IM，覆盖文本单聊、离线补拉、会话/未读/已读、撤回、拉黑、系统通知，并让 Flutter/Web/Django 在一个开关下双跑、可回退。

**Architecture:** 单个 C++ 进程同时提供 WebSocket（实时帧）与 HTTP（历史/会话/内部管理 API），消息落 MySQL（会话级 `seq` 保证顺序与幂等），Redis 存在线态与封禁键。Django 只签发 IM token、按开关决定后端、通过 HMAC 内部 API 触发副作用；客户端按 `/im/user_sig` 返回的 `backend` 选择腾讯或自建实现。

**Tech Stack:** C++20 / CMake / Boost.Asio + Beast / nlohmann-json / MySQL 8 / Redis 7 / OpenSSL；Django 5.2 + DRF + PyJWT；Flutter 3.47（web_socket_channel + Dio）；Vue 3 + TypeScript + Vitest。

**Spec:** `docs/superpowers/specs/2026-10-20-self-hosted-im-design.md`

## Global Constraints

- C++ 标准 **C++20**；CMake ≥ 3.22；构建与测试统一在 **Ubuntu 24.04 容器**内，不在 Windows MinGW 下编译。
- 时间字段一律**毫秒 Unix 时间戳**；对外 `msg_id` / `client_msg_id` 一律**字符串**，`seq` / `ts` / `uid` 为数字。
- 文本上限 **2000 字符**，单帧上限 **8192 字节**；`client_msg_id` 1–64 字符，限 `[A-Za-z0-9_-]`。
- 鉴权：IM token 为 **HS256 JWT**，claims `sub`（`u<uid>`）、`uid`、`iat`、`exp`、`jti`；密钥 `IM_JWT_SECRET` 与 Django `IM_SELF_SECRET` 一致。
- 内部 API 只监听 `127.0.0.1`，HMAC-SHA256 覆盖 `ts + "\n" + METHOD + "\n" + path + "\n" + body`，时间偏差 ≤ 60 秒。
- 所有 SQL 用**预处理语句**；日志**禁止**记录 token、消息正文、手机号。
- 消息幂等键 `UNIQUE(from_id, client_msg_id)`；会话顺序键 `UNIQUE(conv_id, seq)`。
- 测试用 Docker Compose：MySQL `127.0.0.1:13306`、Redis `127.0.0.1:16379`；不得复用开发库。
- 新增/修改 `.py` 必须补模块与函数/类 docstring，公开函数带参数写 `Args:`（`CommentCoverageTests`）。
- 任何 `/api/v1` 接口改动必须在同一次改动内更新 `docs/api/`（`ApiDocsCoverageTests`）。
- Flutter `flutter analyze` 零告警；Web `vue-tsc` 零错误、`eslint --max-warnings 0` 零告警。
- 每步全绿再进下一步；提交前缀：`feat(imserver):` / `test(imserver):` / `feat(im):` / `test(im):` / `feat(app/im):` / `feat(web/im):` / `docs(im):`。

## 文件结构

**C++ 服务端（新建 `imserver/`）**

| 文件 | 责任 |
|---|---|
| `imserver/CMakeLists.txt` | 目标：`imcore` 静态库 + `imserver` 可执行 + `im_unit_tests` / `im_db_tests` |
| `imserver/Dockerfile.dev` / `Dockerfile` | 开发镜像（编译+测试依赖）与多阶段发布镜像 |
| `imserver/docker-compose.test.yml` | MySQL 8 + Redis 7（13306/16379） |
| `imserver/scripts/test.sh` | 容器内 cmake + build + ctest |
| `imserver/src/config.{h,cpp}` | env 读取、DSN 解析、fail fast |
| `imserver/src/util/log.{h,cpp}` | JSON 行日志（stdout） |
| `imserver/src/auth/token.{h,cpp}` | JWT 签发/校验（OpenSSL HMAC） |
| `imserver/src/net/ws_server.{h,cpp}` | Beast WebSocket 会话、首帧鉴权、心跳、写队列 |
| `imserver/src/net/http_api.{h,cpp}` | Beast HTTP：`/im/api/*`、`/internal/*` |
| `imserver/src/service/session_registry.{h,cpp}` | uid→连接、在线 Redis、踢人 |
| `imserver/src/service/message_service.{h,cpp}` | 发送事务、历史、撤回、已读、删会话 |
| `imserver/src/store/models.h` | `UserRow` / `ConversationRow` / `MessageRow` / `StateRow` |
| `imserver/src/store/mysql_pool.{h,cpp}` | 连接池、事务 RAII、预处理语句封装 |
| `imserver/src/store/user_repo.{h,cpp}` | `im_user` 读写 |
| `imserver/src/store/conversation_repo.{h,cpp}` | 会话、state、未读/已读/删除 |
| `imserver/src/store/message_repo.{h,cpp}` | 消息插入/查询/撤回/删除 |
| `imserver/src/store/blacklist_repo.{h,cpp}` | 拉黑关系 |
| `imserver/src/store/redis_client.{h,cpp}` | hiredis 封装 |
| `imserver/src/main.cpp` | 装配与信号退出 |
| `imserver/migrations/001_init.sql` | 建表 + 系统通知账号 |
| `imserver/tests/*.cpp` | gtest 单测 |
| `imserver/tests/integration/*.py` | Python 端到端脚本 |

**Django**

| 文件 | 责任 |
|---|---|
| `chatapp/im/self_client.py` | 内部 API 客户端（HMAC、永不抛异常） |
| `chatapp/im/backend.py` | `use_self_im(user)` / `self_enabled_for(identifier)` |
| `chatapp/im/token.py` | IM JWT 签发/校验 |
| `chatapp/im/client.py` | 保留腾讯实现；公开函数入口按账号灰度分发 |
| `chatapp/im/views.py` | `user_sig` 双分支 + 灰度 |
| `chatapp/im/tasks.py` | 仅 `ban_notice` 传 `block=True` |
| `chatapp/config/settings.py` | `IM_BACKEND` / `IM_SELF_*` 配置 |
| `chatapp/appconfig/*` | `GET /api/v1/app/config`（最小版本拦截） |

**Flutter**

| 文件 | 责任 |
|---|---|
| `app/lib/im/im_bootstrap.dart` | 引导包模型（backend/token/wsUrl/httpUrl） |
| `app/lib/im/routing_im_client.dart` | 按 backend 选实现，事件透传 |
| `app/lib/im/self_im_client.dart` | 自建实现（连接/重连/收发/历史） |
| `app/lib/im/self_transport.dart` | 传输抽象 + WebSocket 实现 |
| `app/lib/im/im_client.dart` | `init(ImBootstrap)` + `capabilities` |
| `app/lib/im/im_repository.dart` | 解析新字段 |
| `app/lib/im/im_manager.dart` | 用引导包登录 |
| `app/lib/core/app_config.dart` | 版本配置拉取与比较 |
| `app/lib/features/auth/splash_page.dart` | 版本阻塞页 |

**Web**

| 文件 | 责任 |
|---|---|
| `web/src/im/self/transport.ts` | 浏览器 WebSocket 抽象 |
| `web/src/im/self/client.ts` | 自建实现 |
| `web/src/im/self/map.ts` | 帧 → 领域模型 |
| `web/src/im/routing.ts` | 按 backend 选实现 |
| `web/src/im/types.ts` | `ImBootstrap` / `capabilities` |
| `web/src/stores/chat.ts` | 用引导包连接 |
| `web/src/features/app/ForceUpdate.vue` | 版本阻塞页 |

**工具/文档**

`tools/im_e2e.py`、`tools/im_load.py`、`docs/api/im.md`、`docs/api/app.md`、`docs/pitfalls/im.md`、`docs/ops/imserver.md`。

---

### Task 1: 构建骨架、配置与日志

**Files:**
- Create: `imserver/CMakeLists.txt`、`imserver/Dockerfile.dev`、`imserver/.dockerignore`、`imserver/scripts/test.sh`
- Create: `imserver/src/config.h`、`imserver/src/config.cpp`、`imserver/src/util/log.h`、`imserver/src/util/log.cpp`、`imserver/src/main.cpp`
- Test: `imserver/tests/config_test.cpp`、`imserver/tests/CMakeLists.txt`

**Interfaces:**
- Consumes: 无
- Produces:
  - `struct MysqlDsn { std::string user, password, host, database; int port; }`
  - `MysqlDsn parse_mysql_dsn(const std::string&)`
  - `struct Config { ...; static Config from_env(); static Config from_map(const std::map<std::string,std::string>&); }`
  - `void log_info(std::string_view event, std::initializer_list<std::pair<std::string,std::string>> fields)`

- [ ] **Step 1: 写失败的配置测试**

`imserver/tests/config_test.cpp`:

```cpp
#include <gtest/gtest.h>
#include "config.h"

TEST(ConfigTest, ParsesMysqlDsn) {
  const auto dsn = parse_mysql_dsn("mysql://imserver:secret@127.0.0.1:13306/chatapp_im");
  EXPECT_EQ(dsn.user, "imserver");
  EXPECT_EQ(dsn.password, "secret");
  EXPECT_EQ(dsn.host, "127.0.0.1");
  EXPECT_EQ(dsn.port, 13306);
  EXPECT_EQ(dsn.database, "chatapp_im");
}

TEST(ConfigTest, RejectsMissingJwtSecret) {
  std::map<std::string, std::string> env{
      {"IM_MYSQL_DSN", "mysql://u:p@127.0.0.1:3306/db"},
      {"IM_INTERNAL_SECRET", "internal"}};
  EXPECT_THROW(Config::from_map(env), std::runtime_error);
}

TEST(ConfigTest, AppliesDefaults) {
  std::map<std::string, std::string> env{
      {"IM_MYSQL_DSN", "mysql://u:p@127.0.0.1:3306/db"},
      {"IM_JWT_SECRET", "jwt"},
      {"IM_INTERNAL_SECRET", "internal"}};
  const auto cfg = Config::from_map(env);
  EXPECT_EQ(cfg.listen_ws, "127.0.0.1:9100");
  EXPECT_EQ(cfg.listen_http, "127.0.0.1:9101");
  EXPECT_EQ(cfg.io_threads, 2);
  EXPECT_EQ(cfg.max_frame, 8192u);
}
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
docker build -f imserver/Dockerfile.dev -t imserver-dev imserver
docker run --rm -v "$($PWD.Path)\imserver:/src" imserver-dev bash /src/scripts/test.sh
```

Expected: FAIL —— `config.h: No such file or directory`。

- [ ] **Step 3: 写构建、配置与日志**

`imserver/CMakeLists.txt`:

```cmake
cmake_minimum_required(VERSION 3.22)
project(imserver LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_package(Boost 1.83 REQUIRED COMPONENTS system)
find_package(OpenSSL REQUIRED)
find_package(nlohmann_json REQUIRED)
find_package(PkgConfig REQUIRED)
pkg_check_modules(MYSQLCLIENT REQUIRED mysqlclient)
pkg_check_modules(HIREDIS REQUIRED hiredis)

add_library(imcore STATIC
  src/config.cpp
  src/util/log.cpp
)
target_include_directories(imcore PUBLIC src)
target_link_libraries(imcore PUBLIC OpenSSL::Crypto nlohmann_json::nlohmann_json)
target_compile_options(imcore PRIVATE -Wall -Wextra -Wpedantic)

add_executable(imserver src/main.cpp)
target_link_libraries(imserver PRIVATE imcore)

enable_testing()
add_subdirectory(tests)
```

`imserver/src/config.h`:

```cpp
#pragma once
#include <cstddef>
#include <map>
#include <string>
#include <vector>

struct MysqlDsn {
  std::string user;
  std::string password;
  std::string host = "127.0.0.1";
  int port = 3306;
  std::string database;
};

MysqlDsn parse_mysql_dsn(const std::string& dsn);

struct Config {
  std::string listen_ws = "127.0.0.1:9100";
  std::string listen_http = "127.0.0.1:9101";
  std::string mysql_dsn;
  std::string redis_url = "redis://127.0.0.1:6379/2";
  std::string jwt_secret;
  std::string internal_secret;
  std::string migrations_dir = "/usr/local/share/imserver/migrations";
  std::vector<std::string> allowed_origins;
  int io_threads = 2;
  int db_threads = 4;
  int db_pool = 8;
  std::size_t max_frame = 8192;
  std::size_t text_max = 2000;

  static Config from_env();
  static Config from_map(const std::map<std::string, std::string>& env);
};
```

`imserver/src/config.cpp` 要点：`from_map` 读 `IM_LISTEN_WS`、`IM_LISTEN_HTTP`、`IM_MYSQL_DSN`、
`IM_REDIS_URL`、`IM_JWT_SECRET`、`IM_INTERNAL_SECRET`、`IM_MIGRATIONS_DIR`、
`IM_ALLOWED_ORIGINS`（逗号分隔）、`IM_IO_THREADS`、`IM_DB_THREADS`、
`IM_DB_POOL`、`IM_MAX_FRAME`、`IM_TEXT_MAX`；`mysql_dsn`、`jwt_secret`、
`internal_secret` 缺失抛 `std::runtime_error("missing IM_...")`。`parse_mysql_dsn`
按 `mysql://user:pass@host:port/db` 解析，端口缺省 3306，格式不对抛
`std::invalid_argument`。

`imserver/src/util/log.h`:

```cpp
#pragma once
#include <initializer_list>
#include <string>
#include <string_view>
#include <utility>

void log_info(std::string_view event,
              std::initializer_list<std::pair<std::string, std::string>> fields = {});
void log_error(std::string_view event,
               std::initializer_list<std::pair<std::string, std::string>> fields = {});
```

`log.cpp` 用 `nlohmann::json` 输出一行 JSON（`ts`、`level`、`event` + fields），
互斥锁保护 `std::cout`，`std::endl` 刷新。

`imserver/src/main.cpp`（本任务只验证装配）：

```cpp
#include <iostream>
#include "config.h"
#include "util/log.h"

int main(int argc, char** argv) {
  try {
    const auto cfg = Config::from_env();
    log_info("startup", {{"listen_ws", cfg.listen_ws}, {"listen_http", cfg.listen_http},
                          {"io_threads", std::to_string(cfg.io_threads)}});
    if (argc > 1 && std::string(argv[1]) == "--migrate") {
      std::cerr << "migrate not implemented yet\n";
      return 2;
    }
    return 0;
  } catch (const std::exception& e) {
    std::cerr << "fatal: " << e.what() << "\n";
    return 1;
  }
}
```

`imserver/Dockerfile.dev`:

```dockerfile
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake ninja-build pkg-config git python3 python3-pip \
    libboost-all-dev nlohmann-json3-dev libssl-dev \
    libmysqlclient-dev libhiredis-dev libgtest-dev \
 && rm -rf /var/lib/apt/lists/*
RUN pip3 install --break-system-packages --no-cache-dir websockets PyJWT pymysql redis
WORKDIR /src
```

`imserver/.dockerignore`:

```
build/
.git/
```

`imserver/scripts/test.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
cmake -S /src -B /src/build -G Ninja -DCMAKE_BUILD_TYPE=Debug
cmake --build /src/build
ctest --test-dir /src/build -L unit --output-on-failure
```

`imserver/tests/CMakeLists.txt`:

```cmake
find_package(GTest REQUIRED)
include(GoogleTest)
add_executable(im_unit_tests config_test.cpp)
target_link_libraries(im_unit_tests PRIVATE imcore GTest::gtest_main)
gtest_discover_tests(im_unit_tests PROPERTIES LABELS unit)
```

单测（`unit` 标签）不连库；连库用例单独打 `db` 标签，只在
`test_integration.sh` 里跑。

- [ ] **Step 4: 跑测试确认通过**

```powershell
docker run --rm -v "$($PWD.Path)\imserver:/src" imserver-dev bash /src/scripts/test.sh
```

Expected: `100% tests passed, 0 tests failed out of 3`。

- [ ] **Step 5: 提交**

```bash
git add imserver
git commit -m "feat(imserver): 构建骨架、配置与日志"
```

---

### Task 2: MySQL/Redis 连接池与建表迁移

**Files:**
- Create: `imserver/migrations/001_init.sql`、`imserver/docker-compose.test.yml`
- Create: `imserver/src/store/mysql_pool.h`、`imserver/src/store/mysql_pool.cpp`、`imserver/src/store/redis_client.h`、`imserver/src/store/redis_client.cpp`
- Modify: `imserver/src/main.cpp`（实现 `--migrate`）、`imserver/CMakeLists.txt`
- Test: `imserver/tests/store_test.cpp`、`imserver/scripts/test_integration.sh`

**Interfaces:**
- Consumes: `Config`、`MysqlDsn`、`log_*`
- Produces:
  - `class MysqlPool { class Lease { MYSQL* get(); void begin(); void commit(); void rollback(); }; Lease acquire(); }`
  - `class RedisClient { bool setex(key, ttl_s, value); std::optional<std::string> get(key); bool del(key); long long incr(key); bool ping(); }`
  - `void run_migrations(const Config&)`

- [ ] **Step 1: 写建表 SQL**

`imserver/migrations/001_init.sql`:

```sql
CREATE TABLE IF NOT EXISTS im_schema_version (
  version INT NOT NULL PRIMARY KEY,
  applied_at BIGINT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS im_user (
  user_id BIGINT UNSIGNED NOT NULL PRIMARY KEY,
  nickname VARCHAR(64) NOT NULL DEFAULT '',
  avatar_url VARCHAR(512) NOT NULL DEFAULT '',
  updated_at BIGINT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS im_conversation (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  user_a BIGINT UNSIGNED NOT NULL,
  user_b BIGINT UNSIGNED NOT NULL,
  last_seq BIGINT UNSIGNED NOT NULL DEFAULT 0,
  last_msg_id BIGINT UNSIGNED NULL,
  last_msg_at BIGINT NOT NULL DEFAULT 0,
  created_at BIGINT NOT NULL,
  UNIQUE KEY uk_pair (user_a, user_b)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS im_conversation_state (
  owner_id BIGINT UNSIGNED NOT NULL,
  conv_id BIGINT UNSIGNED NOT NULL,
  unread INT UNSIGNED NOT NULL DEFAULT 0,
  read_seq BIGINT UNSIGNED NOT NULL DEFAULT 0,
  deleted TINYINT NOT NULL DEFAULT 0,
  updated_at BIGINT NOT NULL,
  PRIMARY KEY (owner_id, conv_id),
  KEY idx_owner_updated (owner_id, updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS im_message (
  msg_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  conv_id BIGINT UNSIGNED NOT NULL,
  seq BIGINT UNSIGNED NOT NULL,
  from_id BIGINT UNSIGNED NOT NULL,
  to_id BIGINT UNSIGNED NOT NULL,
  kind TINYINT NOT NULL,
  body TEXT NOT NULL,
  client_msg_id VARCHAR(64) NOT NULL,
  created_at BIGINT NOT NULL,
  revoked_at BIGINT NULL,
  UNIQUE KEY uk_conv_seq (conv_id, seq),
  UNIQUE KEY uk_from_client (from_id, client_msg_id),
  KEY idx_conv_msg (conv_id, msg_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS im_blacklist (
  owner_id BIGINT UNSIGNED NOT NULL,
  peer_id BIGINT UNSIGNED NOT NULL,
  created_at BIGINT NOT NULL,
  PRIMARY KEY (owner_id, peer_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT IGNORE INTO im_user (user_id, nickname, avatar_url, updated_at)
VALUES (0, '系统通知', '', 0);
```

- [ ] **Step 2: 写集成测试（先失败）**

`imserver/tests/store_test.cpp`:

```cpp
#include <gtest/gtest.h>
#include <cstdlib>
#include "store/mysql_pool.h"
#include "store/redis_client.h"

TEST(StoreTest, TablesAndSystemUserExist) {
  const char* dsn = std::getenv("IM_TEST_MYSQL_DSN");
  ASSERT_NE(dsn, nullptr);
  MysqlPool pool(parse_mysql_dsn(dsn), 2);
  auto lease = pool.acquire();
  auto* res = lease.query("SELECT nickname FROM im_user WHERE user_id=0");
  ASSERT_NE(res, nullptr);
  MYSQL_ROW row = mysql_fetch_row(res);
  ASSERT_NE(row, nullptr);
  EXPECT_STREQ(row[0], "系统通知");
  mysql_free_result(res);
}

TEST(StoreTest, RedisSetGetDel) {
  const char* url = std::getenv("IM_TEST_REDIS_URL");
  ASSERT_NE(url, nullptr);
  RedisClient redis(url);
  ASSERT_TRUE(redis.setex("im:test:key", 30, "v"));
  ASSERT_EQ(redis.get("im:test:key").value_or(""), "v");
  ASSERT_TRUE(redis.del("im:test:key"));
  EXPECT_FALSE(redis.get("im:test:key").has_value());
}
```

`imserver/docker-compose.test.yml`:

```yaml
services:
  mysql:
    image: mysql:8.0
    environment:
      MYSQL_ROOT_PASSWORD: root
      MYSQL_DATABASE: chatapp_im
      MYSQL_USER: imserver
      MYSQL_PASSWORD: imserver
    ports: ["13306:3306"]
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "127.0.0.1", "-uroot", "-proot"]
      interval: 3s
      retries: 20
  redis:
    image: redis:7
    ports: ["16379:6379"]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 3s
      retries: 20
  test:
    build:
      context: .
      dockerfile: Dockerfile.dev
    volumes:
      - .:/src
      - ..:/repo
    working_dir: /src
    depends_on:
      mysql: {condition: service_healthy}
      redis: {condition: service_healthy}
    environment:
      IM_MYSQL_DSN: mysql://imserver:imserver@mysql:3306/chatapp_im
      IM_REDIS_URL: redis://redis:6379/2
      IM_JWT_SECRET: test-jwt-secret
      IM_INTERNAL_SECRET: test-internal-secret
      IM_MIGRATIONS_DIR: /src/migrations
    command: bash /src/scripts/test_integration.sh
```

`test` 服务与 MySQL/Redis 同网络，容器内用 `mysql:3306` / `redis:6379`，
不依赖宿主机端口；宿主机端口只用于手工排查。

- [ ] **Step 3: 跑测试确认失败**

```powershell
docker compose -f imserver/docker-compose.test.yml run --rm test bash /src/scripts/test.sh
```

Expected: FAIL —— `store/mysql_pool.h: No such file or directory`。

- [ ] **Step 4: 实现连接池、Redis 与迁移**

`MysqlPool` 用 `mysql_init/mysql_real_connect` 建 `db_pool` 条连接，`acquire()`
用 `std::mutex + std::condition_variable` 借出，`Lease` 析构归还；`begin/commit/
rollback` 直接 `mysql_query("START TRANSACTION")` 等。`Lease::query(sql)` 调
`mysql_real_query` + `mysql_store_result`，仅供测试/迁移；业务查询一律走
`mysql_stmt_*` 预处理（后续 Task 的 repo 内实现）。

`RedisClient` 解析 `redis://host:port/db`，`redisConnect` 后 `SELECT db`；
`setex` 用 `redisCommand(ctx, "SETEX %s %d %s", ...)`，`get` 返回
`std::optional<std::string>`，`incr` 返回 `long long`；连接失败构造时抛
`std::runtime_error`。

`run_migrations(cfg)`：

1. 连接 `cfg.mysql_dsn`；
2. `CREATE TABLE IF NOT EXISTS im_schema_version ...`；
3. 查 `SELECT version FROM im_schema_version`，若没有 1，则读取
   `cfg.migrations_dir + "/001_init.sql"`，按 `;` 切分逐条执行（跳过空语句），
   成功后 `INSERT INTO im_schema_version VALUES (1, <now_ms>)`；
4. 打印 `log_info("migrated", {{"version","1"}})`。

`main.cpp` 的 `--migrate` 调 `run_migrations(cfg)` 后返回 0。

`CMakeLists.txt` 的 `imcore` 源文件追加 `src/store/mysql_pool.cpp`、
`src/store/redis_client.cpp`；`imcore` 以 `PUBLIC` 链接
`${MYSQLCLIENT_LIBRARIES}`、`${HIREDIS_LIBRARIES}` 并加上两者 include 目录，
保证 `imserver` 与 `im_db_tests` 都能链到。

`imserver/scripts/test_integration.sh`：

```bash
#!/usr/bin/env bash
set -euo pipefail
cmake -S /src -B /src/build -G Ninja -DCMAKE_BUILD_TYPE=Debug
cmake --build /src/build
/src/build/imserver --migrate
export IM_TEST_MYSQL_DSN="$IM_MYSQL_DSN"
export IM_TEST_REDIS_URL="$IM_REDIS_URL"
ctest --test-dir /src/build -L db --output-on-failure
```

`tests/CMakeLists.txt` 追加：

```cmake
add_executable(im_db_tests store_test.cpp)
target_link_libraries(im_db_tests PRIVATE imcore GTest::gtest_main)
gtest_discover_tests(im_db_tests PROPERTIES LABELS db)
```

- [ ] **Step 5: 跑测试确认通过**

```powershell
docker compose -f imserver/docker-compose.test.yml run --rm test bash /src/scripts/test_integration.sh
```

Expected: `100% tests passed`，且输出 `{"event":"migrated","version":"1"}`。

- [ ] **Step 6: 提交**

```bash
git add imserver
git commit -m "feat(imserver): MySQL/Redis 连接池与建表迁移"
```

---

### Task 3: JWT 签发与校验

**Files:**
- Create: `imserver/src/auth/token.h`、`imserver/src/auth/token.cpp`
- Test: `imserver/tests/token_test.cpp`（加入 `tests/CMakeLists.txt`）
- Modify: `imserver/CMakeLists.txt`（`imcore` 加 `src/auth/token.cpp`）

**Interfaces:**
- Consumes: 无
- Produces:
  - `struct TokenClaims { uint64_t uid; std::string sub; int64_t iat; int64_t exp; std::string jti; };`
  - `std::optional<TokenClaims> verify_token(std::string_view token, std::string_view secret, int64_t now_ms);`
  - `std::string mint_token(uint64_t uid, std::string_view secret, int64_t now_ms, int64_t ttl_s);`

- [ ] **Step 1: 写失败测试**

`imserver/tests/token_test.cpp`:

```cpp
#include <gtest/gtest.h>
#include "auth/token.h"

namespace {
constexpr int64_t kNow = 1760000000000;  // 2025-10-09T...
constexpr const char* kSecret = "0123456789abcdef0123456789abcdef";
}

TEST(TokenTest, MintThenVerify) {
  const auto token = mint_token(9, kSecret, kNow, 3600);
  const auto claims = verify_token(token, kSecret, kNow + 1000);
  ASSERT_TRUE(claims.has_value());
  EXPECT_EQ(claims->uid, 9u);
  EXPECT_EQ(claims->sub, "u9");
  EXPECT_EQ(claims->exp, kNow / 1000 + 3600);
}

TEST(TokenTest, RejectsExpired) {
  const auto token = mint_token(9, kSecret, kNow, 60);
  EXPECT_FALSE(verify_token(token, kSecret, kNow + 61000).has_value());
}

TEST(TokenTest, RejectsTamperedPayload) {
  auto token = mint_token(9, kSecret, kNow, 3600);
  const auto dot = token.find('.');
  token[dot + 2] = token[dot + 2] == 'A' ? 'B' : 'A';
  EXPECT_FALSE(verify_token(token, kSecret, kNow).has_value());
}

TEST(TokenTest, RejectsWrongSecret) {
  const auto token = mint_token(9, kSecret, kNow, 3600);
  EXPECT_FALSE(verify_token(token, "ffffffffffffffffffffffffffffffff", kNow).has_value());
}

TEST(TokenTest, RejectsSubUidMismatch) {
  const auto token = mint_token(9, kSecret, kNow, 3600);
  // 手工把 payload 的 sub 改成 u10 再签名，模拟伪造
  const auto forged = forge_token_with_sub(token, "u10", kSecret);
  EXPECT_FALSE(verify_token(forged, kSecret, kNow).has_value());
}
```

`forge_token_with_sub` 在测试文件里用 OpenSSL 实现（复制 `mint_token` 的
base64url + HMAC 逻辑，payload 固定 `{"sub":"u10","uid":9,...}`）。

- [ ] **Step 2: 跑测试确认失败**

```powershell
docker run --rm -v "$($PWD.Path)\imserver:/src" imserver-dev bash /src/scripts/test.sh
```

Expected: FAIL —— `auth/token.h: No such file or directory`。

- [ ] **Step 3: 实现**

`CMakeLists.txt` 的 `imcore` 源文件追加 `src/auth/token.cpp`；`tests/CMakeLists.txt`
的 `im_unit_tests` 源文件追加 `token_test.cpp`。

`token.h` 如接口所示。`token.cpp`：

- `base64url_encode/decode`（无填充，`-`/`_`）；
- `mint_token`：header `{"alg":"HS256","typ":"JWT"}`，payload
  `{"sub":"u<uid>","uid":<uid>,"iat":<秒>,"exp":<秒>,"jti":"<16 位随机 hex>"}`；
  `HMAC(EVP_sha256(), secret, ..., signing_input, ...)`；
- `verify_token`：
  1. 按 `.` 切 3 段，段数不对返回 `nullopt`；
  2. 解 header，校验 `alg=="HS256"`；
  3. 重算 HMAC，`CRYPTO_memcmp` 常量时间比较；
  4. 解 payload，读 `sub/uid/iat/exp/jti`；
  5. `now_ms/1000 > exp` 或 `iat > now+60` 返回 `nullopt`；
  6. `sub != "u" + std::to_string(uid)` 返回 `nullopt`；
  7. 成功返回 claims。

`jti` 用 `std::random_device` + `std::mt19937_64` 生成 16 位 hex，不参与校验。

- [ ] **Step 4: 跑测试确认通过**

```powershell
docker run --rm -v "$($PWD.Path)\imserver:/src" imserver-dev bash /src/scripts/test.sh
```

Expected: `TokenTest.*` 全 PASS。

- [ ] **Step 5: 提交**

```bash
git add imserver
git commit -m "feat(imserver): IM token 的 HS256 签发与校验"
```

---

### Task 4: WebSocket 会话、首帧鉴权、互踢与心跳

**Files:**
- Create: `imserver/src/net/ws_server.h`、`imserver/src/net/ws_server.cpp`、`imserver/src/service/session_registry.h`、`imserver/src/service/session_registry.cpp`、`imserver/src/util/ratelimit.h`、`imserver/src/util/ratelimit.cpp`
- Modify: `imserver/src/main.cpp`、`imserver/CMakeLists.txt`
- Test: `imserver/tests/integration/test_ws.py`、`imserver/tests/ratelimit_test.cpp`、`imserver/scripts/test_ws.sh`

**Interfaces:**
- Consumes: `Config`、`verify_token`、`RedisClient`、`log_*`
- Produces:
  - `class WsServer { WsServer(Config, SessionRegistry&); void start(); void stop(); }`
  - `class SessionRegistry { void register_session(uint64_t uid, std::shared_ptr<WsSession>); void unregister(uint64_t uid, WsSession*); void kick(uint64_t uid, std::string reason); bool is_online(uint64_t uid); size_t online_count(); }`
  - `class TokenBucket { TokenBucket(double rate_per_sec, double burst); bool allow(int64_t now_ms); }`

- [ ] **Step 1: 写失败的端到端测试**

`imserver/tests/integration/test_ws.py`:

```python
import asyncio
import json
import os
import time

import jwt
import websockets

SECRET = os.environ["IM_JWT_SECRET"]
WS = os.environ.get("IM_TEST_WS", "ws://127.0.0.1:19100/im/ws")


def token(uid: int) -> str:
    now = int(time.time())
    return jwt.encode({"sub": f"u{uid}", "uid": uid, "iat": now, "exp": now + 3600,
                       "jti": "test"}, SECRET, algorithm="HS256")


async def recv_until(ws, type_):
    while True:
        msg = json.loads(await asyncio.wait_for(ws.recv(), 3))
        if msg["type"] == type_:
            return msg


async def main():
    a = await websockets.connect(WS)
    await a.send(json.dumps({"v": 1, "type": "auth", "data": {"token": token(1)}}))
    ok = await recv_until(a, "auth_ok")
    assert ok["data"]["uid"] == 1

    # 第二处登录：旧连接被踢
    b = await websockets.connect(WS)
    await b.send(json.dumps({"v": 1, "type": "auth", "data": {"token": token(1)}}))
    kicked = await recv_until(a, "kicked")
    assert kicked["data"]["reason"] == "multi_device"

    await b.send(json.dumps({"v": 1, "type": "ping"}))
    pong = await recv_until(b, "pong")
    assert "server_time" in pong["data"]

    await a.close()
    await b.close()


asyncio.run(main())
```

`imserver/tests/ratelimit_test.cpp`:

```cpp
#include <gtest/gtest.h>
#include "util/ratelimit.h"

TEST(RateLimitTest, BurstThenRefill) {
  TokenBucket bucket(20, 40);
  int allowed = 0;
  for (int i = 0; i < 100; ++i) {
    if (bucket.allow(0)) ++allowed;
  }
  EXPECT_EQ(allowed, 40);
  EXPECT_TRUE(bucket.allow(1000));   // 1 秒补 20 个
  EXPECT_TRUE(bucket.allow(1000));
  EXPECT_FALSE(bucket.allow(1000));
}
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
docker compose -f imserver/docker-compose.test.yml run --rm test bash /src/scripts/test_ws.sh
```

Expected: FAIL —— 连接被拒绝（服务端还没监听）。

- [ ] **Step 3: 实现**

`SessionRegistry`：`std::mutex` + `std::unordered_map<uint64_t, std::weak_ptr<WsSession>>`；
`register_session` 先取出旧连接，调用 `old->kick("multi_device")`，再登记新连接；
`unregister` 只在当前指针匹配时删除；在线态写 Redis `SETEX im:online:<uid> 90 <now_ms>`，
任何帧到达时刷新。

`WsServer`：

- `acceptor` 监听 `cfg.listen_ws`；
- 每个连接 `WsSession` 持有 `websocket::stream<beast::tcp_stream>`、`strand`、
  `flat_buffer`、`std::deque<std::string> outbox`、`bool authed`、`uint64_t uid`；
- 升级前从 HTTP 请求头读 `X-Real-IP`（缺省用 remote endpoint），保存供限流；
- `do_accept` 成功后启动 5 秒 `auth_timer`，未收到 `auth` 就 `close(4002)`；
- `auth` 帧：`verify_token(token, cfg.jwt_secret, now_ms)`；失败回
  `{"type":"error","data":{"code":40101,...}}` 并 `close(4002)`；成功后再查
  Redis `im:block:<uid>`，命中则回 `40301` 并 `close(4003)`；否则
  `registry.register_session(uid, shared_from_this())`，回
  `{"type":"auth_ok","data":{"uid":uid,"server_time":...,"heartbeat_sec":25}}`；
- `ping` 帧回 `pong`；任何帧更新 `last_frame_ms`；
- 每 15 秒检查一次 `now - last_frame_ms > 75s`，超时 `close(1000)`；
- 出站：`send_json(json)` 序列化后入 `outbox`，若队列 >64 或字节 >128KB 则
  `close(4004)`；`do_write` 串行发送；
- `kick(reason)`：发 `{"type":"kicked","data":{"reason":reason}}` 后 `close(4001)`；
- 升级前校验 `Origin`：`cfg.allowed_origins` 非空时，带 Origin 且不在名单内直接
  HTTP 403；无 Origin（App）放行；
- 每 IP 并发连接上限 20（`X-Real-IP` 计数），超出 `close(4004)`；
- 入站帧超过 `cfg.max_frame` 直接 `close(4004)`，不解析；
- 鉴权失败按 IP 限流 60 次/分钟（`TokenBucket`），超限直接 `close(4002)`；
- 每用户发送令牌桶 20 条/秒、突发 40，Task 6 的 `send` 分支使用；
- 所有回调 `noexcept`，异常只记日志不抛出。

`main.cpp`：建 `RedisClient`、`SessionRegistry`、`WsServer`，`io_context` 跑
`cfg.io_threads` 线程，`SIGINT/SIGTERM` 调 `stop()`。

`CMakeLists.txt` 的 `imcore` 源文件追加 `src/net/ws_server.cpp`、
`src/service/session_registry.cpp`、`src/util/ratelimit.cpp`，`find_package(Threads
REQUIRED)` 后以 `PUBLIC` 链接 `Boost::system`、`Threads::Threads`；
`tests/CMakeLists.txt` 的 `im_unit_tests` 追加 `ratelimit_test.cpp`。

`imserver/scripts/test_ws.sh`：

```bash
#!/usr/bin/env bash
set -euo pipefail
cmake -S /src -B /src/build -G Ninja -DCMAKE_BUILD_TYPE=Debug
cmake --build /src/build
export IM_LISTEN_WS="127.0.0.1:19100"
export IM_LISTEN_HTTP="127.0.0.1:19101"
/src/build/imserver --migrate
/src/build/imserver &
PID=$!
trap 'kill $PID' EXIT
for i in $(seq 1 30); do
  (echo > /dev/tcp/127.0.0.1/19100) >/dev/null 2>&1 && break
  sleep 0.2
done
python3 /src/tests/integration/test_ws.py
```

- [ ] **Step 4: 跑测试确认通过**

```powershell
docker compose -f imserver/docker-compose.test.yml run --rm test bash /src/scripts/test_ws.sh
```

Expected: 脚本退出码 0，无断言失败。

- [ ] **Step 5: 提交**

```bash
git add imserver
git commit -m "feat(imserver): WebSocket 首帧鉴权、单设备互踢与心跳"
```

---

### Task 5: 仓储层与发送事务（seq / 幂等 / 未读）

**Files:**
- Create: `imserver/src/store/models.h`、`user_repo.{h,cpp}`、`conversation_repo.{h,cpp}`、`message_repo.{h,cpp}`、`blacklist_repo.{h,cpp}`
- Create: `imserver/src/service/message_service.{h,cpp}`
- Test: `imserver/tests/message_service_test.cpp`（集成，连真 MySQL）
- Modify: `imserver/CMakeLists.txt`

**Interfaces:**
- Consumes: `MysqlPool`、`MysqlDsn`
- Produces:
  - `struct SendRequest { uint64_t from; uint64_t to; std::string client_msg_id; std::string text; };`
  - `struct SendResult { uint64_t msg_id; uint64_t seq; int64_t ts; std::string from_nickname; std::string from_avatar; };`
  - `std::variant<SendResult, int> MessageService::send(const SendRequest&);`（int 为错误码）
  - `MessageService(MysqlPool&, UserRepo&, ConversationRepo&, MessageRepo&, BlacklistRepo&)`
  - 访问器：`users()` / `conversations()` / `messages()` / `blacklist()`

- [ ] **Step 1: 写失败测试**

`imserver/tests/message_service_test.cpp` 用 `IM_TEST_MYSQL_DSN` 建池，每个用例前
`TRUNCATE im_message/im_conversation/im_conversation_state/im_blacklist` 并插入
用户 1、2。测试文件里提供：

```cpp
class Fixture {
 public:
  explicit Fixture(const char* dsn)
      : pool_(parse_mysql_dsn(dsn), 2),
        users_(pool_), conversations_(pool_), messages_(pool_), blacklist_(pool_),
        svc_(pool_, users_, conversations_, messages_, blacklist_) {}

  MessageService& svc() { return svc_; }

 private:
  MysqlPool pool_;
  UserRepo users_;
  ConversationRepo conversations_;
  MessageRepo messages_;
  BlacklistRepo blacklist_;
  MessageService svc_;
};

MessageService& make_service() {
  static Fixture fixture(std::getenv("IM_TEST_MYSQL_DSN"));
  return fixture.svc();
}
```

```cpp
TEST(MessageServiceTest, AllocatesSeqAndUnread) {
  auto svc = make_service();
  svc.users().ensure(1, "A");
  svc.users().ensure(2, "B");

  auto first = svc.send({1, 2, "c-1", "你好"});
  ASSERT_TRUE(std::holds_alternative<SendResult>(first));
  EXPECT_EQ(std::get<SendResult>(first).seq, 1u);

  auto second = svc.send({1, 2, "c-2", "在吗"});
  ASSERT_TRUE(std::holds_alternative<SendResult>(second));
  EXPECT_EQ(std::get<SendResult>(second).seq, 2u);

  EXPECT_EQ(svc.conversations().unread_for_peer(2, 1), 2u);
}

TEST(MessageServiceTest, SameClientMsgIdIsIdempotent) {
  auto svc = make_service();
  svc.users().ensure(1, "A");
  svc.users().ensure(2, "B");
  auto a = svc.send({1, 2, "same", "hi"});
  auto b = svc.send({1, 2, "same", "hi"});
  ASSERT_TRUE(std::holds_alternative<SendResult>(a));
  ASSERT_TRUE(std::holds_alternative<SendResult>(b));
  EXPECT_EQ(std::get<SendResult>(a).msg_id, std::get<SendResult>(b).msg_id);
  EXPECT_EQ(svc.messages().count_pair(1, 2), 1u);
}

TEST(MessageServiceTest, BlacklistRejectsSend) {
  auto svc = make_service();
  svc.users().ensure(1, "A");
  svc.users().ensure(2, "B");
  svc.blacklist().add(2, 1);
  auto r = svc.send({1, 2, "c-1", "hi"});
  ASSERT_TRUE(std::holds_alternative<int>(r));
  EXPECT_EQ(std::get<int>(r), 40302);
}
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
docker compose -f imserver/docker-compose.test.yml run --rm test bash /src/scripts/test_integration.sh
```

Expected: FAIL —— `service/message_service.h: No such file or directory`。

- [ ] **Step 3: 实现**

`models.h` 定义四个 row 结构（字段与 §4 表一致）。

`UserRepo::ensure(uid, nickname)`：
```sql
INSERT INTO im_user (user_id, nickname, avatar_url, updated_at)
VALUES (?, ?, '', ?) ON DUPLICATE KEY UPDATE user_id = user_id
```
`get(uid)` 返回 `std::optional<UserRow>`；`update_profile(uid, nickname?, avatar?)` 用
动态 SET 的预处理语句。

`ConversationRepo`：

- `lock_pair(a, b)`：`SELECT id,last_seq FROM im_conversation WHERE user_a=? AND user_b=? FOR UPDATE`；
  不存在则 `INSERT`（`last_seq=0`），撞唯一键后重查；
- `touch(conv_id, seq, msg_id, at)`：`UPDATE ... SET last_seq=?, last_msg_id=?, last_msg_at=? WHERE id=?`；
- `upsert_state(owner, conv, unread_delta, reset_deleted)`：
  `INSERT ... ON DUPLICATE KEY UPDATE unread = unread + VALUES(unread), deleted = 0, updated_at = VALUES(updated_at)`；
- `unread(owner, conv)`、`unread_for_peer(owner, peer)`、`mark_read(owner, peer, seq)`、`set_deleted(owner, peer)`；
- `list(owner, limit)` 返回 join 后的会话摘要（Task 7 用）。

`MessageRepo`：

- `insert(conv_id, seq, from, to, kind, body, client_msg_id, at)` 返回 `msg_id`；
- `find_by_client(from, client_msg_id)` 返回 `std::optional<MessageRow>`；
- `list(conv_id, before_seq, limit)`：`SELECT ... WHERE conv_id=? AND seq<? ORDER BY seq DESC LIMIT ?`，
  调用方反转为升序；
- `revoke(msg_id, at)`、`count_pair(a,b)`、`delete_for_user(uid)`。

`BlacklistRepo`：`add/remove/exists_either(a,b)`，SQL 用
`WHERE (owner_id=? AND peer_id=?) OR (owner_id=? AND peer_id=?)`。

`CMakeLists.txt` 的 `imcore` 源文件追加四个 repo 与
`src/service/message_service.cpp`；`tests/CMakeLists.txt` 的 `im_db_tests`
源文件追加 `message_service_test.cpp`。

`MessageService::send`：

1. `from==to`、`text` 去空白后为空/超长、`client_msg_id` 非法 → 返回 `42201`；
2. `users().ensure(to, "")`（收件人没登录过也能收离线消息）；
3. `from != 0` 时查 `blacklist().exists_either(from, to)` → `40302`（系统通知不受拉黑限制）；
4. 先 `find_by_client`，命中且 `to_id` 一致 → 返回原结果；不一致 → `42201`；
5. `auto tx = pool.acquire(); tx.begin();`
6. `auto conv = conversations().lock_pair(min,max);`
7. `seq = conv.last_seq + 1`；`msg_id = messages().insert(...)`；
8. `conversations().touch(...)`；`upsert_state(to, +1, reset=true)`；
   `upsert_state(from, 0, reset=true)`（`from==0` 跳过发送方）；
9. `tx.commit();` 查一次 `users().get(from)`，返回
   `{msg_id, seq, now_ms, nickname, avatar}`；
10. 捕获 `mysql` 重复键（errno 1062）：回滚后重查 `find_by_client`，命中返回原结果，
    否则返回 `50001`。

- [ ] **Step 4: 跑测试确认通过**

```powershell
docker compose -f imserver/docker-compose.test.yml run --rm test bash /src/scripts/test_integration.sh
```

Expected: `MessageServiceTest.*` 全 PASS。

- [ ] **Step 5: 提交**

```bash
git add imserver
git commit -m "feat(imserver): 消息仓储与发送事务（seq/幂等/未读）"
```

---

### Task 6: WS 发送、ack、推送与离线补拉

**Files:**
- Create: `imserver/src/net/frames.h`
- Modify: `imserver/src/net/ws_server.cpp`（`send` 分支）、`imserver/src/service/session_registry.{h,cpp}`（`send_to`）
- Test: `imserver/tests/integration/test_send.py`

**Interfaces:**
- Consumes: `MessageService::send`、`SessionRegistry`
- Produces:
  - `bool SessionRegistry::send_to(uint64_t uid, const std::string& frame);`
  - `std::string build_message_frame(const SendResult&, uint64_t from, uint64_t to, const std::string& kind, const std::string& text, const nlohmann::json& custom);`
  - WS `send` 帧 → `ack` / `error`；接收方在线收到 `message`

- [ ] **Step 1: 写失败测试**

`imserver/tests/integration/test_send.py`:

```python
import asyncio, json, os, time
import jwt, websockets

SECRET = os.environ["IM_JWT_SECRET"]
WS = os.environ.get("IM_TEST_WS", "ws://127.0.0.1:19100/im/ws")


def token(uid):
    now = int(time.time())
    return jwt.encode({"sub": f"u{uid}", "uid": uid, "iat": now, "exp": now + 3600,
                       "jti": "t"}, SECRET, algorithm="HS256")


async def auth(uid):
    ws = await websockets.connect(WS)
    await ws.send(json.dumps({"v": 1, "type": "auth", "data": {"token": token(uid)}}))
    while True:
        msg = json.loads(await asyncio.wait_for(ws.recv(), 3))
        if msg["type"] == "auth_ok":
            return ws


async def recv(ws, type_):
    while True:
        msg = json.loads(await asyncio.wait_for(ws.recv(), 3))
        if msg["type"] == type_:
            return msg


async def main():
    a = await auth(1)
    b = await auth(2)
    await a.send(json.dumps({"v": 1, "type": "send", "id": "c-1",
                             "data": {"to": "u2", "kind": "text", "text": "你好"}}))
    ack = await recv(a, "ack")
    assert ack["id"] == "c-1"
    assert ack["data"]["seq"] == 1
    push = await recv(b, "message")
    assert push["data"]["text"] == "你好"
    assert push["data"]["from"] == "u1"
    assert push["data"]["seq"] == 1

    # 重发同一 client_msg_id：seq 不增，msg_id 相同
    await a.send(json.dumps({"v": 1, "type": "send", "id": "c-1",
                             "data": {"to": "u2", "kind": "text", "text": "你好"}}))
    ack2 = await recv(a, "ack")
    assert ack2["data"]["msg_id"] == ack["data"]["msg_id"]
    assert ack2["data"]["seq"] == 1

    await a.close()
    await b.close()


asyncio.run(main())
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
docker compose -f imserver/docker-compose.test.yml run --rm test bash /src/scripts/test_ws.sh
```

Expected: FAIL —— `KeyError: 'ack'` 或超时（`send` 分支未实现）。

- [ ] **Step 3: 实现**

`WsSession` 的 `send` 分支（先查该 uid 的 `TokenBucket`，超限直接回 `42901`，
不落库）：

```cpp
if (type == "send") {
  SendRequest req;
  req.from = uid;
  req.client_msg_id = data.value("client_msg_id", frame.value("id", ""));
  req.to = parse_uid(data.value("to", ""));
  req.text = data.value("text", "");
  // kind 必须是 text；否则回 42201
  db_pool_.post([self = shared_from_this(), req] {
    auto result = message_service_.send(req);
    boost::asio::post(self->strand_, [self, result, req, id = frame.value("id", "")] {
      if (auto* ok = std::get_if<SendResult>(&result)) {
        self->registry_.send_to(req.to,
            build_message_frame(*ok, req.from, req.to, "text", req.text, {}));
        self->send_json({{"v", 1}, {"type", "ack"}, {"id", id},
                         {"data", {{"msg_id", std::to_string(ok->msg_id)},
                                   {"seq", ok->seq}, {"ts", ok->ts}}}});
      } else {
        self->send_error(std::get<int>(result), id);
      }
    });
  });
}
```

`net/frames.h`：

```cpp
inline std::string build_message_frame(const SendResult& r, uint64_t from, uint64_t to,
                                       const std::string& kind, const std::string& text,
                                       const nlohmann::json& custom) {
  nlohmann::json data = {
      {"msg_id", std::to_string(r.msg_id)}, {"seq", r.seq},
      {"from", "u" + std::to_string(from)}, {"to", "u" + std::to_string(to)},
      {"kind", kind}, {"ts", r.ts}, {"revoked", false},
      {"from_profile", {{"nickname", r.from_nickname}, {"avatar", r.from_avatar}}}};
  if (kind == "text") {
    data["text"] = text;
  } else {
    data["custom"] = custom;
  }
  return nlohmann::json{{"v", 1}, {"type", "message"}, {"data", data}}.dump();
}
```

`SessionRegistry::send_to` 加锁取 `shared_ptr`，解锁后调用 `send_raw`（已序列化
的帧，避免重复 dump）；`send_json` 内部也走 `send_raw`。

离线时 `send_to` 返回 false，仅落库；B 登录后通过 Task 7 的 HTTP 拉取。

- [ ] **Step 4: 跑测试确认通过**

```powershell
docker compose -f imserver/docker-compose.test.yml run --rm test bash /src/scripts/test_ws.sh
```

Expected: 脚本退出码 0。

- [ ] **Step 5: 提交**

```bash
git add imserver
git commit -m "feat(imserver): WS 发送、ack、在线推送与幂等重发"
```

---

### Task 7: 历史消息、会话列表、已读、撤回、删会话

**Files:**
- Create: `imserver/src/net/http_api.h`、`imserver/src/net/http_api.cpp`
- Modify: `imserver/src/service/message_service.{h,cpp}`、`imserver/src/net/ws_server.cpp`、`imserver/src/main.cpp`、`imserver/CMakeLists.txt`
- Test: `imserver/tests/integration/test_history.py`、`imserver/scripts/test_http.sh`

**Interfaces:**
- Consumes: 仓储、`verify_token`、`SessionRegistry`
- Produces:
  - `HttpApi(Config, MessageService&, SessionRegistry&)`，路由 `/im/api/conversations`、`/im/api/messages`
  - `MessageService::list_conversations(uid, limit)`、`list_messages(uid, peer, before_seq, limit)`、`mark_read(uid, peer, seq)`、`revoke(uid, msg_id)`、`delete_conversation(uid, peer)`

- [ ] **Step 1: 写失败的端到端测试**

`imserver/tests/integration/test_history.py`（用 `urllib.request`，避免新增依赖）：

```python
import asyncio, json, os, time, urllib.request
import jwt, websockets

SECRET = os.environ["IM_JWT_SECRET"]
WS = os.environ.get("IM_TEST_WS", "ws://127.0.0.1:19100/im/ws")
HTTP = os.environ.get("IM_TEST_HTTP", "http://127.0.0.1:19101/im/api")


def token(uid):
    now = int(time.time())
    return jwt.encode({"sub": f"u{uid}", "uid": uid, "iat": now, "exp": now + 3600,
                       "jti": "t"}, SECRET, algorithm="HS256")


def get(path, uid):
    req = urllib.request.Request(HTTP + path,
                                 headers={"Authorization": f"Bearer {token(uid)}"})
    with urllib.request.urlopen(req, timeout=3) as resp:
        return json.loads(resp.read())


async def auth(uid):
    ws = await websockets.connect(WS)
    await ws.send(json.dumps({"v": 1, "type": "auth", "data": {"token": token(uid)}}))
    while True:
        msg = json.loads(await asyncio.wait_for(ws.recv(), 3))
        if msg["type"] == "auth_ok":
            return ws


async def recv(ws, type_):
    while True:
        msg = json.loads(await asyncio.wait_for(ws.recv(), 3))
        if msg["type"] == type_:
            return msg


async def main():
    a = await auth(1)
    for i, text in enumerate(["一", "二"]):
        await a.send(json.dumps({"v": 1, "type": "send", "id": f"c-{i}",
                                 "data": {"to": "u2", "kind": "text", "text": text}}))
        await recv(a, "ack")

    conv = get("/conversations", 2)["items"]
    assert conv[0]["peer"]["id"] == "u1"
    assert conv[0]["unread"] == 2

    history = get("/messages?peer=u1&limit=50", 2)["items"]
    assert [m["text"] for m in history] == ["一", "二"]
    assert history[0]["seq"] == 1

    b = await auth(2)
    await b.send(json.dumps({"v": 1, "type": "read", "data": {"peer": "u1", "seq": 2}}))
    await recv(b, "ack")
    assert get("/conversations", 2)["items"][0]["unread"] == 0

    msg_id = history[0]["msg_id"]
    await a.send(json.dumps({"v": 1, "type": "revoke", "data": {"msg_id": msg_id}}))
    revoked = await recv(b, "revoked")
    assert revoked["data"]["msg_id"] == msg_id
    after = get("/messages?peer=u1&limit=50", 2)["items"]
    assert after[0]["revoked"] is True and "text" not in after[0]

    await b.send(json.dumps({"v": 1, "type": "conversation_delete",
                             "data": {"peer": "u1"}}))
    await recv(b, "ack")
    assert get("/conversations", 2)["items"] == []

    await a.close(); await b.close()


asyncio.run(main())
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
docker compose -f imserver/docker-compose.test.yml run --rm test bash /src/scripts/test_http.sh
```

Expected: FAIL —— `urllib.error.HTTPError: 404` 或连接被拒绝。

- [ ] **Step 3: 实现**

`HttpApi` 用 `beast::http::async_read` 读请求，按 `req.target()` 前缀路由：

- 鉴权：读 `Authorization: Bearer <token>`，`verify_token` 失败回
  `401 {"code":40101,"message":"登录已过期"}`；
- `/im/api/conversations?limit=`：`message_service_.list_conversations(uid, limit)`，
  返回 `{"items":[...],"has_more":false}`；
- `/im/api/messages?peer=&before_seq=&limit=`：解析 `peer`（`u<digits>` 或
  `system_notice`），调 `list_messages`，返回 `{"items":[...],"has_more":bool}`；
- 错误统一 `{"code":<int>,"message":"<中文>"}`，HTTP 状态按 401/403/422/500 映射。

`MessageService` 查询实现：

- `list_conversations`：`SELECT c.id,c.user_a,c.user_b,c.last_seq,c.last_msg_at,
  s.unread,u.nickname,u.avatar_url,m.msg_id,m.seq,m.from_id,m.kind,m.body,m.created_at,m.revoked_at
  FROM im_conversation_state s JOIN im_conversation c ON c.id=s.conv_id
  JOIN im_user u ON u.user_id = IF(c.user_a=?, c.user_b, c.user_a)
  LEFT JOIN im_message m ON m.msg_id=c.last_msg_id
  WHERE s.owner_id=? AND s.deleted=0 ORDER BY c.last_msg_at DESC LIMIT ?`；
  逐行拼 JSON，`peer.id = "u"+other`，系统通知映射 `"system_notice"`；
- `list_messages`：先查 `conv_id`（`SELECT id FROM im_conversation WHERE user_a=? AND user_b=?`），
  再 `SELECT ... WHERE conv_id=? AND seq<? ORDER BY seq DESC LIMIT ?`，反转升序；
  `revoked_at` 非空时只输出 `revoked:true`，不输出 `text`；
- `mark_read`：`UPDATE im_conversation_state SET unread=0, read_seq=GREATEST(read_seq,?),
  updated_at=? WHERE owner_id=? AND conv_id=?`；
- `revoke`：`SELECT from_id,created_at,revoked_at FROM im_message WHERE msg_id=?`；
  非发送者 → `41001`；`now-created_at>120000` → `41001`；已撤回 → `41001`；
  `UPDATE ... SET revoked_at=?`；向双方 `send_to` 推 `revoked` 帧；
- `delete_conversation`：`UPDATE im_conversation_state SET deleted=1 WHERE owner_id=? AND conv_id=?`。

WS 新增分支：`read`、`revoke`、`conversation_delete`，成功后回
`{"type":"ack","id":<id>,"data":{"ok":true}}`，失败回 `error`。

`CMakeLists.txt` 的 `imcore` 源文件追加 `src/net/http_api.cpp`，`main.cpp` 启动
`HttpApi`（与 `WsServer` 共用 `io_context`）。

`imserver/scripts/test_http.sh`：

```bash
#!/usr/bin/env bash
set -euo pipefail
cmake -S /src -B /src/build -G Ninja -DCMAKE_BUILD_TYPE=Debug
cmake --build /src/build
export IM_LISTEN_WS="127.0.0.1:19100"
export IM_LISTEN_HTTP="127.0.0.1:19101"
/src/build/imserver --migrate
/src/build/imserver &
PID=$!
trap 'kill $PID' EXIT
for i in $(seq 1 30); do
  (echo > /dev/tcp/127.0.0.1/19100) >/dev/null 2>&1 && break
  sleep 0.2
done
export IM_TEST_HTTP="http://127.0.0.1:19101/im/api"
python3 /src/tests/integration/test_history.py
```

- [ ] **Step 4: 跑测试确认通过**

```powershell
docker compose -f imserver/docker-compose.test.yml run --rm test bash /src/scripts/test_http.sh
```

Expected: 脚本退出码 0。

- [ ] **Step 5: 提交**

```bash
git add imserver
git commit -m "feat(imserver): 历史/会话 HTTP 与已读、撤回、删会话"
```

---

### Task 8: 内部管理 API 与 HMAC

**Files:**
- Modify: `imserver/src/net/http_api.{h,cpp}`
- Create: `imserver/src/util/hmac.{h,cpp}`、`imserver/src/util/uuid.{h,cpp}`
- Test: `imserver/tests/integration/test_internal.py`、`imserver/tests/hmac_test.cpp`

**Interfaces:**
- Consumes: `MessageService`、`SessionRegistry`、仓储
- Produces:
  - `std::string hmac_sha256_hex(std::string_view key, std::string_view data);`
  - `bool verify_internal(const http::request<http::string_body>&, std::string_view secret, int64_t now_s);`
  - 内部路由 `/internal/*`（见 spec §6.4）

- [ ] **Step 1: 写失败的 HMAC 测试**

`imserver/tests/hmac_test.cpp`:

```cpp
#include <gtest/gtest.h>
#include "util/hmac.h"

TEST(HmacTest, KnownVector) {
  EXPECT_EQ(hmac_sha256_hex("key", "The quick brown fox jumps over the lazy dog"),
            "f7bc83f430538424b13298e6aa6fb143ef4d59a14946175997479dbc2d1a3cd8");
}
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
docker run --rm -v "$($PWD.Path)\imserver:/src" imserver-dev bash /src/scripts/test.sh
```

Expected: FAIL —— `util/hmac.h: No such file or directory`。

- [ ] **Step 3: 实现 HMAC 与内部路由**

`hmac.cpp` 用 `HMAC(EVP_sha256(), ...)` 输出小写 hex。`verify_internal`：

1. 取 `X-IM-Timestamp`、`X-IM-Signature`；
2. `|now_s - ts| > 60` 返回 false；
3. 拼 `ts + "\n" + method + "\n" + target + "\n" + body`；
4. `CRYPTO_memcmp` 比较。

`/internal/*` 处理前检查 `socket().remote_endpoint().address().is_loopback()`，
不是回环地址直接 403；`X-Real-IP` 只用于客户端接口，不参与内部 API 判断。

`CMakeLists.txt` 的 `imcore` 追加 `src/util/hmac.cpp`、`src/util/uuid.cpp`；
`tests/CMakeLists.txt` 的 `im_unit_tests` 追加 `hmac_test.cpp`。

内部路由（全部 POST，除 healthz/readyz/stats）：

| 路径 | 实现 |
|---|---|
| `/internal/healthz` | `200 {"ok":true}`，不查库 |
| `/internal/readyz` | `SELECT 1` + Redis `PING`，失败 503 |
| `/internal/accounts/ensure` | `users().ensure(uid,nickname)` |
| `/internal/profile` | `users().update_profile(uid,nickname?,avatar?)` |
| `/internal/send` | 构造 `SendRequest`，`client_msg_id="sys-"+uuid`；`from=0` 允许；推送 |
| `/internal/blacklist` | `add/remove` |
| `/internal/kick` | `registry.kick(uid, "banned")`；`block=true` 时 Redis `SETEX im:block:<uid> 86400 1` |
| `/internal/unblock` | `DEL im:block:<uid>` |
| `/internal/delete_account` | 事务删 `im_message`（from/to）、`im_conversation`、`state`、`blacklist`、`im_user`；再 kick+block |
| `/internal/stats` | 在线数、发送计数、ack 延迟 p50/p99（简单分桶）、队列丢弃数 |

`/internal/send` 与 WS 共用 `net/frames.h::build_message_frame(SendResult, from, to,
kind, text, custom)`，避免两处 JSON 字段漂移；落库后 `registry.send_to(to, ...)`。

`uuid.cpp`：`std::random_device` + `mt19937_64`，输出 32 位 hex。

- [ ] **Step 4: 写并跑内部 API 测试**

`imserver/tests/integration/test_internal.py` 计算 HMAC 调
`/internal/accounts/ensure`、`/internal/send`、`/internal/kick`，断言：

```python
BASE = "http://127.0.0.1:19101"

def call(path, payload):
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    ts = str(int(time.time()))
    sig = hmac.new(SECRET.encode(), f"{ts}\nPOST\n{path}\n{body}".encode(),
                   hashlib.sha256).hexdigest()
    req = urllib.request.Request(BASE + path, data=body.encode(),
        headers={"Content-Type": "application/json", "X-IM-Timestamp": ts,
                 "X-IM-Signature": sig})
    with urllib.request.urlopen(req, timeout=3) as r:
        return json.loads(r.read())

call("/internal/accounts/ensure", {"uid": 1, "nickname": "A"})
call("/internal/send", {"from": 0, "to": 1, "kind": "custom",
                        "custom": {"type": "ban_notice", "desc": "你被封禁", "data": {}}})
```

再用 WS 以 uid=1 登录，断言收到 `message` 且 `custom.type=="ban_notice"`；
`/internal/kick {"uid":1,"block":true}` 后连接收到 `kicked`；重连被拒 `40301`；
`/internal/unblock` 后可重连。

`test_http.sh` 末尾追加：

```bash
python3 /src/tests/integration/test_internal.py
```

- [ ] **Step 5: 跑测试确认通过**

```powershell
docker compose -f imserver/docker-compose.test.yml run --rm test bash /src/scripts/test_http.sh
```

Expected: `HmacTest` 与 `test_internal.py` 全 PASS。

- [ ] **Step 6: 提交**

```bash
git add imserver
git commit -m "feat(imserver): 内部管理 API 与 HMAC 鉴权"
```

---

### Task 9: Django IM token 与自建客户端门面

**Files:**
- Create: `chatapp/im/token.py`、`chatapp/im/self_client.py`、`chatapp/im/backend.py`
- Modify: `chatapp/im/client.py`（每个公开函数顶部加分发）
- Test: `chatapp/im/tests.py`（新增 `SelfBackendTests`）

**实现说明**：不把腾讯实现搬到独立文件。`im/tests.py` 里有 77 处
`patch("im.client.*")`，迁文件会让它们全部失效；保留 `client.py` 为腾讯实现、
在函数入口分发，行为不变、改动面最小。spec §7.2 已同步为当前布局。

**Interfaces:**
- Consumes: `settings.IM_BACKEND` / `IM_SELF_*`
- Produces:
  - `mint_im_token(user_id: int, ttl: int) -> str`
  - `verify_im_token(token: str) -> dict | None`
  - `self_client.{ensure_account, send_custom_elem, send_text, set_profile_nick,
    set_profile_avatar, black_list_add, black_list_delete, kick_user,
    unblock_user, delete_account, send_ban_lifted}`
  - `backend.use_self_im(user) -> bool`

- [ ] **Step 1: 写失败的 token 测试**

在 `chatapp/im/tests.py` 顶部加：

```python
from .token import mint_im_token, verify_im_token
```

新增用例：

```python
class ImTokenTests(SimpleTestCase):
    def test_mint_and_verify(self):
        token = mint_im_token(9, 3600)
        claims = verify_im_token(token)
        self.assertIsNotNone(claims)
        self.assertEqual(claims["uid"], 9)
        self.assertEqual(claims["sub"], "u9")

    def test_reject_tampered(self):
        token = mint_im_token(9, 3600)
        self.assertIsNone(verify_im_token(token[:-1] + ("A" if token[-1] != "A" else "B")))
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
cd chatapp
$env:TEST_REDIS_PORT="16379"
python manage.py test im.tests.ImTokenTests -v 2
```

Expected: FAIL —— `ImportError: cannot import name 'mint_im_token'`。

- [ ] **Step 3: 实现 token、self_client、backend**

`chatapp/im/token.py`:

```python
"""IM token 的签发与校验（HS256，与 C++ 服务端共享密钥）。"""

import time
import uuid

import jwt
from django.conf import settings


def mint_im_token(user_id: int, ttl: int) -> str:
    """签发一个 IM token。

    Args:
        user_id: 账号 id。
        ttl: 有效期（秒）。

    Returns:
        HS256 JWT 字符串。
    """
    now = int(time.time())
    return jwt.encode(
        {"sub": f"u{user_id}", "uid": user_id, "iat": now,
         "exp": now + ttl, "jti": uuid.uuid4().hex},
        settings.IM_SELF_SECRET, algorithm="HS256")


def verify_im_token(token: str) -> dict | None:
    """校验 IM token；失败返回 ``None``（测试与排障用）。"""
    try:
        claims = jwt.decode(token, settings.IM_SELF_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    if claims.get("sub") != f"u{claims.get('uid')}":
        return None
    return claims
```

`chatapp/im/self_client.py` 要点（**不要 import `client.py`**，避免循环依赖；
系统通知常量与 `BAN_LIFTED_TEXT` 等文案在本文件本地定义）：

```python
SYSTEM_UID = 0


def _uid(identifier: str) -> int:
    if identifier == SYSTEM_NOTICE_IDENTIFIER:
        return SYSTEM_UID
    return int(identifier.removeprefix("u"))


def _post(path: str, payload: dict) -> bool:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    ts = str(int(time.time()))
    signing = f"{ts}\nPOST\n{path}\n{body}".encode()
    sig = hmac.new(settings.IM_SELF_INTERNAL_SECRET.encode(), signing,
                   hashlib.sha256).hexdigest()
    try:
        resp = requests.post(settings.IM_SELF_URL + path, data=body.encode(),
                             headers={"Content-Type": "application/json",
                                      "X-IM-Timestamp": ts,
                                      "X-IM-Signature": sig}, timeout=5)
        resp.raise_for_status()
        return True
    except Exception:
        logger.exception("自建 IM 调用失败 path=%s", path)
        return False
```

公开函数（全部返回 `bool`、永不抛异常）：

- `ensure_account(identifier, nickname="")` → `_post("/internal/accounts/ensure", {"uid":..., "nickname":...})`
- `set_profile_nick/avatar` → `/internal/profile`
- `send_custom_elem(from_identifier, to_identifier, data, desc="")` →
  `/internal/send`，`custom={"type": data["type"], "desc": desc, "data": data}`
- `send_text(from, to, text)` → `/internal/send`，`kind="text"`
- `black_list_add/delete(owner, other)` → `/internal/blacklist`
- `kick_user(identifier, block=False)` → `/internal/kick`
- `unblock_user(identifier)` → `/internal/unblock`
- `delete_account(identifier)` → `/internal/delete_account`
- `send_ban_lifted(to_identifier)` → 先 `send_custom_elem`，再 `unblock_user`

`chatapp/im/backend.py`:

```python
def _gray_uids():
    gray = getattr(settings, "IM_SELF_GRAYLIST", "").strip()
    if gray == "all":
        return None
    return {int(x) for x in gray.split(",") if x.strip().isdigit()}


def use_self_im(user) -> bool:
    """登录时该用户是否走自建 IM。"""
    if getattr(settings, "IM_BACKEND", "tencent") != "self":
        return False
    gray = _gray_uids()
    return gray is None or user.id in gray


def self_enabled_for(identifier: str) -> bool:
    """某个 IM 账号的副作用是否走自建后端。

    Args:
        identifier: IM 账号，如 ``u9``；系统通知传收件人账号。

    Returns:
        ``IM_BACKEND=self`` 且该账号命中灰度名单（或名单为 ``all``）时为 ``True``。
    """
    if getattr(settings, "IM_BACKEND", "tencent") != "self":
        return False
    gray = _gray_uids()
    if gray is None:
        return True
    uid = 0 if identifier == "system_notice" else int(identifier.removeprefix("u"))
    return uid in gray
```

`chatapp/im/client.py` 顶部：

```python
from . import self_client
from .backend import self_enabled_for
```

每个公开函数按“**决策主体**”分发（不是全局开关）：

| 函数 | 决策主体 | 原因 |
|---|---|---|
| `ensure_account` / `set_profile_*` | `identifier` | 账号自身 |
| `send_custom_elem` / `send_text` | `to_identifier` | 消息投递到哪套存储 |
| `black_list_add/delete` | `owner_identifier` | 操作方 |
| `kick_user` / `delete_account` | `identifier` | 目标账号 |
| `send_ban_lifted` | `to_identifier` | 收件人 |

示例：

```python
def ensure_account(identifier: str, nickname: str = "") -> bool:
    if self_enabled_for(identifier):
        return self_client.ensure_account(identifier, nickname)
    ...
```

**注意**：`send_match_notice` / `send_ban_notice` / 举报与评论通知都是组合函数，
内部调用 `send_custom_elem`，不要在组合函数上再分发一次，避免双重判断。
唯一例外是 `send_ban_lifted`：它还要清封禁键，顶部显式分发到
`self_client.send_ban_lifted`。

`kick_user` 增加 `block: bool = False`，腾讯分支忽略该参数。

- [ ] **Step 4: 写并跑门面测试**

`chatapp/im/tests.py` 顶部现有 `from .client import (...)` 里补上
`send_custom_elem`，然后追加：

```python
class SelfBackendTests(SimpleTestCase):
    @override_settings(IM_BACKEND="self", IM_SELF_GRAYLIST="2")
    @patch("im.client.self_client.send_custom_elem", return_value=True)
    def test_gray_recipient_dispatches(self, mocked):
        self.assertTrue(send_custom_elem("u1", "u2", {"type": "match_notice"}, "hi"))
        mocked.assert_called_once()

    @override_settings(IM_BACKEND="self", IM_SELF_GRAYLIST="1")
    @patch("im.client._request")
    def test_non_gray_recipient_stays_tencent(self, request):
        request.return_value = {"ErrorCode": 0}
        self.assertTrue(send_custom_elem("u1", "u2", {"type": "x"}, "hi"))
        request.assert_called_once()

    @override_settings(IM_BACKEND="tencent")
    @patch("im.client._request")
    def test_tencent_still_default(self, request):
        request.return_value = {"ErrorCode": 0}
        self.assertTrue(send_custom_elem("u1", "u2", {"type": "x"}, "hi"))
```

Run:

```powershell
cd chatapp
$env:TEST_REDIS_PORT="16379"
python manage.py test im.tests.ImTokenTests im.tests.SelfBackendTests -v 2
```

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add chatapp/im
git commit -m "feat(im): IM token 与自建客户端门面"
```

---

### Task 10: `/im/user_sig` 双分支与灰度配置

**Files:**
- Modify: `chatapp/config/settings.py`、`chatapp/im/views.py`、`chatapp/.env.example`
- Test: `chatapp/im/tests.py`
- Docs: `docs/api/im.md`

**Interfaces:**
- Consumes: `mint_im_token`、`use_self_im`、`self_client.ensure_account`
- Produces: `POST /api/v1/im/user_sig` 响应新增 `backend/token/ws_url/http_url`

- [ ] **Step 1: 写失败测试**

```python
class UserSigSelfTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(phone="13800000001")

    @override_settings(IM_BACKEND="self", IM_SELF_GRAYLIST="all",
                       IM_SELF_WS_URL="wss://im.example/ws",
                       IM_SELF_HTTP_URL="https://im.example/api")
    @patch("im.views.ensure_account", return_value=True)
    def test_self_branch_returns_token(self, _):
        self.client.force_authenticate(self.user)
        resp = self.client.post("/api/v1/im/user_sig")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["backend"], "self")
        self.assertEqual(resp.data["ws_url"], "wss://im.example/ws")
        self.assertTrue(resp.data["token"])

    @override_settings(IM_BACKEND="self", IM_SELF_GRAYLIST="")
    @patch("im.views.gen_user_sig", return_value="tencent-sig")
    def test_not_in_graylist_falls_back(self, _):
        self.client.force_authenticate(self.user)
        resp = self.client.post("/api/v1/im/user_sig")
        self.assertEqual(resp.data["backend"], "tencent")
        self.assertEqual(resp.data["user_sig"], "tencent-sig")
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
cd chatapp
$env:TEST_REDIS_PORT="16379"
python manage.py test im.tests.UserSigSelfTests -v 2
```

Expected: FAIL —— `KeyError: 'backend'`。

- [ ] **Step 3: 实现配置与分支**

`settings.py` 在腾讯 IM 配置后追加：

```python
# --- 自建 IM（IM_BACKEND=self 时生效）---
IM_BACKEND = os.getenv("IM_BACKEND", "tencent")
IM_SELF_URL = os.getenv("IM_SELF_URL", "http://127.0.0.1:9101")
IM_SELF_WS_URL = os.getenv("IM_SELF_WS_URL", "")
IM_SELF_HTTP_URL = os.getenv("IM_SELF_HTTP_URL", "")
IM_SELF_SECRET = os.getenv("IM_SELF_SECRET", "")
IM_SELF_INTERNAL_SECRET = os.getenv("IM_SELF_INTERNAL_SECRET", "")
IM_SELF_TOKEN_TTL = int(os.getenv("IM_SELF_TOKEN_TTL", "86400"))
IM_SELF_GRAYLIST = os.getenv("IM_SELF_GRAYLIST", "")

if IM_BACKEND == "self" and not (IM_SELF_SECRET and IM_SELF_INTERNAL_SECRET
                                 and IM_SELF_WS_URL and IM_SELF_HTTP_URL):
    raise ImproperlyConfigured("IM_BACKEND=self 需要完整的 IM_SELF_* 配置")
```

`views.py`：

```python
from .backend import use_self_im
from .token import mint_im_token

...
if use_self_im(user):
    nickname = getattr(getattr(user, "profile", None), "nickname", "") or ""
    ensure_account(user.im_user_id, nickname)  # 失败不阻断
    return Response({
        "backend": "self",
        "token": mint_im_token(user.id, settings.IM_SELF_TOKEN_TTL),
        "im_user_id": user.im_user_id,
        "ws_url": settings.IM_SELF_WS_URL,
        "http_url": settings.IM_SELF_HTTP_URL,
        "expire": settings.IM_SELF_TOKEN_TTL,
    })
return Response({
    "backend": "tencent",
    "user_sig": gen_user_sig(user.im_user_id),
    "sdkappid": settings.IM_SDKAPPID,
    "im_user_id": user.im_user_id,
    "expire": settings.IM_SIG_EXPIRE,
})
```

保留原 `kick_pending` 逻辑；self 分支下 `kick_user` 走门面。

`.env.example` 追加 §7.1 的全部键（值留空/示例）。

`docs/api/im.md` 的 `user_sig` 响应示例补 `backend` 与新字段，并写明两种分支。

- [ ] **Step 4: 跑测试确认通过**

```powershell
cd chatapp
$env:TEST_REDIS_PORT="16379"
python manage.py test im.tests.UserSigSelfTests -v 2
python manage.py test im -v 2
```

Expected: 全 PASS；`ApiDocsCoverageTests` 绿。

- [ ] **Step 5: 提交**

```bash
git add chatapp/config/settings.py chatapp/im/views.py chatapp/.env.example docs/api/im.md
git commit -m "feat(im): user_sig 双分支与自建 IM 灰度配置"
```

---

### Task 11: 系统通知与封禁/解封端到端

**Files:**
- Modify: `chatapp/im/tasks.py`（`ban_notice` 一行）、`chatapp/im/self_client.py`（`send_ban_lifted` 已含 unblock）
- Test: `chatapp/im/tests.py`

**Interfaces:**
- Consumes: 门面 `kick_user(identifier, block)`、`self_client.send_ban_lifted`
- Produces: 配对灰条、封禁通知、解封通知、举报/评论通知在 self 模式下全部可用

- [ ] **Step 1: 写失败测试**

```python
class SelfNoticeTests(SimpleTestCase):
    @override_settings(IM_BACKEND="self", IM_SELF_GRAYLIST="9")
    @patch("im.client.self_client.send_custom_elem", return_value=True)
    @patch("im.client.self_client.kick_user", return_value=True)
    def test_heavy_ban_blocks_and_notifies(self, kick, send):
        with patch("im.tasks._user") as user:
            user.return_value.im_user_id = "u9"
            ban_notice.run(9, "heavy", "违规")
        send.assert_called_once()
        kick.assert_called_once_with("u9", True)

    @override_settings(IM_BACKEND="self", IM_SELF_GRAYLIST="9")
    @patch("im.client.self_client.send_ban_lifted", return_value=True)
    def test_ban_lifted_unblocks(self, lifted):
        with patch("im.tasks._user") as user:
            user.return_value.im_user_id = "u9"
            ban_lifted.run(9)
        lifted.assert_called_once_with("u9")
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
cd chatapp
$env:TEST_REDIS_PORT="16379"
python manage.py test im.tests.SelfNoticeTests -v 2
```

Expected: FAIL —— `kick` 未按 `block=True` 调用（或 `ban_notice` 参数不匹配）。

- [ ] **Step 3: 实现**

`chatapp/im/tasks.py::ban_notice`：

```python
kicked = im_client.kick_user(user.im_user_id, block=True)
```

`self_client.send_ban_lifted`：

```python
def send_ban_lifted(to_identifier: str) -> bool:
    sent = send_custom_elem(SYSTEM_NOTICE_IDENTIFIER, to_identifier,
                            {"type": "ban_lifted"}, BAN_LIFTED_TEXT)
    return unblock_user(to_identifier) and sent
```

顺序：先发通知再解封；`unblock` 失败返回 False 交给 Celery 重试（重试会重复灰条，
与现网腾讯路径一致）。

`client.py` 的 `send_ban_lifted` 在 self 模式分发到 `self_client.send_ban_lifted`。

- [ ] **Step 4: 跑测试确认通过**

```powershell
cd chatapp
$env:TEST_REDIS_PORT="16379"
python manage.py test im -v 2
```

Expected: 全 PASS。

- [ ] **Step 5: 提交**

```bash
git add chatapp/im
git commit -m "feat(im): 系统通知与封禁/解封在自建后端闭环"
```

---

### Task 12: Flutter 引导包、路由客户端与连接

**Files:**
- Create: `app/lib/im/im_bootstrap.dart`、`app/lib/im/self_transport.dart`、`app/lib/im/routing_im_client.dart`、`app/lib/im/self_im_client.dart`
- Modify: `app/lib/im/im_client.dart`、`app/lib/im/im_repository.dart`、`app/lib/im/im_manager.dart`、`app/pubspec.yaml`
- Test: `app/test/im/self_im_client_test.dart`、`app/test/im/routing_im_client_test.dart`、`app/test/support/fake_im_client.dart`

**Interfaces:**
- Consumes: `POST /im/user_sig` 响应
- Produces:
  - `enum ImBackend { tencent, self }`
  - `class ImBootstrap { ImBackend backend; int sdkAppId; String token, wsUrl, httpUrl, imUserId; }`
  - `class ImCapabilities { bool image; }`
  - `abstract class SelfTransport { Stream<String> get frames; Future<void> connect(Uri); void send(String); Future<void> close(); }`
  - `abstract class SelfHttpClient { Future<Map<String,dynamic>> get(String path, Map<String,String> query); }`
  - `ImClient.init(ImBootstrap)` / `ImClient.capabilities`

- [ ] **Step 1: 写失败测试**

`app/test/im/self_im_client_test.dart`:

```dart
import 'dart:async';
import 'package:flutter_test/flutter_test.dart';
import 'package:chatapp_app/im/im_bootstrap.dart';
import 'package:chatapp_app/im/self_im_client.dart';
import 'package:chatapp_app/im/self_transport.dart';

class FakeTransport implements SelfTransport {
  final _frames = StreamController<String>.broadcast();
  final sent = <String>[];
  bool connected = false;

  @override
  Stream<String> get frames => _frames.stream;
  @override
  Future<void> connect(Uri uri) async => connected = true;
  @override
  void send(String frame) => sent.add(frame);
  @override
  Future<void> close() async => _frames.close();

  void emit(String frame) => _frames.add(frame);
}

void main() {
  test('login sends auth and completes on auth_ok', () async {
    final transport = FakeTransport();
    final client = SelfImClient(transportFactory: () => transport);
    await client.init(const ImBootstrap(
      backend: ImBackend.self,
      token: 'tok',
      wsUrl: 'ws://test/im/ws',
      httpUrl: 'http://test/im/api',
      imUserId: 'u9',
    ));

    final login = client.login(userId: 'u9', userSig: 'tok');
    await pumpEventQueue();
    expect(transport.connected, isTrue);
    expect(transport.sent.single, contains('"type":"auth"'));

    transport.emit('{"v":1,"type":"auth_ok","data":{"uid":9}}');
    await login;
  });
}
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
cd app
..\flutter\bin\flutter.bat test test/im/self_im_client_test.dart
```

Expected: FAIL —— `Error: Couldn't resolve the package 'chatapp_app'` 中的
`im_bootstrap.dart` / `self_im_client.dart` 不存在。

- [ ] **Step 3: 实现引导包、传输与客户端骨架**

`app/pubspec.yaml` 的 dependencies 加：

```yaml
  web_socket_channel: ^3.0.3
```

`im_bootstrap.dart`:

```dart
enum ImBackend { tencent, self }

class ImBootstrap {
  const ImBootstrap({
    required this.backend,
    this.sdkAppId = 0,
    this.token = '',
    this.wsUrl = '',
    this.httpUrl = '',
    required this.imUserId,
  });

  final ImBackend backend;
  final int sdkAppId;
  final String token;
  final String wsUrl;
  final String httpUrl;
  final String imUserId;
}
```

`im_client.dart` 接口改动：

```dart
class ImCapabilities {
  const ImCapabilities({required this.image});
  final bool image;
}

abstract class ImClient {
  Stream<ImEvent> get events;
  ImCapabilities get capabilities;
  Future<void> init(ImBootstrap bootstrap);
  Future<void> login({required String userId, required String userSig});
  // 其余方法签名不变
}
```

`TencentImClient`：`init` 里用 `bootstrap.sdkAppId`；`capabilities` 返回
`const ImCapabilities(image: true)`；`sendImage` 逻辑不变。

`im_repository.dart`：`UserSig` 增加 `backend`、`token`、`wsUrl`、`httpUrl`，
`user_sig`/`sdkappid` 改为可空；`fetchUserSig` 解析
`backend`（缺省 `tencent`）。

`im_manager.dart::_loginOnce`：

```dart
final sig = await ref.read(imRepositoryProvider).fetchUserSig();
final client = ref.read(imClientProvider);
await client.init(sig.bootstrap);
await client.login(userId: sig.imUserId, userSig: sig.token.isNotEmpty ? sig.token : (sig.userSig ?? ''));
state = ImLoggedIn(sig.imUserId);
```

`imClientProvider` 改为 `RoutingImClient()`。

`self_transport.dart`：接口如 Produces；`WebSocketTransport` 用
`WebSocketChannel.connect(uri)`，`await channel.ready` 后把 `channel.stream`
转成 `Stream<String>`，`send` 调 `channel.sink.add`，`close` 调 `sink.close`。
同文件放 `DioSelfHttpClient`（独立 `Dio`，baseUrl=`httpUrl`，
`Authorization: Bearer <token>`，不挂 JWT 刷新拦截器）。

`self_im_client.dart`（本任务只做连接/鉴权/心跳/重连）：

```dart
class SelfImClient implements ImClient {
  SelfImClient({SelfTransport Function()? transportFactory, SelfHttpClient? httpClient})
      : _newTransport = transportFactory ?? (() => WebSocketTransport()),
        _http = httpClient;

  final SelfTransport Function() _newTransport;
  SelfHttpClient? _http;
  final _events = StreamController<ImEvent>.broadcast();
  ImBootstrap? _bootstrap;
  SelfTransport? _transport;
  StreamSubscription<String>? _sub;
  Timer? _heartbeat;
  bool _stopped = false;
  int _attempt = 0;
  String? _lastToken;

  @override
  Stream<ImEvent> get events => _events.stream;

  @override
  ImCapabilities get capabilities => const ImCapabilities(image: false);

  @override
  Future<void> init(ImBootstrap bootstrap) async {
    _bootstrap = bootstrap;
    _http ??= DioSelfHttpClient(bootstrap.httpUrl, bootstrap.token);
  }

  @override
  Future<void> login({required String userId, required String userSig}) async {
    _stopped = false;
    _lastToken = userSig;
    await _connect(userSig);
  }

  Future<void> _connect(String token) async {
    final boot = _bootstrap!;
    final transport = _newTransport();
    _transport = transport;
    final auth = Completer<void>();
    _sub = transport.frames.listen((raw) {
      final frame = jsonDecode(raw) as Map<String, dynamic>;
      final type = frame['type'] as String? ?? '';
      if (type == 'auth_ok') {
        _attempt = 0;
        if (!auth.isCompleted) auth.complete();
        _startHeartbeat();
      } else if (type == 'kicked') {
        _stopped = true;
        _events.add(const ImKickedOffline());
        unawaited(transport.close());
      } else if (type == 'error' &&
          (frame['data'] as Map?)?['code'] == 40101) {
        _stopped = true;
        _events.add(const ImSigExpired());
        unawaited(transport.close());
      }
    }, onDone: _scheduleReconnect, onError: (_) => _scheduleReconnect());
    await transport.connect(Uri.parse(boot.wsUrl));
    transport.send(jsonEncode({'v': 1, 'type': 'auth', 'data': {'token': token}}));
    await auth.future.timeout(const Duration(seconds: 5));
  }

  void _startHeartbeat() {
    _heartbeat?.cancel();
    _heartbeat = Timer.periodic(const Duration(seconds: 25), (_) {
      _transport?.send(jsonEncode({'v': 1, 'type': 'ping', 'data': {}}));
    });
  }

  void _scheduleReconnect() {
    if (_stopped) return;
    final delay = Duration(seconds: (1 << _attempt).clamp(1, 30));
    _attempt = (_attempt + 1).clamp(0, 5);
    Timer(delay, () => _connect(_lastToken!).catchError((_) {}));
  }
}
```

（`_lastToken` 在 `login` 时保存；本任务不实现发送/历史，未实现的方法先
`throw UnimplementedError()`，Task 13 补齐。）

`routing_im_client.dart`：`init` 时按 `bootstrap.backend` 建
`TencentImClient` 或 `SelfImClient`；`events` 用 broadcast 控制器转发；
其余方法逐个委托给 `_active!`。

`app/test/support/fake_im_client.dart`：补 `capabilities` 与
`init(ImBootstrap)` 签名。

- [ ] **Step 4: 跑测试确认通过**

```powershell
cd app
..\flutter\bin\flutter.bat test test/im/self_im_client_test.dart test/im/routing_im_client_test.dart
..\flutter\bin\flutter.bat analyze
```

Expected: 测试 PASS，`No issues found!`。

- [ ] **Step 5: 提交**

```bash
git add app/pubspec.yaml app/pubspec.lock app/lib/im app/test
git commit -m "feat(app/im): 引导包、路由客户端与自建连接"
```

---

### Task 13: Flutter 收发、ack 重试、历史与会话

**Files:**
- Modify: `app/lib/im/self_im_client.dart`
- Test: `app/test/im/self_im_client_test.dart`、`app/test/im/self_history_test.dart`

**Interfaces:**
- Consumes: Task 12 的 `SelfImClient`/`SelfTransport`
- Produces: `sendText`、`resend`、`fetchHistory`、`fetchConversations`、
  `markConversationRead`、`revokeMessage`、`deleteConversation`、`deleteMessage`

- [ ] **Step 1: 写失败测试**

```dart
const bootstrap = ImBootstrap(
  backend: ImBackend.self,
  token: 'tok',
  wsUrl: 'ws://test/im/ws',
  httpUrl: 'http://test/im/api',
  imUserId: 'u9',
);

test('sendText retries with the same client_msg_id', () async {
  final transport = FakeTransport();
  final client = SelfImClient(transportFactory: () => transport);
  await client.init(bootstrap);
  await client.login(userId: 'u9', userSig: 'tok');
  transport.emit('{"v":1,"type":"auth_ok","data":{"uid":9}}');

  final future = client.sendText(peerId: 'u2', text: 'hi');
  await pumpEventQueue();
  final first = jsonDecode(transport.sent.last) as Map<String, dynamic>;
  final cid = first['id'] as String;

  transport.emit(jsonEncode({'v': 1, 'type': 'ack', 'id': cid,
      'data': {'msg_id': '100', 'seq': 1, 'ts': 1}}));
  final message = await future;
  expect(message.msgId, '100');
  expect(message.text, 'hi');
});

test('fetchHistory maps ascending items', () async {
  final transport = FakeTransport();
  final client = SelfImClient(transportFactory: () => transport,
      httpClient: FakeHttpClient.history([
        {'msg_id': '1', 'seq': 1, 'from': 'u2', 'to': 'u9', 'kind': 'text',
         'text': 'a', 'ts': 10, 'revoked': false},
      ]));
  await client.init(bootstrap);
  final login = client.login(userId: 'u9', userSig: 'tok');
  await pumpEventQueue();
  transport.emit('{"v":1,"type":"auth_ok","data":{"uid":9}}');
  await login;
  final items = await client.fetchHistory('u2');
  expect(items.single.text, 'a');
  expect(items.single.isSelf, isFalse);
});
```

（`FakeHttpClient` 在测试文件内实现，注入到 `SelfImClient` 的可选构造参数；
生产默认用 `Dio`。）

- [ ] **Step 2: 跑测试确认失败**

```powershell
cd app
..\flutter\bin\flutter.bat test test/im/self_im_client_test.dart
```

Expected: FAIL —— `UnimplementedError` 或 `sendText` 未定义。

- [ ] **Step 3: 实现**

- `sendText`：生成/复用 `client_msg_id`，放入 `_pending`，发帧，等 ack；
  `timeout(10s)` 后用同一 id 重发，最多 3 次；仍失败抛
  `ImException(50001, "发送失败")`。
- `resend`：文本走 `sendText(clientMsgId: message.msgId)`；图片走
  `sendImage`（self 下抛 42202）。
- `_onFrame` 处理 `ack`（完成 pending）、`message`（`ImNewMessage` +
  `ImConversationsChanged`）、`revoked`（`ImMessageRevoked`）。
- `fetchHistory`：`GET {httpUrl}/messages?peer=&limit=`，带
  `Authorization: Bearer <token>`，映射为 `ChatMessage`（`isSelf = from == imUserId`，
  `timestamp = ts`，custom → `matchNotice`/`banNotice`/`other`）。
- `fetchConversations`：`GET {httpUrl}/conversations`，映射 `ImConversation`。
- `markConversationRead`：发 `read` 帧（fire-and-forget）。
- `revokeMessage`：发 `revoke` 帧，等 `ack`；超时抛 `ImException(41001)`。
- `deleteConversation`：发帧并等 ack。
- `deleteMessage`：no-op（本地删除由控制器做）。

`ChatMessage.msgId` 用服务端字符串；`isPending` 由控制器维护。

- [ ] **Step 4: 跑测试确认通过**

```powershell
cd app
..\flutter\bin\flutter.bat test test/im
..\flutter\bin\flutter.bat analyze
```

Expected: 全 PASS，零告警。

- [ ] **Step 5: 提交**

```bash
git add app/lib/im app/test/im
git commit -m "feat(app/im): 自建收发、ack 重试、历史与会话"
```

---

### Task 14: Web 自建客户端与路由

**Files:**
- Create: `web/src/im/self/transport.ts`、`web/src/im/self/client.ts`、`web/src/im/self/map.ts`、`web/src/im/routing.ts`
- Modify: `web/src/im/types.ts`、`web/src/im/client.ts`、`web/src/stores/chat.ts`
- Test: `web/tests/unit/im-self.spec.ts`

**Interfaces:**
- Consumes: `/im/user_sig` 引导包
- Produces:
  - `interface ImBootstrap { backend: 'tencent' | 'self'; sdkAppId: number; token: string; wsUrl: string; httpUrl: string; imUserId: string }`
  - `ImClient.init(bootstrap: ImBootstrap)`、`ImClient.capabilities`
  - `getImClient()` 返回 `RoutingImClient`

- [ ] **Step 1: 写失败测试**

```ts
import { describe, expect, it, vi } from 'vitest'
import { SelfImClient } from '@/im/self/client'
import type { SelfTransport } from '@/im/self/transport'

class FakeTransport implements SelfTransport {
  sent: string[] = []
  private listeners: ((raw: string) => void)[] = []
  onFrame(fn: (raw: string) => void) { this.listeners.push(fn) }
  async connect() {}
  send(raw: string) { this.sent.push(raw) }
  async close() {}
  emit(raw: string) { this.listeners.forEach((fn) => fn(raw)) }
}

describe('SelfImClient', () => {
  it('logs in with first-frame auth and resolves send on ack', async () => {
    const transport = new FakeTransport()
    const client = new SelfImClient(() => transport)
    await client.init({ backend: 'self', sdkAppId: 0, token: 'tok',
      wsUrl: 'ws://test/im/ws', httpUrl: 'http://test/im/api', imUserId: 'u9' })
    const login = client.login('u9', 'tok')
    await Promise.resolve()
    expect(transport.sent[0]).toContain('"type":"auth"')
    transport.emit('{"v":1,"type":"auth_ok","data":{"uid":9}}')
    await login
    expect(client.capabilities.image).toBe(false)
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
cd web
npm run test:run -- im-self
```

Expected: FAIL —— 模块不存在。

- [ ] **Step 3: 实现**

`types.ts`：`ImBootstrap`、`ImCapabilities`、`init(bootstrap)`；
`ImClient` 其余方法不变。

`self/transport.ts`：

```ts
export interface SelfTransport {
  onFrame(fn: (raw: string) => void): void
  connect(url: string): Promise<void>
  send(raw: string): void
  close(): Promise<void>
}

export class BrowserWebSocketTransport implements SelfTransport {
  private ws?: WebSocket
  private handler?: (raw: string) => void
  onFrame(fn: (raw: string) => void) { this.handler = fn }
  connect(url: string) {
    return new Promise<void>((resolve, reject) => {
      const ws = new WebSocket(url)
      this.ws = ws
      ws.onopen = () => resolve()
      ws.onerror = () => reject(new Error('ws error'))
      ws.onmessage = (e) => this.handler?.(String(e.data))
    })
  }
  send(raw: string) { this.ws?.send(raw) }
  close() { this.ws?.close(); return Promise.resolve() }
}
```

`self/client.ts`：与 Flutter 同构——`init` 存 bootstrap、`login` 连接并发
`auth`、`auth_ok` 后 ready；`sendText` 等 `ack`，10 秒超时用同一 id 重试 3 次；
`fetchHistory`/`fetchConversations` 用 `fetch(httpUrl + path, {headers})`；
`sendImage` 抛 `ImException(42202, ...)`；`capabilities.image=false`。

`routing.ts`：按 `bootstrap.backend` 建 `TencentImClient` 或 `SelfImClient`，
事件转发。

`web/src/im/client.ts`：`getImClient()` 改为返回 `routing` 单例；
`TencentImClient.init(bootstrap)` 用 `bootstrap.sdkAppId`。

`web/src/stores/chat.ts::doConnect`：

```ts
const { data } = await http.post('/im/user_sig')
const payload = data as ImBootstrap & { user_sig?: string }
// Web 永远走同源：忽略后端返回的绝对地址（可能是 App 用的 10.0.2.2）
const wsUrl = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/im/ws`
const httpUrl = new URL('/im/api', location.origin).toString()
await client.init({ ...payload, wsUrl, httpUrl })
await client.login(payload.im_user_id, payload.token || payload.user_sig || '')
```

- [ ] **Step 4: 跑测试确认通过**

```powershell
cd web
npm run test:run -- im-self
npm run type-check
npm run lint
```

Expected: PASS，零错误/零告警。

- [ ] **Step 5: 提交**

```bash
git add web/src/im web/src/stores/chat.ts web/tests/unit/im-self.spec.ts
git commit -m "feat(web/im): 自建客户端与后端路由"
```

---

### Task 15: 双端隐藏图片入口

**Files:**
- Modify: `app/lib/features/chat/chat_page.dart`、`web/src/features/chat/ChatPage.vue`
- Test: `app/test/features/chat/chat_page_test.dart`、`web/tests/component/chat-page.spec.ts`

**Interfaces:**
- Consumes: `ImClient.capabilities.image`
- Produces: 自建后端下图片按钮不渲染

- [ ] **Step 1: 写失败测试**

Flutter：在现有聊天页测试里注入 `FakeImClient`，把 `capabilities` 设为
`ImCapabilities(image: false)`，断言 `find.byKey(const Key('chat.image'))` 为空；
`image: true` 时存在。

Web：mock `getImClient()` 返回 `capabilities.image=false`，断言
`wrapper.find('[data-test="image-button"]').exists()` 为 false。

- [ ] **Step 2: 跑测试确认失败**

```powershell
cd app
..\flutter\bin\flutter.bat test test/features/chat/chat_page_test.dart
cd ..\web
npm run test:run -- chat-page
```

Expected: FAIL —— 按钮仍然存在。

- [ ] **Step 3: 实现**

Flutter `chat_page.dart` 的图片按钮外层加：

```dart
if (ref.read(imClientProvider).capabilities.image)
  IconButton(key: const Key('chat.image'), ...)
```

Web `ChatPage.vue`：

```vue
<button v-if="client.capabilities.image" data-test="image-button" ...>
```

`sendImage` 仍保留抛错兜底。

- [ ] **Step 4: 跑测试确认通过**

```powershell
cd app
..\flutter\bin\flutter.bat test test/features/chat/chat_page_test.dart
..\flutter\bin\flutter.bat analyze
cd ..\web
npm run test:run -- chat-page
npm run type-check
```

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add app/lib/features/chat/chat_page.dart app/test/features/chat/chat_page_test.dart \
        web/src/features/chat/ChatPage.vue web/tests/component/chat-page.spec.ts
git commit -m "feat(im): 自建后端隐藏图片入口"
```

---

### Task 16: 最小版本拦截

**Files:**
- Create: `chatapp/appconfig/__init__.py`、`apps.py`、`views.py`、`urls.py`、`tests.py`
- Modify: `chatapp/config/settings.py`、`chatapp/config/urls.py`
- Create: `app/lib/core/app_config.dart`、`app/lib/features/auth/force_update_page.dart`
- Modify: `app/lib/features/auth/splash_page.dart`
- Create: `web/src/features/app/ForceUpdate.vue`、`web/src/main.ts`
- Docs: `docs/api/app.md`、`docs/api/README.md`

**Interfaces:**
- Consumes: `appVersion`（`app/lib/core/app_info.dart`）
- Produces: `GET /api/v1/app/config` → `{min_app_version, latest_version, download_url}`

- [ ] **Step 1: 写失败测试**

Django:

```python
class AppConfigTests(APITestCase):
    def test_public_config(self):
        resp = self.client.get("/api/v1/app/config")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("min_app_version", resp.data)
```

Flutter：`test/core/app_config_test.dart` 断言
`isOutdated(current: '1.0.0', min: '1.1.0') == true`、`'1.1.0'` 为 false。

- [ ] **Step 2: 跑测试确认失败**

```powershell
cd chatapp
$env:TEST_REDIS_PORT="16379"
python manage.py test appconfig -v 2
cd ..\app
..\flutter\bin\flutter.bat test test/core/app_config_test.dart
```

Expected: FAIL —— 404 / 文件不存在。

- [ ] **Step 3: 实现**

Django：新建 `appconfig` app，`views.py`：

```python
@api_view(["GET"])
@permission_classes([AllowAny])
def app_config(request):
    """返回客户端启动所需的最低版本配置。"""
    return Response({
        "min_app_version": settings.MIN_APP_VERSION,
        "latest_version": settings.LATEST_APP_VERSION,
        "download_url": settings.APP_DOWNLOAD_URL,
    })
```

`settings.py` 加 `MIN_APP_VERSION = os.getenv("MIN_APP_VERSION", "1.0.0")` 等；
`config/urls.py` 加 `path("api/v1/app/", include("appconfig.urls"))`；
`INSTALLED_APPS` 加 `appconfig`。

Flutter `app_config.dart`：

```dart
bool isOutdated({required String current, required String min}) {
  List<int> parts(String v) => v.split('.').map((e) => int.tryParse(e) ?? 0).toList();
  final a = parts(current), b = parts(min);
  for (var i = 0; i < 3; i++) {
    final x = i < a.length ? a[i] : 0;
    final y = i < b.length ? b[i] : 0;
    if (x != y) return x < y;
  }
  return false;
}
```

`SplashPage._start` 在协议检查前拉 `/app/config`；失败不阻断（网络抖动），
`isOutdated` 为真时 `setState` 显示 `ForceUpdatePage`（下载按钮
`launchUrl`，不进入主界面）。

Web `main.ts` 挂载前 `fetch('/api/v1/app/config')`，版本低则渲染
`ForceUpdate.vue`；Vite `define` 注入 `__APP_VERSION__`（取 `package.json.version`）。

`docs/api/app.md` 新建，`docs/api/README.md` 计数 +1。

- [ ] **Step 4: 跑测试确认通过**

```powershell
cd chatapp
$env:TEST_REDIS_PORT="16379"
python manage.py test appconfig -v 2
cd ..\app
..\flutter\bin\flutter.bat test test/core/app_config_test.dart
cd ..\web
npm run type-check
```

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add chatapp/appconfig chatapp/config app/lib/core/app_config.dart \
        app/lib/features/auth web/src/features/app web/src/main.ts docs/api
git commit -m "feat(app): 最小版本拦截（/app/config + 双端阻塞页）"
```

---

### Task 17: 端到端脚本、压测与 CI

**Files:**
- Create: `tools/im_e2e.py`、`tools/im_load.py`、`.github/workflows/imserver.yml`
- Modify: `imserver/scripts/test_http.sh`

**Interfaces:**
- Consumes: 已启动的 imserver + MySQL + Redis
- Produces: 一条命令跑完“登录→互发→离线→撤回→踢下线”的验收脚本；500 连接压测

- [ ] **Step 1: 写失败的 E2E 脚本**

`tools/im_e2e.py` 用 `websockets` + `urllib` 串起验收清单 1–8（见 spec §11.2），
每一步失败即 `sys.exit(1)` 并打印步骤名。先写空实现：

```python
def main():
    raise SystemExit("not implemented")
```

- [ ] **Step 2: 跑脚本确认失败**

```powershell
python tools/im_e2e.py
```

Expected: 退出码 1，输出 `not implemented`。

- [ ] **Step 3: 实现脚本与压测**

`tools/im_e2e.py`：读 `IM_BASE_WS` / `IM_BASE_HTTP` / `IM_JWT_SECRET`，用
**uid 9001/9002**（避免与 history/internal 用例的 1/2 冲突），实现
`auth(uid)`、`send(...)`、`recv(...)`，覆盖：

1. 双端互发文本；
2. B 离线时 A 发 3 条，B 登录后未读=3；
3. 同一 `client_msg_id` 重发只落一行；
4. 2 分钟内撤回双方变灰；
5. 第二处登录踢掉第一处；
6. 拉黑后发送失败；
7. 重启后重连（脚本只校验重连，不负责重启）；
8. 封禁/解封。

`tools/im_load.py`：`asyncio` 建 500 条连接，每 50ms 随机选一对发消息，统计
`ack` 延迟 p50/p95/p99 与错误数；结束打印 JSON 并断言 p99 < 200ms。

`.github/workflows/imserver.yml`：`ubuntu-24.04` 上
`docker compose -f imserver/docker-compose.test.yml run --rm test bash /src/scripts/test_http.sh`
（compose 的 `test` 服务已把仓库根挂到 `/repo`，`test_http.sh` 末尾会跑
`/repo/tools/im_e2e.py`）。

`test_http.sh` 末尾追加：

```bash
export IM_BASE_WS="ws://127.0.0.1:19100/im/ws"
export IM_BASE_HTTP="http://127.0.0.1:19101/im/api"
python3 /repo/tools/im_e2e.py
```

- [ ] **Step 4: 跑脚本确认通过**

```powershell
docker compose -f imserver/docker-compose.test.yml run --rm test bash /src/scripts/test_http.sh
```

Expected: 所有步骤 PASS，退出码 0。

- [ ] **Step 5: 提交**

```bash
git add tools/im_e2e.py tools/im_load.py .github/workflows/imserver.yml imserver/scripts
git commit -m "test(imserver): 端到端验收、500 连接压测与 CI"
```

---

### Task 18: 部署产物与运维手册

**Files:**
- Create: `imserver/Dockerfile`、`imserver/deploy/imserver.service`、`imserver/deploy/nginx-im.conf`、`imserver/deploy/imserver.env.example`、`docs/ops/imserver.md`
- Modify: `imserver/CMakeLists.txt`（安装规则）

**Interfaces:**
- Consumes: 已通过的二进制
- Produces: 可复制的 systemd/Nginx/env 三件套与启动/升级/回滚步骤

- [ ] **Step 1: 写发布镜像与部署文件**

`imserver/Dockerfile` 多阶段：

```dockerfile
FROM ubuntu:24.04 AS build
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake ninja-build pkg-config \
    libboost-all-dev nlohmann-json3-dev libssl-dev \
    libmysqlclient-dev libhiredis-dev && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY . .
RUN cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release && cmake --build build

FROM ubuntu:24.04
RUN apt-get update && apt-get install -y --no-install-recommends \
    libboost-system-dev libssl3 libmysqlclient-dev libhiredis-dev \
    ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=build /src/build/imserver /usr/local/bin/imserver
COPY --from=build /src/migrations /usr/local/share/imserver/migrations
ENTRYPOINT ["/usr/local/bin/imserver"]
```

`deploy/imserver.service`：

```ini
[Unit]
Description=Self-hosted IM server
After=network.target mysql.service redis-server.service

[Service]
Type=simple
EnvironmentFile=/www/server/imserver/imserver.env
ExecStart=/usr/local/bin/imserver
Restart=always
RestartSec=2
LimitNOFILE=65535
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
```

`deploy/nginx-im.conf`：按 spec §12.2 的 `/im/ws` 与 `/im/api/`，含
`X-Real-IP`、`proxy_read_timeout 90s`。

`deploy/imserver.env.example`：§12.2 全部键，密钥留空。

`docs/ops/imserver.md`：首次部署（建库/建号/`--migrate`/systemd/Nginx）、
升级（换二进制 → `--migrate` → restart）、回滚（`IM_BACKEND=tencent` →
重启 gunicorn → 用户重启 App）、日志与健康检查、备份。

- [ ] **Step 2: 构建发布镜像**

```powershell
docker build -f imserver/Dockerfile -t imserver:test imserver
docker run --rm imserver:test
```

Expected: 退出码 1，输出 `missing IM_MYSQL_DSN`（说明动态库齐全、配置校验生效）。
若报 `error while loading shared libraries`，按
`docker run --rm --entrypoint ldd imserver:test /usr/local/bin/imserver` 的实际
soname 调整运行阶段的 apt 包名。

- [ ] **Step 3: 校验 Nginx 配置语法**

`nginx-im.conf` 只是两个 `location` 片段（粘贴进现有 `server{}`），不能直接放进
`conf.d`。用临时 wrapper 校验：

```powershell
docker run --rm -v "$($PWD.Path)\imserver\deploy\nginx-im.conf:/etc/nginx/im-locations.conf:ro" nginx:1.27 bash -lc "printf 'events{} http{ server{ listen 8080; include /etc/nginx/im-locations.conf; } }' > /etc/nginx/nginx.conf && nginx -t"
```

Expected: `syntax is ok`。

- [ ] **Step 4: 提交**

```bash
git add imserver/Dockerfile imserver/deploy docs/ops/imserver.md
git commit -m "feat(imserver): 发布镜像与 systemd/Nginx 部署产物"
```

---

### Task 19: 灰度、回退演练与文档收尾

**Files:**
- Modify: `docs/pitfalls/im.md`、`CLAUDE.md`、`README.md`、`docs/api/im.md`、`docs/api/README.md`
- Create: `docs/superpowers/plans/2026-10-20-self-hosted-im-rollout.md`（核对单）

**Interfaces:**
- Consumes: 前 18 个任务
- Produces: 可执行的切换/回退步骤与项目文档更新

- [ ] **Step 1: 写灰度核对单**

`docs/superpowers/plans/2026-10-20-self-hosted-im-rollout.md` 列出：

1. 服务器部署但 `IM_BACKEND=tencent`，`http://127.0.0.1:9101/internal/healthz` 200；
2. 隔离测试号加入 `IM_SELF_GRAYLIST`，两端互发/撤回/离线/踢下线通过；
3. `MIN_APP_VERSION` 生效，旧版本被阻塞页挡住；
4. **全量前置：图片二期已交付**（否则只保留测试号灰度，不做 `all`）；
5. 切换日 `IM_SELF_GRAYLIST=all`，观察 30 分钟；
6. 回退：`IM_BACKEND=tencent` → 重启 gunicorn → 用户重启 App；
7. 回退后自建库保留，消息不丢（但腾讯侧看不到）。

- [ ] **Step 2: 更新踩坑手册与项目文档**

`docs/pitfalls/im.md` 增加“自建 IM”分册：首帧鉴权、seq 语义、幂等键、
单设备互踢、灰度不能跨后端、Redis 不可用 fail closed。

`CLAUDE.md`：IM 章节改为“腾讯/自建双后端”，补 `IM_BACKEND` 开关、
`imserver` 目录、测试命令；`README.md` 部署图加 imserver。

`docs/api/im.md` 补 `user_sig` 双分支与错误码；`docs/api/README.md` 计数更新
（新增 `/app/config`）。

- [ ] **Step 3: 跑全量门禁**

```powershell
cd chatapp
$env:TEST_REDIS_PORT="16379"
python manage.py test
cd ..\app
..\flutter\bin\flutter.bat analyze
..\flutter\bin\flutter.bat test
cd ..\web
npm run type-check
npm run lint
npm run test:coverage
```

Expected: 后端全绿、Flutter 零告警且全绿、Web 零错误/零告警且覆盖率达标。

- [ ] **Step 4: 提交**

```bash
git add docs CLAUDE.md README.md
git commit -m "docs(im): 自建 IM 灰度核对单与项目文档收尾"
```

---

### Task 20（条件任务）: 腾讯历史消息导入

**触发条件：** 腾讯侧单聊漫游/导出 REST 可用且已开通权限。不可用时**不写代码**，
在 `docs/ops/imserver.md` 记录结论并由产品书面确认“切换点之前的记录不可见”。

**Files:**
- Create: `tools/im_import_tencent.py`
- Modify: `docs/ops/imserver.md`

**Interfaces:**
- Consumes: 导出的 JSON 行（每行一条）：
  `{"msg_id": "...", "from": "u1", "to": "u2", "kind": "text", "text": "...", "ts": 1760000000000}`
- Produces: `import_messages(rows: list[dict], dsn: str) -> int`（写入条数）

- [ ] **Step 1: 确认接口与输入格式**

用腾讯云控制台文档确认单聊漫游接口名、权限与分页参数，把结论（接口、限制、
导出命令）写进 `docs/ops/imserver.md`。同时确定导出 JSON 的字段映射：
`from/to` 为 `u<id>`，`ts` 为毫秒，`kind` 只支持 text。

- [ ] **Step 2: 写失败的导入测试**

`tools/im_import_tencent.py` 先只留：

```python
def import_messages(rows, dsn):
    raise NotImplementedError
```

测试脚本（可放 `imserver/tests/integration/test_import.py`）：

```python
rows = [
    {"msg_id": "m2", "from": "u1", "to": "u2", "kind": "text", "text": "二", "ts": 2000},
    {"msg_id": "m1", "from": "u1", "to": "u2", "kind": "text", "text": "一", "ts": 1000},
]
assert import_messages(rows, DSN) == 2
assert import_messages(rows, DSN) == 0          # 重跑幂等
history = get_history(1, 2)
assert [m["text"] for m in history] == ["一", "二"]  # 按 ts 升序、seq 1..2
```

- [ ] **Step 3: 跑测试确认失败**

```powershell
docker compose -f imserver/docker-compose.test.yml run --rm test \
  python3 /repo/tools/im_import_tencent.py --selftest
```

Expected: FAIL —— `NotImplementedError`。

- [ ] **Step 4: 实现**

`import_messages`：

1. 按 `(min(from,to), max(from,to))` 分组，组内按 `ts` 升序、`msg_id` 升序稳定排序；
2. 每组查 `im_conversation`，不存在则插入；从 `last_seq+1` 开始分配 `seq`；
3. 逐条 `INSERT IGNORE INTO im_message (..., client_msg_id) VALUES (...)`，
   `client_msg_id = "tx-" + msg_id`；被忽略（已存在）不计入返回值；
4. 更新 `im_conversation.last_seq/last_msg_id/last_msg_at` 与双方 state
   （导入的历史不增加未读：`unread` 保持 0，`read_seq=last_seq`）；
5. 全部在一个事务里，失败回滚；返回实际插入条数。

- [ ] **Step 5: 跑测试确认通过**

```powershell
docker compose -f imserver/docker-compose.test.yml run --rm test \
  python3 /repo/tools/im_import_tencent.py --selftest
```

Expected: PASS（首次 2 条、重跑 0 条、顺序正确）。

- [ ] **Step 6: 提交**

```bash
git add tools/im_import_tencent.py imserver/tests/integration/test_import.py docs/ops/imserver.md
git commit -m "feat(im): 腾讯历史消息导入（条件任务）"
```

---

## 执行方式

项目全局约定（`~/.dsh/AGENTS.md`）：superpowers 任务**在当前会话内联执行**，
不派发子 agent。因此本计划使用 `executing-plans` 逐任务执行，每个 Task 结束
后跑该 Task 的验证命令并提交，再进入下一个 Task。

**完成定义：** 19 个必做 Task 的复选框全部勾选（Task 20 仅在腾讯导出可用时执行）；
§11.2 验收清单全绿；`IM_BACKEND` 在 tencent/self 之间切换演练通过；文档门禁
（`ApiDocsCoverageTests`、`CommentCoverageTests`）绿。
