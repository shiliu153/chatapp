#!/usr/bin/env bash
# 本地与 CI 共用的环境层:`scripts/verify.sh` 与 `scripts/stacks/*.sh` 都 source 这一份。
#
# 为什么单独一份
# --------------
# 2026-11-14 之前,`verify.sh` 手抄 CI 的 env 与命令序列,于是两边慢慢分叉
# (本地 15 条 / CI 19 条,见 docs/standards/sources-of-truth.md §4 C5)。
# 现在:环境只写在这里,门禁命令只写在 `scripts/gates.toml`,两边调同一个执行器。
#
# 约定
# ----
# - 一律用 `${VAR:-默认值}`:CI 的 workflow 已经注入自己的值(MySQL 3306 / Redis 6379),
#   这里只补本地缺省(母体检出 13306 / 16379,其余目录见下面的「槽位」一段),**不覆盖 CI**。
# - 本文件**不改调用方的 shell 选项**(不 set -e):它既被 `set -euo pipefail` 的
#   verify.sh source,也被 `set -uo pipefail` 的自测 source。
# - 变量与函数是 verify.sh / stacks 脚本之间的内部约定,不是对外接口。

ROOT=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
COMPOSE="$ROOT/docker-compose.ci.yml"

die() { printf '错误: %s\n' "$*" >&2; exit 2; }

# 依赖容器的「槽位」—— 并发跑 backend 时的防撞车规则,**派生只此一处**
# --------------------------------------------------------------------
# 症状(2026-11-14,PR #333/#334/#335):多个工单同时跑 `scripts/verify.sh backend`,
# 后结束的那个 `deps down -v` 会把别的工单正在用的库拆掉,受害者成批 setUpClass 报
# pymysql 1053 / 1049 / 1044。根因是 compose 的项目名与端口都写死:同一份
# `docker-compose.ci.yml`、项目名 `chatapp-ci`、端口 13306 / 16379。
#
# 规则(优先级从高到低,先命中先算数):
#   1. 外部显式给了 `MYSQL_PORT` / `REDIS_PORT` / `COMPOSE_PROJECT_NAME` → 一律照用
#      (CI 的 workflow 就是这么注入它自己那套 service 的);
#   2. 显式给了 `CHATAPP_CI_SLOT`(0-99)→ 用该槽位(同一个目录要临时错开时用它);
#   3. 仓库根就是母体检出(`CHATAPP_MAIN_CHECKOUT`,默认 `$HOME/src/chatapp`)→ 沿用
#      文档口径:端口 13306 / 16379、项目名 chatapp-ci(README / runbook / 踩坑手册都按这套写);
#   4. 其余任何目录(worker 的工单 worktree、临时 worktree、任意克隆)→ 按路径哈希取槽
#      0-99:MySQL 13400+槽、Redis 13500+槽、项目名 `chatapp-ci-s<槽>`。
# 同一个目录每次派生出同一个结果,不同目录几乎必然不同 —— 这就是「并发互不拆台」的依据。
CHATAPP_MAIN_CHECKOUT=${CHATAPP_MAIN_CHECKOUT:-$HOME/src/chatapp}

# 取槽位:显式 CHATAPP_CI_SLOT 优先,否则按仓库根路径哈希。
# 哈希用 cksum 而不用 md5sum / sha1sum:cksum 是 POSIX 必备,精简镜像里另外两个不一定有。
ci_slot() {
  if [ -n "${CHATAPP_CI_SLOT:-}" ]; then
    case $CHATAPP_CI_SLOT in
      ''|*[!0-9]*) die "CHATAPP_CI_SLOT 必须是 0-99 的整数,当前是「$CHATAPP_CI_SLOT」" ;;
    esac
    [ "$((10#$CHATAPP_CI_SLOT))" -le 99 ] \
      || die "CHATAPP_CI_SLOT 必须是 0-99 的整数,当前是「$CHATAPP_CI_SLOT」"
    printf '%s' "$((10#$CHATAPP_CI_SLOT))"
    return 0
  fi
  local sum
  sum=$(printf '%s' "$ROOT" | cksum)
  printf '%s' "$(( ${sum%% *} % 100 ))"
}

# 母体检出保持文档口径;其余目录一律派生(显式 CHATAPP_CI_SLOT 在母体里也生效)。
if [ -n "${CHATAPP_CI_SLOT:-}" ] || [ "$ROOT" != "$CHATAPP_MAIN_CHECKOUT" ]; then
  slot=$(ci_slot)
  COMPOSE_PROJECT_NAME=${COMPOSE_PROJECT_NAME:-chatapp-ci-s$slot}
  MYSQL_PORT=${MYSQL_PORT:-$((13400 + slot))}
  REDIS_PORT=${REDIS_PORT:-$((13500 + slot))}
else
  COMPOSE_PROJECT_NAME=${COMPOSE_PROJECT_NAME:-chatapp-ci}
  MYSQL_PORT=${MYSQL_PORT:-13306}
  REDIS_PORT=${REDIS_PORT:-16379}
fi
export COMPOSE_PROJECT_NAME MYSQL_PORT REDIS_PORT

# 解释器:本地用专用 venv,CI 没有 venv(直接用 setup-python 的 python)。
# 显式 CHATAPP_PY 最优先;run_gates.py 也读它来决定 python 门禁用哪个解释器。
VENV=${CHATAPP_VENV:-$HOME/venvs/chatapp}
if [ -n "${CHATAPP_PY:-}" ]; then
  PY=$CHATAPP_PY
  PY_FALLBACK=0
elif [ -x "$VENV/bin/python" ]; then
  PY=$VENV/bin/python
  PY_FALLBACK=0
else
  PY=python3
  PY_FALLBACK=1
fi
export CHATAPP_PY="$PY"

# Node 版本必须与 CI 对齐(web.yml / web-e2e.yml 都用 22)。实测 Node 24 会让
# profile-store 的上传照片用例报 webidl.is.File 断言失败 —— 那是环境差异不是代码问题,
# 所以这里直接钉住并优先用 $HOME/node22(安装方式见 docs/ops/superagent.md)。
NODE_DIR=${CHATAPP_NODE_DIR:-$HOME/node22}
if [ -x "$NODE_DIR/bin/node" ]; then
  PATH="$NODE_DIR/bin:$PATH"
fi
REQUIRED_NODE_MAJOR=${CHATAPP_NODE_MAJOR:-22}

# Flutter:CI 由 subosito/flutter-action 放进 PATH;本地默认 ~/flutter,可用 FLUTTER_BIN 覆盖。
if [ -n "${FLUTTER_BIN:-}" ]; then
  PATH="$(dirname -- "$FLUTTER_BIN"):$PATH"
elif [ -x "$HOME/flutter/bin/flutter" ]; then
  PATH="$HOME/flutter/bin:$PATH"
fi
export PATH

# 与 backend.yml 的 env 对齐;端口取上面派生的槽位(母体检出 = 文档口径 13306 / 16379)。
export SECRET_KEY=${SECRET_KEY:-ci-only-not-a-real-secret}
export DEBUG=${DEBUG:-1}
export DB_NAME=${DB_NAME:-chatapp_dev}
export DB_USER=${DB_USER:-chatapp}
export DB_PASSWORD=${DB_PASSWORD:-chatapp_ci}
export DB_HOST=${DB_HOST:-127.0.0.1}
export DB_PORT=${DB_PORT:-$MYSQL_PORT}
export DB_SSL_DISABLED=${DB_SSL_DISABLED:-0}
export BROKER_URL=${BROKER_URL:-redis://127.0.0.1:$REDIS_PORT/1}
export REDIS_URL=${REDIS_URL:-redis://127.0.0.1:$REDIS_PORT/0}
# 注意:TESTING 模式下 config/settings.py 不读 REDIS_URL,而是读 TEST_REDIS_HOST/PORT
# (见 settings.py「测试隔离」一节),用独立 DB 15/14 以免碰开发数据。
#
# **必须从 REDIS_URL 解析,不能写死 16379**:CI 的 workflow 只注入 REDIS_URL(Redis 在
# 6379),从没注入 TEST_REDIS_*;写死会让 CI 的测试去连 16379 → Connection refused,
# 门禁红得莫名其妙(2026-11-14 第 4 节在 CI 上实测踩到,本地 16379 恰好是对的所以看不出来)。
test_redis=${REDIS_URL#*://}
test_redis=${test_redis%%/*}
test_redis=${test_redis##*@}
export TEST_REDIS_HOST=${TEST_REDIS_HOST:-${test_redis%%:*}}
export TEST_REDIS_PORT=${TEST_REDIS_PORT:-${test_redis##*:}}
export IM_SELF_URL=${IM_SELF_URL:-http://127.0.0.1:9101}
export IM_SELF_WS_URL=${IM_SELF_WS_URL:-ws://127.0.0.1:9100/im/ws}
export IM_SELF_HTTP_URL=${IM_SELF_HTTP_URL:-http://127.0.0.1:9101/im/api}
export IM_SELF_SECRET=${IM_SELF_SECRET:-ci-fake-secret-32-bytes-minimum}
export IM_SELF_INTERNAL_SECRET=${IM_SELF_INTERNAL_SECRET:-ci-fake-internal-32-bytes-minimum}
export SMS_DEV_MODE=${SMS_DEV_MODE:-1}
export AUTO_APPROVE=${AUTO_APPROVE:-1}

# 两个开关由 verify.sh 的参数解析设置,再 export 给子脚本(它们各自是独立进程)。
DRY_RUN=${DRY_RUN:-0}
KEEP_DEPS=${KEEP_DEPS:-0}
export DRY_RUN KEEP_DEPS

run() { # run <说明> <命令...>
  local label=$1; shift
  printf '\n=== %s ===\n' "$label"
  if [ "$DRY_RUN" = 1 ]; then printf '+ %s\n' "$*"; return 0; fi
  "$@"
}

# web / app 两条栈拒绝在 /mnt/* 上跑:那是 WSL 的 9p 挂载,读 node_modules 与 flutter
# 缓存极慢,实测 vitest 起 fork worker 会直接超时(报 "[vitest-pool] Failed to start
# forks worker … Timeout waiting for worker to respond"),看上去像用例红了其实是环境。
# 正确做法是在 Linux 文件系统上的克隆里跑(worker 的 worktree 本来就在 /root 下)。
assert_linux_fs() { # assert_linux_fs <栈名>
  case $ROOT in
    /mnt/*)
      die "$1 不能在 /mnt/ 下跑(9p 太慢,vitest/flutter 会超时)。请在 WSL 的 Linux 文件系统上的克隆里执行,例如 /root/src/chatapp 的 worktree"
      ;;
  esac
}

# 调门禁执行器。门禁清单的唯一事实来源是 scripts/gates.toml —— 这里**不写任何命令**。
# --dry-run 时把「逐条打印」交给执行器,本地 `verify.sh contract --dry-run` 与 CI 的
# 执行日志因此是同一份清单(scripts/test_verify.sh 会数条数)。
run_gates() { # run_gates <scope>
  local args=(--scope "$1")
  if [ "$DRY_RUN" = 1 ]; then
    args+=(--dry-run)
  fi
  "$PY" "$ROOT/scripts/run_gates.py" "${args[@]}"
}
