# Superagent 开发流程(P0–P3)实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan inline.
> **本计划的执行方式是特例**:它是「流程自身的引导」,必须在 Windows/WSL 直接做,不能拆成 superagent 工单——worker 要先有 `scripts/verify.sh` 和 `AGENTS.md` 才可能干活。P4(业务改动)才交给工单。

**Goal:** 让 WSL 里的 `dsh-superagent` worker 能自己证明「代码是对的」再开 PR,并把「开单 → 实现 → 验收 → 人合」固化成可重复的日常流程。

**Architecture:** 三层:CI 六轨仍是唯一裁判;`scripts/verify.sh` 在本地复刻同一套检查(同一 compose、同一命令、同一环境变量),让 worker 在推之前就能跑绿;`AGENTS.md` + Issue/PR 模板把「哪些纪律违反就红」写成 worker 可读的执行约束。人与机器的边界靠「不配 merge CLI + 碰 `app/` 必须模拟器验收」守住。

**Tech Stack:** Docker Compose(mysql:8.0 / redis:7-alpine)、POSIX bash、Django 5.2 + DRF、Flutter 3.47.2(Linux SDK)、C++20 imserver(docker test)、Vue 3 + vitest。

**Spec:** [docs/superpowers/specs/2026-11-07-superagent-dev-workflow-design.md](../specs/2026-11-07-superagent-dev-workflow-design.md)

## Global Constraints

- **一单一条栈**:backend / web / imserver / app / 纯文档;跨栈必须拆单。契约联动(OpenAPI、`docs/api/*.md`、WS fixture、心跳 token、版本号三处)算同一条栈的附带改动,同 PR 内做完。
- **不改 CI workflow 去调 `scripts/verify.sh`**:`verify.sh` 是 CI 的镜像,不是 CI 的入口。CI 红了两边同时瞎比一处出错更糟。
- **不碰**:`flutter/`(SDK 源码,自带独立 .git)、`.remember/`、`app/pubspec.yaml` 版本号(本计划不升版本)、`deploy/` 下任何生产脚本、`.env` 与任何密钥。
- **不配 merge CLI**:superagent 永不自合;所有 PR 由人 squash 合并。
- **碰 `app/` 的 UI 可见改动**:worker 只负责码 + `flutter analyze`/`flutter test`,PR 必须开成 draft 且不得声称 ready,模拟器验收由人在 Windows 上做。
- **新增/修改 `.py` 必须补齐 docstring**(`docs/standards/python.md`),否则 `CommentCoverageTests` 红。本计划不新增 `.py`。
- **对 worker 的唯一本地验证入口**:`scripts/verify.sh <stack>`;文档、提示词、PR 模板里提到验证都必须指向它。
- **提交信息**:沿用 `<type>(<scope>): <中文摘要>`,scope 取 `backend`/`web`/`imserver`/`app`/`scripts`/`docs`/`ops`。

---

## 文件结构

| 路径 | 职责 |
|---|---|
| `docker-compose.ci.yml`(新增,仓库根) | CI 等价依赖容器:mysql:8.0 + redis:7-alpine,端口映射避开 Windows 本机 3306/6379 |
| `chatapp/db_setup_ci.sql`(新增) | 容器初始化:给 `chatapp` 用户授权 `test_chatapp_dev.*`(等价于 CI 里那一步 GRANT) |
| `scripts/verify.sh`(新增) | 五栈本地验证入口:`backend` / `web` / `imserver` / `app` / `contract`,外加 `all` / `deps` |
| `scripts/test_verify.sh`(新增) | `verify.sh` 的自测(无参→用法退出 1;未知栈→退出 2;`--list`→列出五栈;`--dry-run`→只打印命令) |
| `scripts/superagent-prune.sh`(新增) | 清理已结束工单的 worktree 与 `refs/dsh-superagent/*` |
| `AGENTS.md`(新增,仓库根) | 给 agent 的执行约束:门禁表、verify 表、PR 规矩、禁止事项 |
| `.github/ISSUE_TEMPLATE/agent-task.yml`(新增) | 工单模板:背景 / 验收口径 / 影响栈 / 禁止事项 / 是否碰 app |
| `.github/pull_request_template.md`(新增) | PR 四问 + App 手测证据勾选 |
| `docs/ops/superagent.md`(新增) | 运维手册:启停、retry、prepare 失败、worktree 清理、升级回滚 |
| `~/.dsh/AGENTS.md`(修改,**不入库**) | 全局约定改成「设计与评审内联、实现走工单」 |
| superagent 面板 `prompts.delivery` / `prompts.scope` / `settings.executor`(修改,面板/API) | 项目专属条款(verify 入口、一单一条栈、app UI 不得声称 ready)+ 执行环境(maxWorkers=2、blockedCommands、prepare 去代理) |

---

### Task 1: CI 等价依赖容器

**Files:**
- Create: `docker-compose.ci.yml`
- Create: `chatapp/db_setup_ci.sql`

**Interfaces:**
- Produces: 容器名 `chatapp-ci-mysql` / `chatapp-ci-redis`;宿主端口 **13306**(MySQL)、**16379**(Redis);凭据 `chatapp` / `chatapp_ci`,库 `chatapp_dev`。Task 2/3 的 `verify.sh` 依赖这三组值。

- [ ] **Step 1: 在 WSL 里打开 Docker 集成并确认可用**

Windows 侧:Docker Desktop → Settings → Resources → WSL integration → 打开 `Ubuntu-24.04` → Apply & restart。然后在 WSL 里跑:

```bash
wsl -e bash -lc 'docker version --format "{{.Server.Version}}"'
```

期望:打印一个版本号。若报 `could not be found in this WSL 2 distro`,说明集成没开——**停在这里修好再继续**。

- [ ] **Step 2: 确认端口没被本机开发环境占用**

```powershell
Test-NetConnection -ComputerName 127.0.0.1 -Port 13306 -InformationLevel Quiet
Test-NetConnection -ComputerName 127.0.0.1 -Port 16379 -InformationLevel Quiet
```

期望:两个都是 `False`。若为 `True`,改用 13307/16380 并同步改下面 compose 与 Task 3 的 env。

- [ ] **Step 3: 写 `chatapp/db_setup_ci.sql`**

```sql
-- CI 等价依赖容器的初始化脚本。
-- 业务库 chatapp_dev 由 MYSQL_DATABASE 自动创建;这里只补「测试库授权」,
-- 与 .github/workflows/backend.yml「给测试库授权」那一步等价。
-- Django 测试运行器会自行 CREATE DATABASE test_<DB_NAME>,而 MYSQL_USER 建出的账号
-- 只有 MYSQL_DATABASE 一个库的权限,建库会 1044 被拒。
GRANT ALL PRIVILEGES ON `test_chatapp_dev`.* TO 'chatapp'@'%';
FLUSH PRIVILEGES;
```

- [ ] **Step 4: 写 `docker-compose.ci.yml`**

```yaml
# CI 等价依赖:与 .github/workflows/backend.yml 的 services 逐项对齐(镜像/账号/库名/健康检查)。
# 用途:在 WSL / Linux 本地跑 scripts/verify.sh backend,不必等 CI 才知道红绿。
#
# 端口刻意不映射成 3306 / 6379:Windows 本机已跑着开发用 MySQL 与 chatapp-redis,
# 而 Docker Desktop 的发布端口落在 Windows 宿主上,会直接撞车。
# 这里用 13306 / 16379,verify.sh 里通过 DB_PORT / REDIS_URL 指过来。
name: chatapp-ci

services:
  mysql:
    image: mysql:8.0
    container_name: chatapp-ci-mysql
    environment:
      MYSQL_ROOT_PASSWORD: root
      MYSQL_DATABASE: chatapp_dev
      MYSQL_USER: chatapp
      MYSQL_PASSWORD: chatapp_ci
    ports:
      - "13306:3306"
    volumes:
      # 挂在 initdb.d 下:容器首次初始化时自动执行,补 test 库授权。
      # 不挂数据卷,保证每次 up 都是干净库;verify.sh 结束默认 down。
      - ./chatapp/db_setup_ci.sql:/docker-entrypoint-initdb.d/10-grant-test-db.sql:ro
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "127.0.0.1", "--silent"]
      interval: 10s
      timeout: 5s
      retries: 12
      start_period: 30s

  redis:
    image: redis:7-alpine
    container_name: chatapp-ci-redis
    ports:
      - "16379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 10
```

- [ ] **Step 5: 校验并起来**

```bash
wsl -e bash -lc 'cd /mnt/d/pycharmproject/chat_app && docker compose -f docker-compose.ci.yml config -q && docker compose -f docker-compose.ci.yml up -d --wait && docker compose -f docker-compose.ci.yml ps'
```

期望:`config -q` 无输出(语法 OK);`ps` 里两个服务都是 `healthy`。

- [ ] **Step 6: 验证「可认证连接 + test 库授权」(这是 CI 里最容易翻车的一步)**

```bash
wsl -e bash -lc 'cd /mnt/d/pycharmproject/chat_app/chatapp && python3 -c "
import pymysql
c = pymysql.connect(host=\"127.0.0.1\", port=13306, user=\"chatapp\", password=\"chatapp_ci\", database=\"chatapp_dev\", connect_timeout=10)
with c.cursor() as cur:
    cur.execute(\"SELECT VERSION()\"); print(\"version\", cur.fetchone()[0])
    cur.execute(\"CREATE DATABASE IF NOT EXISTS test_chatapp_dev\"); print(\"create test db OK\")
    cur.execute(\"DROP DATABASE test_chatapp_dev\"); print(\"drop test db OK\")
c.close()
"'
```

期望:三行 OK。若 `create test db` 报 `(1044, "Access denied")`,说明 initdb 脚本没执行——`docker compose -f docker-compose.ci.yml down && up -d --wait` 再来一次。

- [ ] **Step 7: 提交**

```bash
git add docker-compose.ci.yml chatapp/db_setup_ci.sql
git commit -m "chore(scripts): 新增 CI 等价依赖容器 mysql8+redis7(端口避让本机开发环境)"
```

---

### Task 2: `verify.sh` 骨架与自测(TDD)

**Files:**
- Create: `scripts/test_verify.sh`
- Create: `scripts/verify.sh`

**Interfaces:**
- Produces:`scripts/verify.sh [选项] <子命令>...`,子命令集合 = `backend|web|imserver|app|contract|all|deps|bootstrap`;选项 `--list`、`--dry-run`、`--keep-deps`。退出码:0 全绿;1 用法错误;2 未知子命令或自检失败。后续所有任务只往里加函数,不改骨架。

> **执行中发现的缺口(2026-11-07 补):** WSL 系统 Python 是 3.12.3 且没有 Django/PyMySQL,
> 而 CI 用 3.11。因此 `backend` / `contract` 必须走一个专用 venv(`$HOME/venvs/chatapp`),
> 由新增的 `bootstrap` 子命令按 `chatapp/requirements.txt` 装好。
> 版本差异(3.12 本地 / 3.11 CI)是已知偏差:Django 5.2 两边都支持,真正的裁判仍是 CI;
> 若出现过只在一边红的用例,先怀疑版本差异,再考虑给 compose 加 python:3.11 服务。

- [ ] **Step 1: 先写自测(此时 `verify.sh` 还不存在,必须红)**

`scripts/test_verify.sh`:

```bash
#!/usr/bin/env bash
# verify.sh 的自测:只验「入口契约」(用法/退出码/子命令清单/--dry-run),
# 不真跑测试套件——真跑由 verify.sh 自己负责,这里防的是「脚本自己错了却报绿」。
set -uo pipefail
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
V="$ROOT/scripts/verify.sh"
fail=0
check() { # check <描述> <期望退出码> <命令...>
  local desc=$1 want=$2; shift 2
  "$@" >/dev/null 2>&1; local got=$?
  if [ "$got" = "$want" ]; then printf 'ok   %s\n' "$desc"
  else printf 'FAIL %s (期望退出 %s,实际 %s)\n' "$desc" "$want" "$got"; fail=1; fi
}
check "无参数打印用法并退出 1" 1 bash "$V"
check "未知子命令退出 2" 2 bash "$V" nosuchstack
check "--list 正常退出" 0 bash "$V" --list
for s in backend web imserver app contract; do
  out=$(bash "$V" --list 2>/dev/null)
  case $out in *"$s"*) printf 'ok   --list 含 %s\n' "$s";; *) printf 'FAIL --list 缺 %s\n' "$s"; fail=1;; esac
done
# --dry-run 的可用性用 deps 验:它是骨架里就已实现的子命令,
# backend/web/app 的具体断言由各自 Task 追加。
check "deps --dry-run 退出 0" 0 bash "$V" deps --dry-run
dry=$(bash "$V" deps --dry-run 2>/dev/null)
case $dry in *"docker compose"*) echo "ok   --dry-run 打印 docker compose";; *) echo "FAIL --dry-run 未打印 docker compose"; fail=1;; esac
[ "$fail" = 0 ] && echo "全部通过" || echo "有失败"
exit "$fail"
```

- [ ] **Step 2: 跑自测,确认它红**

```bash
wsl -e bash -lc 'cd /mnt/d/pycharmproject/chat_app && bash scripts/test_verify.sh'
```

期望:每个 `check` 都 FAIL(因为 `scripts/verify.sh` 不存在)。**这一步不许跳过**,否则你不知道自测到底测到了什么。

- [ ] **Step 3: 实现 `verify.sh` 骨架**

```bash
#!/usr/bin/env bash
# 本地复刻 CI 六轨的可执行入口。用法见 usage()。
#
# 设计原则:命令序列与环境变量必须与 .github/workflows/*.yml 逐项对齐,
# 但 CI 不调用本脚本——它是 CI 的镜像,不是 CI 的入口。
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
COMPOSE="$ROOT/docker-compose.ci.yml"
# 后端/契约用的解释器:专用 venv(见 Task 2 Interfaces 里的缺口说明)。
VENV=${CHATAPP_VENV:-$HOME/venvs/chatapp}
PY="$VENV/bin/python"
DRY_RUN=0
KEEP_DEPS=0

# 与 backend.yml 的 env 对齐;端口用 compose 里避让后的 13306/16379。
export SECRET_KEY=ci-only-not-a-real-secret
export DEBUG=1
export DB_NAME=chatapp_dev
export DB_USER=chatapp
export DB_PASSWORD=chatapp_ci
export DB_HOST=127.0.0.1
export DB_PORT=13306
export DB_SSL_DISABLED=0
export BROKER_URL=redis://127.0.0.1:16379/1
export REDIS_URL=redis://127.0.0.1:16379/0
export IM_SELF_URL=http://127.0.0.1:9101
export IM_SELF_WS_URL=ws://127.0.0.1:9100/im/ws
export IM_SELF_HTTP_URL=http://127.0.0.1:9101/im/api
export IM_SELF_SECRET=ci-fake-secret-32-bytes-minimum
export IM_SELF_INTERNAL_SECRET=ci-fake-internal-32-bytes-minimum
export SMS_DEV_MODE=1
export AUTO_APPROVE=1

usage() {
  cat <<'EOF'
用法: scripts/verify.sh [选项] <子命令> [子命令...]

子命令:
  backend    起依赖 → migrate → 后端全量测试 → OpenAPI 同改校验 → 压测脚本自测
  web        npm ci → 类型生成物同改校验 → type-check → lint → test → build
  imserver   单元 / 集成 / HTTP e2e(docker compose test)
  app        flutter analyze(零告警)+ flutter test
  contract   版本号三处一致 + App 模型字段 ⊆ OpenAPI
  all        依次跑 backend web imserver app contract
  deps       只起依赖容器
  bootstrap  建后端 venv 并装 requirements.txt(首次或依赖变更后跑一次)

选项:
  --list       列出子命令
  --dry-run    只打印将执行的命令
  --keep-deps  结束后不拆依赖容器
EOF
}

die() { printf '错误: %s\n' "$*" >&2; exit 2; }

run() { # run <说明> <命令...>
  local label=$1; shift
  printf '\n=== %s ===\n' "$label"
  if [ "$DRY_RUN" = 1 ]; then printf '+ %s\n' "$*"; return 0; fi
  "$@"
}

deps_up() {
  run "起依赖容器(MySQL 13306 / Redis 16379)" \
    docker compose -f "$COMPOSE" up -d --wait
}

deps_down() {
  # 注意:这里必须用 if,不能写 `[ … ] && { … }`——后者在 set -e 下,
  # 条件为假会让整条列表返回非零,直接把脚本打死。
  if [ "$KEEP_DEPS" = 1 ]; then
    echo "保留依赖容器(--keep-deps)"
    return 0
  fi
  run "拆除依赖容器" docker compose -f "$COMPOSE" down -v
}

stack_backend() { :; }
stack_web() { :; }
stack_imserver() { :; }
stack_app() { :; }
stack_contract() { :; }

stack_bootstrap() {
  run "创建 venv($VENV)" python3 -m venv "$VENV"
  run "升级 pip" "$VENV/bin/pip" install --upgrade pip
  run "安装后端依赖" "$VENV/bin/pip" install -r "$ROOT/chatapp/requirements.txt"
  run "自检" "$PY" -c "import django, pymysql; print('django', django.get_version())"
}

main() {
  local stacks=()
  while [ $# -gt 0 ]; do
    case $1 in
      --list|--help|-h) usage; exit 0 ;;
      --dry-run) DRY_RUN=1 ;;
      --keep-deps) KEEP_DEPS=1 ;;
      backend|web|imserver|app|contract|deps|all|bootstrap) stacks+=("$1") ;;
      -*) die "未知选项 $1" ;;
      *) die "未知子命令 $1(用 --list 看清单)" ;;
    esac
    shift
  done
  [ ${#stacks[@]} -eq 0 ] && { usage >&2; exit 1; }

  local ran_backend=0
  for s in "${stacks[@]}"; do
    case $s in
      deps) deps_up ;;
      bootstrap) stack_bootstrap ;;
      all) deps_up; stack_backend; stack_web; stack_imserver; stack_app; stack_contract; ran_backend=1 ;;
      backend) deps_up; stack_backend; ran_backend=1 ;;
      web) stack_web ;;
      imserver) stack_imserver ;;
      app) stack_app ;;
      contract) stack_contract ;;
    esac
  done
  [ "$ran_backend" = 1 ] && deps_down
  printf '\n全部通过\n'
}

main "$@"
```

- [ ] **Step 4: 跑自测,确认全绿**

```bash
wsl -e bash -lc 'cd /mnt/d/pycharmproject/chat_app && bash scripts/test_verify.sh'
```

期望:`全部通过`,退出码 0。此时 `backend` / `web` / `app` 分支还都是空函数,自测**刻意不碰它们**——它们的断言由 Task 3、Task 4、Task 6 各自追加,每个 Task 都从「断言红 → 实现 → 转绿」走一遍。

- [ ] **Step 5: 提交**

```bash
git add scripts/verify.sh scripts/test_verify.sh
git commit -m "feat(scripts): 新增 verify.sh 入口骨架与自测(CI 镜像,非 CI 入口)"
```

---

### Task 3: `backend` 子命令

**Files:**
- Modify: `scripts/verify.sh`(`stack_backend()` 函数体)
- Modify: `scripts/test_verify.sh`(增加 backend 的 dry-run 断言)

**Interfaces:**
- Consumes:Task 1 的 compose(端口 13306/16379)、Task 2 的 `run()` / `deps_up()`。
- Produces:`verify.sh backend` 跑完 = CI `backend.yml` 四步(migrate / test / OpenAPI 同改 / 压测自测)全绿。

- [ ] **Step 1: 给自测加断言(先红)**

在 `scripts/test_verify.sh` 的 `[ "$fail" = 0 ]` 之前插入:

```bash
bdry=$(bash "$V" backend --dry-run 2>/dev/null)
for needle in "manage.py migrate" "manage.py test" "manage.py spectacular" "perf.test_run"; do
  case $bdry in *"$needle"*) printf 'ok   backend dry-run 含 %s\n' "$needle";;
    *) printf 'FAIL backend dry-run 缺 %s\n' "$needle"; fail=1;; esac
done
```

跑 `wsl -e bash -lc 'cd /mnt/d/pycharmproject/chat_app && bash scripts/test_verify.sh'`,期望四条全 FAIL。

- [ ] **Step 2: 实现 `stack_backend()`**

```bash
stack_backend() {
  if [ "$DRY_RUN" = 0 ] && [ ! -x "$PY" ]; then
    die "没有可用的 venv:$PY。先跑 scripts/verify.sh bootstrap"
  fi
  cd "$ROOT/chatapp"
  run "迁移" "$PY" manage.py migrate --noinput
  run "后端全量测试" "$PY" manage.py test --noinput
  run "OpenAPI 生成物同改校验" "$PY" manage.py spectacular --file ../docs/api/openapi.yml --validate
  if [ "$DRY_RUN" = 0 ]; then
    git -C "$ROOT" diff --exit-code -- docs/api/openapi.yml \
      || die "docs/api/openapi.yml 落后于代码:重新生成并提交"
  fi
  cd "$ROOT"
  run "压测脚本自测" "$PY" -m unittest perf.test_run -v
}
```

- [ ] **Step 3: 建 venv 并装依赖(一次性,约 1–2 分钟)**

```bash
wsl -e bash -lc 'cd /mnt/d/pycharmproject/chat_app && export https_proxy="http://$(ip route show default | awk "{print \$3}" | head -1):7897" http_proxy="$https_proxy" && bash scripts/verify.sh bootstrap'
```

期望:最后打印 `django 5.2.x`。装不动先查代理(宿主 7897),别改脚本。

- [ ] **Step 4: 自测转绿**

```bash
wsl -e bash -lc 'cd /mnt/d/pycharmproject/chat_app && bash scripts/test_verify.sh'
```

期望:`全部通过`。

- [ ] **Step 5: 真跑一次(这条最慢,3–5 分钟)**

```bash
wsl -e bash -lc 'cd /mnt/d/pycharmproject/chat_app && bash scripts/verify.sh backend'
```

期望:最后一行 `全部通过`;退出码 0。若 `CommentCoverageTests` / `ApiDocsCoverageTests` / `OpenApiSchemaTests` 红,说明**代码本身有问题**(不是脚本问题),按报错修或不属本计划的改动就停下回报。

- [ ] **Step 6: 提交**

```bash
git add scripts/verify.sh scripts/test_verify.sh
git commit -m "feat(scripts): verify.sh 支持 backend(与 backend.yml 四步对齐)"
```

---

### Task 4: `web` 与 `contract` 子命令

**Files:**
- Modify: `scripts/verify.sh`
- Modify: `scripts/test_verify.sh`(追加 web / contract 断言)

**Interfaces:**
- Consumes:`web/package.json` 的脚本(`gen:api` / `type-check` / `lint` / `test:run` / `build`)、`scripts/sync_version.py --check`、`scripts/check_app_models.py`。
- Produces:`verify.sh web` / `verify.sh contract`。

- [ ] **Step 1: 给自测加 web / contract 断言(先红)**

在 `scripts/test_verify.sh` 的 `[ "$fail" = 0 ]` 之前插入:

```bash
wdry=$(bash "$V" web --dry-run 2>/dev/null)
case $wdry in *"npm run type-check"*) printf 'ok   web dry-run 含 type-check\n';;
  *) printf 'FAIL web dry-run 缺 type-check\n'; fail=1;; esac
cdry=$(bash "$V" contract --dry-run 2>/dev/null)
case $cdry in *"sync_version.py --check"*) printf 'ok   contract dry-run 含 sync_version\n';;
  *) printf 'FAIL contract dry-run 缺 sync_version\n'; fail=1;; esac
```

跑自测,期望这两条 FAIL(`stack_web` / `stack_contract` 还是空函数)。

- [ ] **Step 2: 实现两个函数**

```bash
stack_web() {
  cd "$ROOT/web"
  run "安装依赖" npm ci
  run "重新生成 API 类型" npm run gen:api
  if [ "$DRY_RUN" = 0 ]; then
    git -C "$ROOT" diff --exit-code -- web/src/api/schema.d.ts \
      || die "web/src/api/schema.d.ts 与 docs/api/openapi.yml 不一致"
  fi
  run "类型检查" npm run type-check
  run "代码规范(零告警)" npm run lint
  run "单元/组件测试" npm run test:run
  run "构建" npm run build
  cd "$ROOT"
}

stack_contract() {
  run "版本号三处一致" "$PY" "$ROOT/scripts/sync_version.py" --check
  run "App 模型字段 ⊆ OpenAPI" "$PY" "$ROOT/scripts/check_app_models.py"
}
```

- [ ] **Step 3: 自测转绿**

```bash
wsl -e bash -lc 'cd /mnt/d/pycharmproject/chat_app && bash scripts/test_verify.sh'
```

- [ ] **Step 4: 真跑**

```bash
wsl -e bash -lc 'cd /mnt/d/pycharmproject/chat_app && bash scripts/verify.sh contract web'
```

期望:`全部通过`。`npm ci` 需要网络,走 `/root/start-superagent.sh` 里那套代理环境。

- [ ] **Step 5: 提交**

```bash
git add scripts/verify.sh scripts/test_verify.sh
git commit -m "feat(scripts): verify.sh 支持 web 与 contract"
```

---

### Task 5: `imserver` 子命令

**Files:**
- Modify: `scripts/verify.sh`

**Interfaces:**
- Consumes:`imserver/docker-compose.test.yml`(服务 `test`,内含 mysql / redis 依赖)。
- Produces:`verify.sh imserver`。

- [ ] **Step 1: 先确认镜像能起(不起就别写脚本)**

```bash
wsl -e bash -lc 'cd /mnt/d/pycharmproject/chat_app/imserver && ls docker-compose.test.yml && docker compose -f docker-compose.test.yml config -q && echo compose-ok'
```

- [ ] **Step 2: 实现**

```bash
stack_imserver() {
  run "imserver 单元 / 集成 / HTTP e2e" \
    docker compose -f "$ROOT/imserver/docker-compose.test.yml" run --rm test bash /src/scripts/test_http.sh
}
```

- [ ] **Step 3: 真跑(首次会构建镜像,可能 5–10 分钟)**

```bash
wsl -e bash -lc 'cd /mnt/d/pycharmproject/chat_app && bash scripts/verify.sh imserver'
```

期望:`全部通过`。

- [ ] **Step 4: 提交**

```bash
git add scripts/verify.sh
git commit -m "feat(scripts): verify.sh 支持 imserver"
```

---

### Task 6: Linux Flutter + `app` 子命令

**Files:**
- Modify: `scripts/verify.sh`(`stack_app()`)
- (WSL 侧,不入库)`:~/flutter`

**Interfaces:**
- Produces:`verify.sh app`;`FLUTTER_BIN` 环境变量可覆盖 SDK 路径,默认 `$HOME/flutter/bin/flutter`(**不是** `/mnt/d/.../flutter`)。

- [ ] **Step 1: 在 WSL 装 Linux Flutter 3.47.2(与 `app.yml` 的 `flutter-version` 一致)**

```bash
wsl -e bash -lc 'set -e; [ -d "$HOME/flutter" ] || git clone --depth 1 -b 3.47.2 https://github.com/flutter/flutter.git "$HOME/flutter"; "$HOME/flutter/bin/flutter" --version; "$HOME/flutter/bin/flutter" config --no-analytics'
```

期望:打印 `Flutter 3.47.2 • channel stable`。若 git clone 卡住,检查代理(宿主 7897)。

- [ ] **Step 2: 实现 `stack_app()`**

```bash
stack_app() {
  local flutter=${FLUTTER_BIN:-$HOME/flutter/bin/flutter}
  [ -x "$flutter" ] || die "找不到 Linux Flutter:$flutter(见 docs/ops/superagent.md)"
  cd "$ROOT/app"
  run "拉依赖" "$flutter" pub get
  run "静态检查(零告警)" "$flutter" analyze
  run "测试" "$flutter" test
  cd "$ROOT"
}
```

- [ ] **Step 3: 真跑**

```bash
wsl -e bash -lc 'cd /mnt/d/pycharmproject/chat_app && bash scripts/verify.sh app'
```

期望:`flutter analyze` 无告警、`flutter test` 全绿。

- [ ] **Step 4: 提交**

```bash
git add scripts/verify.sh
git commit -m "feat(scripts): verify.sh 支持 app(Linux Flutter 3.47.2,与 app.yml 同版本)"
```

---

### Task 7: `AGENTS.md`(给 agent 的执行约束)

**Files:**
- Create: `AGENTS.md`(仓库根)

- [ ] **Step 1: 写文件**

````markdown
# AGENTS.md — 给在这里干活的 agent

本文件只写**执行约束**(什么不准做、怎么做才算对)。项目全貌、里程碑与导航看
[CLAUDE.md](CLAUDE.md);对外接口看 [docs/api/README.md](docs/api/README.md);排障看 [docs/pitfalls/README.md](docs/pitfalls/README.md)。
冲突时以本文件 → 测试 → `docs/` 为准。

## 一、开工前必读(按改动面选)

| 改什么 | 先读 |
|---|---|
| 后端 | `docs/standards/python.md`、`docs/pitfalls/backend.md` |
| IM 协议 / imserver | `imserver/tests/fixtures/ws/README.md`、`docs/pitfalls/im.md` |
| App | `docs/superpowers/specs/2026-09-15-ui-design-language-design.md`(「心跳」,强制)、`docs/pitfalls/frontend.md` |
| 网页端 | `docs/pitfalls/web.md` |

## 二、一单一条栈

`backend` / `web` / `imserver` / `app` / `docs` 只能挑一条。跨栈请回报让主人拆单。
契约联动属于**同一条栈的附带改动**,必须同一次做完:改视图 → 重生成 `docs/api/openapi.yml` 并同改 `docs/api/*.md`;改 WS 帧 → fixture + imserver + App + Web 四处同改;改视觉 token → `app/lib/core/theme/*.dart` 与 `web/src/styles/tokens.css` 双份;升版本号 → 三处一致并在 `docs/ops/release.md` §5 记一行。

## 三、验证:唯一入口是 `scripts/verify.sh`

| 你要做的 | 跑 |
|---|---|
| 后端 | `scripts/verify.sh backend` |
| 网页端 | `scripts/verify.sh web` |
| imserver | `scripts/verify.sh imserver` |
| App | `scripts/verify.sh app` |
| 只改文档 | `scripts/verify.sh contract` |

**推之前必须绿。** 把它的末尾输出贴进 PR 描述。它和 CI 跑同一套命令、同一套环境变量(`docker-compose.ci.yml`,MySQL 在 13306、Redis 在 16379),所以本地绿≈CI 绿。

## 四、门禁:这些不走流程必红

| 门禁 | 违反后果 |
|---|---|
| 错误契约 `{"code","message","request_id"}`,业务码 = HTTP 前 3 位 + 2 位序号 | `config/tests.py` 红 |
| 新增/改 `/api/v1` 接口必须同改 `docs/api/` 分册 | `ApiDocsCoverageTests` 红 |
| 对外字段变更必须重生成 `docs/api/openapi.yml` | `backend.yml` 的 `git diff --exit-code` 红 |
| 新增/改 `.py` 必须有模块与函数 docstring(公开函数带 `Args:`) | `CommentCoverageTests` 红 |
| 版本号三处一致(`app/pubspec.yaml` 是唯一事实来源) | `sync_version.py --check` 红 |
| `im/tasks.py` 是 IM 副作用的唯一入口,参数一律 user_id | 代码审查拒 |
| 响应路径禁止任何第三方网络调用 | 代码审查拒 |

## 五、PR 规矩

- 标题:`<type>(<scope>): <中文摘要>`;正文必须写四问:改了什么 / 怎么验的(贴 verify 输出)/ 留了什么给人验 / 求人不求人。
- **不要**自己合并、不要开 auto-merge、不要 `gh pr merge`。
- **碰 `app/` 的 UI 可见改动**:你跑不了模拟器(它只在主人的 Windows 上)。PR 开成 **draft**,正文写「等待模拟器验收」,**不得声称 ready**;Before/After 截图由人补。
- 一个 PR 只解决一个 issue;发现顺手的坑,写进 PR 正文的「遗留」段,不要顺手改。

## 六、绝对不要做

- 改 `flutter/`(Windows Flutter SDK 源码,自带独立 .git)
- 改 `.remember/`、`.env`、任何密钥文件
- 升版本号、打 tag、建 Release、跑 `docs/ops/release.md` 里的发版动作
- `ssh` / `scp` / `rsync` 到生产;碰 `deploy/` 下任何脚本
- 提交生成物以外的手改:(`docs/api/openapi.yml`、`web/src/api/schema.d.ts` 只能由命令生成)

## 七、卡住怎么办

提**一个**具体问题,带上你已排除的选项与证据;能用默认值就先按默认值干完并在正文标注「假定 X」。不确定方向时宁可 `blocked`,不要猜着改一大片。
````

- [ ] **Step 2: 校验它引用的路径都存在**

```bash
wsl -e bash -lc 'cd /mnt/d/pycharmproject/chat_app && for f in CLAUDE.md docs/api/README.md docs/pitfalls/README.md docs/standards/python.md docs/superpowers/specs/2026-09-15-ui-design-language-design.md imserver/tests/fixtures/ws/README.md docs/ops/release.md docker-compose.ci.yml scripts/verify.sh; do [ -e "$f" ] && echo "ok $f" || echo "MISSING $f"; done'
```

期望:全 `ok`。

- [ ] **Step 3: 提交**

```bash
git add AGENTS.md
git commit -m "docs(agents): 新增仓库级 AGENTS.md(门禁表 + verify 入口 + PR 规矩)"
```

---

### Task 8: Issue / PR 模板

**Files:**
- Create: `.github/ISSUE_TEMPLATE/agent-task.yml`
- Create: `.github/pull_request_template.md`

- [ ] **Step 1: 写 `.github/ISSUE_TEMPLATE/agent-task.yml`**

```yaml
name: 交给 agent 的工单
description: 一条可独立验收的改动。一单一条栈。
title: "[工单] "
labels: ["agent"]
body:
  - type: markdown
    attributes:
      value: |
        填完在评论里 `@shiliu655` 触发。**一单一条栈**;跨栈请拆单。
  - type: textarea
    id: background
    attributes:
      label: 背景
      description: 现在是什么样、为什么不对、相关文件与 issue。
    validations:
      required: true
  - type: textarea
    id: acceptance
    attributes:
      label: 验收口径
      description: 可执行、可判断的标准。写「跑什么命令、看到什么」,不要写「优化一下」。
      placeholder: |
        1. `scripts/verify.sh backend` 全绿
        2. GET /api/v1/xxx 返回 {a,b,c}
        3. 老客户端行为不变(回归测试 xxx 仍绿)
    validations:
      required: true
  - type: dropdown
    id: stack
    attributes:
      label: 影响栈(只能选一条)
      options:
        - backend
        - web
        - imserver
        - app
        - docs
    validations:
      required: true
  - type: dropdown
    id: touches_app_ui
    attributes:
      label: 是否有 App 端可见变化
      description: 选「是」时 PR 必须开 draft,由人做模拟器验收后才合并。
      options: ["否", "是"]
    validations:
      required: true
  - type: textarea
    id: forbidden
    attributes:
      label: 禁止事项
      description: 明确不许顺手做的事,例如「不要动 xxx 表结构」「不要改版本号」。
      value: "不改版本号、不发版、不合并 PR、不碰 flutter/ 与 .remember/。"
  - type: textarea
    id: out_of_scope
    attributes:
      label: 明确不在本期范围
      description: 想得到但这次不做的相邻改动,避免 PR 变大。
```

- [ ] **Step 2: 写 `.github/pull_request_template.md`**

```markdown
## 改了什么

<!-- 一句话 + 关键文件清单 -->

## 怎么验的

<!-- 贴 `scripts/verify.sh <stack>` 的末尾输出;贴不出的部分说明为什么 -->

## 留了什么给人验

<!-- 模拟器手测 / 真机 / 生产观测 等 agent 做不到的验收点;没有就写「无」 -->

## App 手测证据(仅当改动涉及 app/ 的可见变化)

- [ ] 已在 Windows 的 Pixel_7 模拟器上逐页手测并截图(截图链接:)
- [ ] 本 PR 未涉及 App 可见变化

## 遗留(不在本期)

<!-- 顺路发现的坑,单独立 issue,不在这里改 -->
```

- [ ] **Step 3: 校验 YAML 语法**

```bash
wsl -e bash -lc 'cd /mnt/d/pycharmproject/chat_app && python3 -c "import yaml,sys; yaml.safe_load(open(\".github/ISSUE_TEMPLATE/agent-task.yml\")); print(\"yaml ok\")"'
```

- [ ] **Step 4: 提交**

```bash
git add .github/ISSUE_TEMPLATE/agent-task.yml .github/pull_request_template.md
git commit -m "chore(github): 新增 agent 工单模板与 PR 模板"
```

---

### Task 9: 改全局约定(Windows 侧,不入库)

**Files:**
- Modify: `C:\Users\20157\.dsh\AGENTS.md`

- [ ] **Step 1: 把「一律内联」改成新口径**

原文:

```markdown
- **superpowers 类任务一律内联执行**:用 `executing-plans`,在当前会话里逐任务完成。
- **不要为了执行计划而派发子 agent**(不启用 `subagent-driven-development` / `dispatching-parallel-agents`),
  除非用户当次明确要求分派。
```

改为:

```markdown
- **设计与评审内联,实现走工单**:写 spec / 计划 / 评审 / 验收 / 发版在当前会话里做;
  实现类工作开成带验收口径的 issue,评论 `@shiliu655` 交给 WSL 的 superagent worker
  (流程见各仓库 `docs/superpowers/specs/*-superagent-dev-workflow-design.md`)。
- **不派发子 agent**(不启用 `subagent-driven-development` / `dispatching-parallel-agents`),
  除非用户当次明确要求分派。superagent 工单不是子 agent,它是仓库外的长期 worker。
```

- [ ] **Step 2: 确认没有第二处冲突表述**

```powershell
Select-String -Path C:\Users\20157\.dsh\AGENTS.md -Pattern "内联|subagent|分派"
```

期望:只剩改后的两条。

- [ ] **Step 3: 无需提交(不在任何仓库内)**

---

### Task 10: 面板设置(prompt 专属条款 + 执行环境)

**Files:**
- Modify: 面板 `prompts`(通过管理 API,`http://127.0.0.1:3082/orchestrator/api/prompts`)
- Modify: 面板 `settings/executor`(同一 API 前缀,`…/settings/executor`)

**Interfaces:**
- Consumes:`GET prompts` 的 `current.revision`(PUT 作 `baseRevision`)、`GET settings` 的 `blocks.executor.revision` / `blocks.executor.value`。
- Produces:`prompts.config.scope` 与 `.delivery` 追加项目条款;`executor.value` 的 `maxWorkers=2`、`blockedCommands=[ssh,scp,rsync]`、`prepare` 去掉代理导出。

- [ ] **Step 1: 读当前值与 revision**

```bash
wsl -e bash -lc 'curl -s -H "x-orchestrator-request: 1" http://127.0.0.1:3082/orchestrator/api/prompts | python3 -c "import json,sys; d=json.load(sys.stdin); print(\"revision\", d[\"current\"][\"revision\"]); print(\"keys\", list(d[\"current\"][\"config\"]))"'
```

- [ ] **Step 2: 写入(shell 脚本,幂等:已含标记就跳过)**

```bash
wsl -e bash -lc 'cat > /tmp/patch_prompts.py <<"PY"
import json, urllib.request

API = "http://127.0.0.1:3082/orchestrator/api/prompts"
HDR = {"x-orchestrator-request": "1", "content-type": "application/json"}

SCOPE = """
This repository (shiliu153/chatapp) allows one stack per ticket: backend, web, imserver, app or docs.
Ask the person to split a request that spans stacks. Contract-linked edits belong to the same ticket as the
change that triggers them: regenerating docs/api/openapi.yml together with docs/api/*.md, changing a WS frame
in imserver/tests/fixtures/ws together with imserver, app and web, changing a heartbeat token in both
app/lib/core/theme and web/src/styles/tokens.css, and bumping the version in the three places sync_version.py checks.
"""

DELIVERY = """
Project rules for shiliu153/chatapp. Read AGENTS.md at the repository root first; it lists the gates whose tests
fail when skipped. Before pushing, run `scripts/verify.sh <stack>` for each stack you touched and paste the tail of
its output into the PR description: CI runs the same commands against docker-compose.ci.yml, so a green local run
means a green CI run. One ticket touches one stack.

UI-visible changes under app/ cannot be verified by you: the Android emulator exists only on the operator's Windows
host. Open such a PR as a draft, state in the description that it waits for emulator verification, and do not report
it as ready, however much of the code you validated. The person runs the emulator, adds the Before/After evidence and
merges. A person merges every PR: never enable auto-merge and never run a merge command.
"""

def main() -> None:
    """Append the project clauses to the scope and delivery prompt sections, once."""
    with urllib.request.urlopen(urllib.request.Request(API, headers=HDR)) as r:
        state = json.load(r)
    rev = state["current"]["revision"]
    cfg = dict(state["current"]["config"])
    changed = False
    for key, add in (("scope", SCOPE), ("delivery", DELIVERY)):
        cur = cfg.get(key) or ""
        if "shiliu153/chatapp" in cur:
            print(f"{key}: 已含项目条款,跳过")
            continue
        cfg[key] = (cur.rstrip() + "\n" + add).strip()
        changed = True
    if not changed:
        print("无需改动")
        return
    body = json.dumps({"config": cfg, "baseRevision": rev}).encode()
    req = urllib.request.Request(API, data=body, headers=HDR, method="PUT")
    with urllib.request.urlopen(req) as r:
        print("saved", r.status)

main()
PY
python3 /tmp/patch_prompts.py'
```

期望:输出 `scope: …`/`delivery: …` 与 `saved 200`(或第二次起输出「已含项目条款,跳过」+「无需改动」)。

- [ ] **Step 3: 回读确认**

```bash
wsl -e bash -lc 'curl -s -H "x-orchestrator-request: 1" http://127.0.0.1:3082/orchestrator/api/prompts | python3 -c "import json,sys; c=json.load(sys.stdin)[\"current\"][\"config\"]; print(\"scope ok\", \"shiliu153/chatapp\" in c[\"scope\"]); print(\"delivery ok\", \"draft\" in c[\"delivery\"])"'
```

期望:两行都 `True`。

- [ ] **Step 4: 面板人工确认一次**

浏览器打开 `http://127.0.0.1:3082` → Prompts,确认 Scope / Delivery 两段末尾有项目条款、且**没有**任何 auto-merge 相关指令。

- [ ] **Step 5: 收紧执行环境(maxWorkers / blockedCommands / prepare 去代理)**

```bash
wsl -e bash -lc 'cat > /tmp/patch_executor.py <<"PY"
import json, urllib.request

API = "http://127.0.0.1:3082/orchestrator/api"
HDR = {"x-orchestrator-request": "1", "content-type": "application/json"}

PREPARE = (
    "git -C /root/src/chatapp fetch --no-tags "
    "\"https://github.com/$DSH_SUPERAGENT_GITHUB_REPOSITORY.git\" "
    "\"${DSH_SUPERAGENT_GITHUB_PR_HEAD:-HEAD}:refs/dsh-superagent/$DSH_SUPERAGENT_TICKET\" && "
    "git -C /root/src/chatapp worktree add -b \"agent/$DSH_SUPERAGENT_NAME\" "
    "\"$DSH_SUPERAGENT_DIR\" \"refs/dsh-superagent/$DSH_SUPERAGENT_TICKET\""
)

def main() -> None:
    """Tighten the executor block: 2 workers, blocked network CLIs, proxy-free prepare."""
    with urllib.request.urlopen(urllib.request.Request(API + "/settings", headers=HDR)) as r:
        block = json.load(r)["blocks"]["executor"]
    value = dict(block["value"])
    value["maxWorkers"] = 2
    # 按名字拦(shim 只认命令名);`gh pr merge` 这种子命令拦不住,
    # 真正的护栏是 delivery 段「人合每个 PR」+ 分支保护。
    value["blockedCommands"] = ["ssh", "scp", "rsync"]
    # 代理由 /root/start-superagent.sh 在启动时导出,worker 继承;
    # 不再在 prepare 里重复 export,免得两处漂移。
    value["prepare"] = PREPARE
    body = json.dumps({"value": value, "revision": block["revision"]}).encode()
    req = urllib.request.Request(API + "/settings/executor", data=body, headers=HDR, method="PUT")
    with urllib.request.urlopen(req) as r:
        print("saved", r.status, r.read().decode()[:200])

main()
PY
python3 /tmp/patch_executor.py'
```

期望:输出 `saved 200 …`。若返回 409,说明 revision 过期(面板刚被人改过),重跑一次即可。

- [ ] **Step 6: 回读并确认 eval 仍是 observe**

```bash
wsl -e bash -lc 'curl -s -H "x-orchestrator-request: 1" http://127.0.0.1:3082/orchestrator/api/settings | python3 -c "
import json,sys
b=json.load(sys.stdin)[\"blocks\"]
e=b[\"executor\"][\"value\"]
print(\"maxWorkers\", e[\"maxWorkers\"]); print(\"blocked\", e[\"blockedCommands\"])
print(\"prepare has proxy:\", \"proxy\" in e[\"prepare\"])
print(\"eval mode\", b[\"eval\"][\"value\"][\"mode\"])
"'
```

期望:`maxWorkers 2`、`blocked ['ssh','scp','rsync']`、`prepare has proxy: False`、`eval mode observe`。

- [ ] **Step 7: 用一条真实工单验证代理没被弄坏**

跑 Task 12 的 Step 1–3(开一条 docs 工单并触发)。若 Ticket 卡在 `The prepare command failed`,几乎一定是代理:**先**确认 `start-superagent.sh` 里那几个 `export` 仍在、宿主 7897 可用,再 Retry;不要急着把代理加回 prepare。

---

### Task 11: 巡检、运维手册与工单卫生

**Files:**
- Create: `docs/ops/superagent.md`
- Create: `scripts/superagent-prune.sh`
- Create(本机会话,不入库):每小时定时任务

- [ ] **Step 1: 写 `scripts/superagent-prune.sh`**

```bash
#!/usr/bin/env bash
# 列出/清理 dsh-superagent 的工单 worktree。默认只列,`--apply` 才删。
# 只删「干净且分支已合并进 origin/master」的 worktree;有未提交改动的只报告不动。
set -euo pipefail
CLONE=${CLONE:-/root/src/chatapp}
WORKROOT=${WORKROOT:-/root/.dsh/state/superagent/work}
APPLY=0
[ "${1:-}" = "--apply" ] && APPLY=1

git -C "$CLONE" fetch --no-tags origin master
BASE=$(git -C "$CLONE" rev-parse origin/master)

git -C "$CLONE" worktree list --porcelain | awk '/^worktree /{print $2}' | while read -r wt; do
  [ "$wt" = "$CLONE" ] && continue
  case $wt in "$WORKROOT"/*) ;; *) continue ;; esac
  br=$(git -C "$wt" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')
  dirty=$(git -C "$wt" status --porcelain 2>/dev/null | wc -l)
  merged=no
  git -C "$CLONE" merge-base --is-ancestor "$br" "$BASE" 2>/dev/null && merged=yes
  printf '%-60s branch=%-45s dirty=%s merged=%s\n' "$wt" "$br" "$dirty" "$merged"
  if [ "$APPLY" = 1 ] && [ "$dirty" = 0 ] && [ "$merged" = yes ]; then
    git -C "$CLONE" worktree remove --force "$wt"
    git -C "$CLONE" branch -D "$br" >/dev/null 2>&1 || true
    echo "  已清理"
  fi
done

if [ "$APPLY" = 1 ]; then
  git -C "$CLONE" worktree prune
  git -C "$CLONE" for-each-ref --format='%(refname)' 'refs/dsh-superagent/*' | while read -r ref; do
    git -C "$CLONE" update-ref -d "$ref"; echo "删除 $ref"
  done
fi
```

- [ ] **Step 2: 先只读跑一次,确认不会误删**

```bash
wsl -e bash -lc 'bash /mnt/d/pycharmproject/chat_app/scripts/superagent-prune.sh'
```

期望:打印现有 worktree 与 `dirty/merged` 状态,**不删任何东西**。此时 PR #95 的工单目录应显示 `merged=no`(它还没合)。

- [ ] **Step 3: 写 `docs/ops/superagent.md`**

````markdown
# superagent 运维手册(WSL)

> 面板:`http://127.0.0.1:3082`(Windows 浏览器直接开)。Overview 只列「需要人」的项;健康时是空的。
> 设计见 [docs/superpowers/specs/2026-11-07-superagent-dev-workflow-design.md](../superpowers/specs/2026-11-07-superagent-dev-workflow-design.md)。

## 1. 启停与身份

| 事 | 命令 |
|---|---|
| 启动 / 查状态 / 停止 | `wsl -e bash /root/start-superagent.sh start\|status\|stop` |
| 状态退出码 | `0` 正常 · `1` 没跑/跑了两份/不响应(可试重启)· `2` 某部件报错(重启无效)· `3` 等设置 |
| agent 账号 | `~/.local/bin/gh-agent api user --jq .login` → `shiliu655` |
| 仓库母体 | `/root/src/chatapp`(工单 worktree 在 `/root/.dsh/state/superagent/work/`) |
| 数据 | `/root/.dsh/state/superagent/orchestrator.sqlite`(**升级前必须备份**) |

模型:`wb-pool` / `cn:deepseek-v4.1-flash`,密钥在 `/root/.dsh/superagent.env`。
代理:`start-superagent.sh` 已导出宿主网关 `:7897`;代理挂了表现为 fetch / pub / npm 全部超时,先修代理再动别的。

## 2. Ticket 卡住了

| 现象 | 处置 |
|---|---|
| `person / blocked`、`person / failed` | 面板上直接回一句话给它继续;或 **Retry** 换一个 Assignment(同 Session、同目录、同分支) |
| `person / delivery` | Input 没送达,重试是唯一解法;**不要**删工单 |
| `The prepare command failed: …` | 输出里写着原因(克隆路径、代理、ref 冲突)。修好后 Retry |
| 工单跑到一半不动 | 先看面板 `load` 与 `worker` 健康位;进程还在就 Retry,进程没了按 §1 重启 |

## 3. 一次工单的完整闭环(人工部分)

1. 面板/issue 收到「PR #N 就绪」→ 评审 diff。
2. 碰 `app/` 的:PR 是 draft,拉分支到 Windows → 装模拟器 → 逐页手测截图 → 贴进 PR → 勾模板第 4 项。
3. CI 六轨绿 → **squash 合并** → 删分支。
4. 合并后跑一次 `scripts/superagent-prune.sh --apply` 清 worktree 与 `refs/dsh-superagent/*`。

## 4. 环境自检(怀疑本地绿 ≠ CI 绿时)

```bash
wsl -e bash -lc 'cd /mnt/d/pycharmproject/chat_app && docker compose -f docker-compose.ci.yml up -d --wait && bash scripts/verify.sh backend --keep-deps'
wsl -e bash -lc 'docker compose -f /mnt/d/pycharmproject/chat_app/docker-compose.ci.yml down -v'
```

环境变量与端口:MySQL `127.0.0.1:13306`、Redis `127.0.0.1:16379`(避开 Windows 本机 3306/6379)。
Linux Flutter:`~/flutter`(3.47.2,与 `app.yml` 同版本);**不要**用 `/mnt/d/.../flutter`(Windows SDK)。

## 5. 升级与回滚

```bash
# 1) 确认没有 Executor 正在跑(面板 Overview 无 Working)
cp /root/.dsh/state/superagent/orchestrator.sqlite /root/.dsh/state/superagent/orchestrator.sqlite.bak-$(date +%F)
cd /root/dsh-superagent && git pull && pnpm install && pnpm build
bash /root/start-superagent.sh restart && bash /root/start-superagent.sh status
```

新版迁移过的库**旧版打不开**:回滚必须用上面那份备份。升级后检查面板 Prompts 里标注 `Default updated` 的段。

## 6. 授权与边界(改之前想清楚)

- 允许清单只有 `shiliu153`;bots 仅 `dependabot[bot]`;eval 模式 `observe`。
- `blockedCommands` 只是按名字拦的 shim,**不是安全边界**;真正的边界是 `/root/.ssh` 保持为空 + 人合 PR。
- 不自合:面板里不存在 merge CLI,所有 PR 由人 squash。
````

- [ ] **Step 4: 建每小时巡检(在 Windows 常用 profile 里,不在 superagent profile)**

用本会话的 `schedule_create` 建一条每小时任务,`target=this_session`(或你常用的那个 profile):

- rrule:`FREQ=HOURLY;INTERVAL=1`
- 标题:`检查 superagent 服务状态`
- prompt:

```text
检查 dsh-superagent:运行 `wsl -e bash /root/start-superagent.sh --profile superagent status`。
退出 0:什么都不做,也不要说话。
退出 2:不要重启;把 `errors` 里每一项连同 detail 告诉我(已经报过同一项就别说)。
退出 3:不要重启;把 `setup` 要求的东西告诉我(已经报过就别说)。
如果输出里 manually_stopped: true,保持停止,不要动它。
其余(退出 1):运行 `wsl -e bash /root/start-superagent.sh --profile superagent --respect-stop restart`,
它退出码含义同上:0 表示已恢复,不说话;2、3 按上面处理;若仍退出 1,读最新的
/root/dsh-superagent/.artifacts/dsh-superagent-superagent-*.log,能修就修,并告诉我哪里坏了、你做了什么。
```

- [ ] **Step 5: 提交脚本与手册**

```bash
git add scripts/superagent-prune.sh docs/ops/superagent.md
git commit -m "docs(ops): superagent 运维手册 + 工单 worktree 清理脚本"
```

---

### Task 12: 端到端验收(P1 门槛)

**Files:** 无代码改动;验证前 11 个任务是否真的串起来了。

- [ ] **Step 1: 开一条只改文档的工单**

用 Task 8 的模板开 issue(影响栈 `docs`,App 可见变化 `否`),验收口径必须包含「`scripts/verify.sh contract` 全绿」与「PR 正文贴输出」。

- [ ] **Step 2: 评论触发**

```
@shiliu655 按 issue 验收口径执行。
```

- [ ] **Step 3: 观察是否出现「先本地 verify 再推」**

```bash
wsl -e bash -lc 'git -C /root/src/chatapp worktree list'
```

期望:出现一个新的 `agent/...` worktree。PR 出现后检查正文:是否贴了 `verify.sh` 输出、是否按模板四问写。

- [ ] **Step 4: 记录结果**

| 指标 | 目标 |
|---|---|
| 人出手次数 | 2(开单确认 + PR 结论) |
| CI 往返 | ≤1 轮 |
| 是否需要人重写 | 否 |

不达标就回到对应 Task:CI 往返多 → 查它有没有真跑 `verify.sh`(Task 10 的 delivery 段);人出手多 → 查 `communication` 段噪音。

- [ ] **Step 5: 处理历史遗留 PR #95**

按 spec §8 默认值:评审该 PR(纯文档 3 增 3 删、`mergeable_state: clean`、worker 已就范围外问题提了一个具体问题)→ 回答它「括号本期不动」→ squash 合并 → 跑 `scripts/superagent-prune.sh --apply`。

---

## 执行顺序与提交边界

| 顺序 | Task | 建议 PR |
|---|---|---|
| 1 | Task 1–6(环境与脚本) | 一个 PR:`chore(scripts): 本地复刻 CI 六轨的可执行验证入口` |
| 2 | Task 7–8(说明书与模板) | 一个 PR:`docs(agents): AGENTS.md + 工单/PR 模板` |
| 3 | Task 9–10(全局约定与面板设置) | 不入库,单独确认(面板改动改完立刻生效) |
| 4 | Task 11(运维与巡检) | 一个 PR:`docs(ops): superagent 运维手册 + 清理脚本` |
| 5 | Task 12(端到端验收) | 无 PR,产出验收记录 |

每完成一个 Task:跑该 Task 的验证命令 → 提交 → 再进下一个。**不要**把多个 Task 攒在一起提交。

---

## 执行记录(2026-11-07)

计划执行完毕:P0–P3 全部落地并验证,Task 12 的端到端验收见 §执行记录.4。

### 1. 与计划的偏差(每一条都是「计划没想到、真跑才暴露」)

| # | 计划怎么写 | 实际怎么改 | 证据 |
|---|---|---|---|
| 1 | Task 3 假定 `python3 manage.py` 能跑 | WSL 系统 Python 3.12 上没有 Django/PyMySQL,且 `python3-venv` 未装 → 新增 `bootstrap` 子命令,后端统一走 `~/venvs/chatapp` | 首次 `manage.py` 直接 `ModuleNotFoundError`;`python3 -m venv` 报 `ensurepip is not available` |
| 2 | 用 `REDIS_URL` 指向容器 Redis | `TESTING` 模式下 `config/settings.py` 读的是 `TEST_REDIS_HOST` / `TEST_REDIS_PORT`(默认 6379,并切 DB15/DB14),**不读 `REDIS_URL`** | 未指过去时全量测试 `Ran 875 tests`,`failures=69, errors=359`,报 `ConnectionInterrupted: Error 111 connecting to 127.0.0.1:6379` |
| 3 | 用 `git diff --exit-code` 校验生成物 | Windows 检出是 CRLF,WSL 的 git 把 **1094 个文件**都算成改动 → 改成 `check_artifact`:比 `HEAD:path` 的内容、忽略行尾,失败时打印前 40 行差异 | `git diff --stat` 在 WSL 里输出 `1094 files changed, 215971 insertions(+)`;Windows 侧只有 3 个文件 |
| 4 | 未约束 Node 版本 | `web.yml` 用 Node 22,WSL 默认 24 → 装 `~/node22` 并在脚本里钉住(可用 `CHATAPP_NODE_MAJOR` 覆盖) | Node 24 下 `profile-store.spec.ts`「上传照片走 multipart」报 `webidl.is.File` 断言失败,88/89 文件通过 |
| 5 | 未约束工作目录的文件系统 | `/mnt/*` 是 9p,`vitest` 起 fork worker 超时 → 新增 `assert_linux_fs`,web/app 在 `/mnt/*` 下直接拒绝并给出原因 | `[vitest-pool]: Failed to start forks worker … Timeout waiting for worker to respond`,54 个 unhandled error |
| 6 | 计划以为 openapi 生成物是最新的 | master 上 `docs/api/openapi.yml` 停在 `1.0.9` 而代码已是 `1.0.10`:升版本那次只碰了 `app/pubspec.yaml` 与 `web/package.json`,**不在 `backend.yml` 的 paths 过滤里**,backend 轨从未被触发 → 本分支一并重新生成 | `spectacular` 重新生成后 `-version: 1.0.9 / +version: 1.0.10` |

### 2. 交付物与 PR

| 内容 | PR / 位置 |
|---|---|
| Task 1–6:依赖容器 + `scripts/verify.sh` 五栈 + 自测 + openapi 同步 | **#99**(已 squash 合并) |
| Task 7–8:`AGENTS.md` + 工单/PR 模板 | **#100**(已合并) |
| Task 11:运维手册 + `superagent-prune.sh` | **#101**(已合并) |
| Task 9:全局约定改为「设计评审内联、实现走工单」 | `~/.dsh/AGENTS.md`(不入库) |
| Task 10:面板 prompt 项目条款 + `maxWorkers=2` + `blockedCommands=[ssh,scp,rsync]` + `prepare` 去代理 | 面板 `127.0.0.1:3082`(不入库) |
| 每小时巡检 | schedule `schedule-10c540bf`(target = 当前 Windows 会话,首跑 22:05) |

### 3. 验证结果

- WSL Linux worktree(`/root/verify-tt`)里 `scripts/verify.sh all`:**exit 0**,五栈全过
  - backend:`Ran 875 tests … OK` + 生成物一致 + 压测自测 `Ran 39 tests … OK`
  - web:npm ci → gen:api 一致 → type-check → lint → test → build
  - imserver:单元 / 集成 / HTTP e2e,`e2e ok`
  - app:`flutter analyze` 零告警 + `flutter test` 通过
  - contract:版本号三处一致 + App 模型字段 ⊆ 契约
- `scripts/test_verify.sh`:`全部通过`
- `scripts/superagent-prune.sh`(只读):正确列出工单 worktree 且不误删(PR #95 当时显示 `merged=no`)
- 服务状态:`status` 退出 0,`health` 全 `ready`

### 4. Task 12 端到端验收

- 历史遗留 **PR #95** 按新流程收尾:回答问题(括号本期不动)→ squash 合并 → 这是第一条「人合」样本
- 新开 **issue #102**(docs 栈,无 App 可见变化,验收口径含 `scripts/verify.sh contract`),评论 `@shiliu655` 触发
- 观察到的行为:Ticket 在 `/root/.dsh/state/superagent/work/testing-pitfalls-section-74ac0662bb76` 起 worktree,基线是该次合并后的 master(`1bdc941`),符合预期

### 5. 新增的本机依赖(WSL)

`python3.12-venv`、`unzip`、`xz-utils`、`libglu1-mesa`;`~/venvs/chatapp`(后端)、`~/node22`(Node 22)、`~/flutter`(3.47.2)。已写进 `docs/ops/superagent.md`。

### 6. P4 首单验收(#104 → PR #106)踩到的新坑(2026-11-07)

首单 = `[工单] backend.yml 的 paths 缺 app/pubspec.yaml` → PR **#106**(`04a5e7f`,squash 成 `baab594`)。
改动本身无悬念(1 文件 +2/−0),下面六条是这轮才暴露的。

| # | 现象 | 原因 | 处置 |
|---|---|---|---|
| 1 | 工单原文的验收口径要求「另开一个**只改 `app/pubspec.yaml` 版本号**的 PR,backend 轨被触发」 | ① 与仓库 `AGENTS.md` 第六节「绝对不要做:升版本号」直接冲突,worker 照做即违规;② 「轨道被触发」是**合并后**事件,本单内不可自证 | 开单后先审口径:改成「1 文件 +2/−0 + `verify.sh contract` 绿 + YAML/paths 断言」,把「被触发」挪进「留给人验」段。**口径必须能在不违规的前提下被 worker 自证** |
| 2 | WSL 母体 `/root/src/chatapp` 停在 `b3dbdaa`,缺 #105 | 母体不会自动跟随 origin/master | worker 不受影响(`prepare` 自己从 GitHub fetch,worktree 基线是当时的 `d07d243`);但**人跑母体里的脚本会用到旧版**:合并后必须先 `git -C /root/src/chatapp pull --ff-only`,再跑 `superagent-prune.sh`——否则用的还是 #105 之前 `merge-base --is-ancestor` 的判定,squash 合并必然判 `merged=no`,清不掉 |
| 3 | #105 的 patch-id 判定在 squash 合并上**实测有效** | — | `pull` 之后 `superagent-prune.sh` 对该工单目录报 `merged=yes` 并清理成功,`refs/dsh-superagent/*` 也删净。这是真跑出来的结论,不是「理论上应该有效」 |
| 4 | 母体里 `git push origin --delete <已合并分支>` **不报错也不返回**,一直挂住 | 母体没配 credential helper,https remote 在等输入(不是失败) | 删已合并分支改用 REST:`DELETE /repos/{owner}/{repo}/git/refs/heads/<branch>`,token 用 MCP 那个(`~/.dsh/github-mcp-token.txt`)。**别在 WSL 母体里 push** |
| 5 | 取证时退出码全变成 `True`,中文输出乱码 | PowerShell 双引号里的 `$?` 被 PowerShell 提前展开(PowerShell 的转义是反引号,不是反斜杠);WSL→PowerShell 的 UTF-8 中文在控制台乱码 | 取证一律 `wsl -e bash -c '...'` **单引号**包裹,把 `echo xxx=$?` 放在 bash 内;别用 `\,` 转义 |
| 6 | 纯文档 PR 在 GitHub 上「一个 check 都没有」 | 六轨(`backend` / `web` / `app` / `imserver` / `contract` / `web-e2e`)的 `paths` 都不含 `docs/**` | 不是 CI 坏了:纯文档 PR 的「全绿」= 没有 check runs,真正的门是本地 `verify.sh contract`。别拿「CI 没触发」当跳过大验证的理由,也别把它当红 |

**worker 行为取证手法(可复用)**:会话记录在
`/root/.dsh/sessions/--<cwd 转义>--/worker-<ticket>/session.v4.jsonl.zstd`;`zstd -dc` 解开后按
`type == "tool/call"` 逐条看命令**顺序**,就能证明「先 verify 再推」——而不是只信 PR 正文里贴的输出。

**本轮指标**:人出手 2 次(补验收口径 / 授权合并),CI 往返 0 轮(首轮即绿),无需重写,
worker 无 `AGENTS.md` 违规(单栈 1 文件、未碰版本号、未自合、未越界)。

### 7. 首单验收后补进流程的三条硬规矩(2026-11-07)

用户在全流程实测后追加,已同步进 spec §3.3 与 `docs/ops/superagent.md` §4:

| # | 规矩 | 为什么要写成规矩 |
|---|---|---|
| 1 | **合并后立刻同步本机**:WSL 母体 `/root/src/chatapp` 与 Windows 仓库都 `pull --ff-only`,**先 pull 再 prune** | 母体不自动跟随 `origin/master`,而人要跑的 `superagent-prune.sh` 就住在母体里。首单实测:母体停在 `b3dbdaa`(缺 #105),此时跑 prune 会用 `merge-base --is-ancestor` 判定,squash 合并必然 `merged=no` → worktree 清不掉 |
| 2 | **纯文档 PR 直接合并**:只动 `docs/**` 的 PR 没有 check runs 是正常的,本地 `verify.sh contract` 绿 + 人看完 diff 即合 | 六轨 `paths` 都不含 `docs/**`。首单之后的记录 PR #107 就是 0 个 check run;若不写明,人和 agent 都会误判成「CI 没跑 = 不敢合」 |
| 3 | **先分析后开单**:需求分析在本机会话里做完再提 issue —— 改什么、属哪条栈、验收口径能否被 worker **在不违反 `AGENTS.md` 的前提下**自证 | 首单原口径同时踩两颗雷:要 worker 升版本号(违反 `AGENTS.md` 第六节)、要它自证「backend 轨被触发」(合并后事件)。凡是合并后才发生的事,一律写进「留给人验」 |

三条都已落到文档(不是只在本会话里说过):spec §3.3 的「三条硬规矩」、`docs/ops/superagent.md` §4 的
第 4–6 步,以及不入库的 `~/.dsh/AGENTS.md`(会话侧执行口径)。

### 8. 补记:本机同步必须自带代理(2026-11-07 收尾实测)

规矩 #1 第一次落地就又撞了一次,现象与「网络坏了」极像,实际是**人的 shell 没代理**:

- `wsl -e bash -c '...'` 起的非登录 shell **不带** `https_proxy` —— 代理只在
  `/root/start-superagent.sh` 里导出、由 worker 进程继承。所以 worker 的 fetch 一直是通的,
  人手动同步却不通。
- 表现:`git pull` / `superagent-prune.sh` 的第一步 `git fetch` 卡约 **130s** 后
  `Failed to connect to github.com port 443 after 132849 ms`,或 `gnutls_handshake() failed`。
- 处置(写进了 `docs/ops/superagent.md` §4 第 4 步):
  ```bash
  GW=$(ip route show default | awk '{print $3}' | head -1)
  export https_proxy="http://$GW:7897" http_proxy="http://$GW:7897"
  ```
- 与 issue #108 的关系:#108 是**脚本层**该不该因 fetch 失败而 fatal;这条是**人侧环境**该带什么变量。
  两者叠加才会出现「明明没有 worktree 可清,prune 却报错退出」。

### 9. 自动化阶梯四步实施记录(2026-11-07/08)

四步全部落地,**每一步都带可查证据**:

| 步 | 交付 | 合并 | 证据 |
|---|---|---|---|
| L1 收尾 | `scripts/superagent-closeout.sh` + 11 条自测 + 每小时定时任务 | #114 → `85a12ec` | 合并后真跑 `pulled=1 … same=yes`;代理不可用时退回本地 ref 判定且 exit 0 |
| L2 自动合并 | `.github/workflows/auto-merge.yml`(白名单只有 `docs/`)+ `AUTOMERGE` 开关 | #111 → `8853331` | 首个真实样本 PR #113 被 `github-actions[bot]` 合为 `5cd0c7a`;人开的 PR #112 被正确拦下 |
| L2.5 分支保护 | master ruleset(deletion / non_fast_forward / pull_request,0 approval) | 仓库外动作 | worker 账号直推 master:`push declined due to repository rule violations` |
| gh 硬拦 | `scripts/gh-guard/`(shim + installer + 13 条自测) | #115 → `678ef14` | 真实环境 `gh pr merge` 退 2 并记账;`pr create/view/checks` 照常 |
| L3 App UI 进 CI | `integration_test/smoke_test.dart` + `app-ui.yml`(emulator api 34) | #117 → `cb85145` | `app-ui` 绿 8m38;日志 `Boot completed in 24731 ms` / `All tests passed!`;主人 Windows 模拟器手测通过 |

**这一轮新增的坑(全部是「计划没想到、真跑才暴露」)**:

| # | 现象 | 根因 | 处置 |
|---|---|---|---|
| 1 | closeout 第一版不认 `--apply`,打印用法退 1 | 我默认 `MODE=apply`,忘了接受 `--apply`(和 `superagent-prune.sh` 的习惯不一致) | 加该选项 + 自测覆盖;教训:**同一套流程里的脚本,参数风格要一致** |
| 2 | closeout 上线后第一次跑报 `No such file or directory` | **鸡生蛋**:脚本本身也在母体里,母体没 pull 就没有它 | 写进 ops 手册:脚本刚上线/刚更新时先手动 `git pull` 一次 |
| 3 | `flutter test` 报「Integration tests and unit tests cannot be run in a single invocation」 | `android-emulator-runner` 的 `script:` 是**逐行 `sh -c`** 执行 —— 续行 `\`、跨行 `set -e`、`$?`、重定向全部失效 | `script` 收敛成单行;WSL 里用同一份 Flutter 复现确认不是用例问题 |
| 4 | Gradle `assembleDebug` 失败:`null cannot be cast to non-null type kotlin.String` | `app/android/app/build.gradle.kts` 在**配置阶段**无条件读 `key.properties`(gitignored,CI 里不存在) | CI 里 `keytool` 现造一次性 keystore + `key.properties`;根治(缺文件回落 debug 签名)需改 `app/android/**`,另开单 |
| 5 | **L3 合并后 `prune` 清不掉 worktree**:`merged=no`,但 PR 明明已 squash 合并 | `git cherry` 按 patch-id 判,**只对单提交分支成立**;L3 迭代了 4 个提交,squash 成一条后每个提交都算「未应用」 | `patch-id` 判不出来时**再问 GitHub**(`gh-agent pr list --state merged --head <branch>`),命中则记 `merged=yes-pr` 并清理;新增 `scripts/test_superagent_prune.sh` 8 条自测,其中三条专门锁这个回归 |
| 6 | `flutter pub get` 在 `app/macos/` 下生成 `Flutter/GeneratedPluginRegistrant.swift`,让 worktree 变脏 → prune 拒绝清理 | 本项目 `app/macos/.gitignore` 只忽略了 `**/Flutter/ephemeral/`,没忽略该文件(上游 Flutter 默认会忽略) | 本单由人删掉生成物后重跑 prune;仓库卫生(补 gitignore)另开单 |
| 7 | 工单收尾后再在这个 issue 下追加一条评论会话,**又长出一个新 worktree**(基线是当时的 master,分支名同旧工单) | 评论落在工单 thread 上会重新触发一次 prepare(`git fetch` + `worktree add`),即使 issue 已 closed、PR 已合并 | 收尾顺序改成:**先评论/关单,再 prune**;本轮由人事后补跑 `prune --apply` 清掉(`merged=yes` 直接识别)。这条直接对应 spec §3.9 的注意力预算 —— 工单结束后不要再往那个 thread 里说话 |

**结论**:自动化每加一层,都会把「原本靠人眼兜住的模糊判定」变成必须写死的确定性规则 —— 这一轮 6 个坑里有 5 个是**判定规则太窄**,而不是模型能力不够。
