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
#   这里只补本地缺省(13306 / 16379),**不覆盖 CI**。
# - 本文件**不改调用方的 shell 选项**(不 set -e):它既被 `set -euo pipefail` 的
#   verify.sh source,也被 `set -uo pipefail` 的自测 source。
# - 变量与函数是 verify.sh / stacks 脚本之间的内部约定,不是对外接口。

ROOT=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
COMPOSE="$ROOT/docker-compose.ci.yml"

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

# 与 backend.yml 的 env 对齐;端口用 compose 里避让后的 13306 / 16379。
export SECRET_KEY=${SECRET_KEY:-ci-only-not-a-real-secret}
export DEBUG=${DEBUG:-1}
export DB_NAME=${DB_NAME:-chatapp_dev}
export DB_USER=${DB_USER:-chatapp}
export DB_PASSWORD=${DB_PASSWORD:-chatapp_ci}
export DB_HOST=${DB_HOST:-127.0.0.1}
export DB_PORT=${DB_PORT:-13306}
export DB_SSL_DISABLED=${DB_SSL_DISABLED:-0}
export BROKER_URL=${BROKER_URL:-redis://127.0.0.1:16379/1}
export REDIS_URL=${REDIS_URL:-redis://127.0.0.1:16379/0}
# 注意:TESTING 模式下 config/settings.py 不读 REDIS_URL,而是读 TEST_REDIS_HOST/PORT
# (见 settings.py「测试隔离」一节),用独立 DB 15/14 以免碰开发数据。这里必须一起指过来,
# 否则测试会去连 127.0.0.1:6379(Windows 上那个开发用 redis),在 WSL 里必然 Connection refused。
export TEST_REDIS_HOST=${TEST_REDIS_HOST:-127.0.0.1}
export TEST_REDIS_PORT=${TEST_REDIS_PORT:-16379}
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

die() { printf '错误: %s\n' "$*" >&2; exit 2; }

run() { # run <说明> <命令...>
  local label=$1; shift
  printf '\n=== %s ===\n' "$label"
  if [ "$DRY_RUN" = 1 ]; then printf '+ %s\n' "$*"; return 0; fi
  "$@"
}

# 校验「生成物 == HEAD 里的那一版」。
#
# 为什么不用 `git diff --exit-code`:本仓库在 Windows 上检出是 CRLF,而 WSL 里的 git
# 按 LF 理解索引,`git diff` 会把上千个文件都算成改动(实测 1094 个),这条判定在
# WSL 里等于永远红。改成「比内容、忽略行尾」:把两边的 \r 都去掉再比。
# (抽成 scripts/lib/artifacts.py 归治理第 5 节,见 sources-of-truth §4 C9。)
check_artifact() { # check_artifact <仓库相对路径>
  local f=$1
  if [ "$DRY_RUN" = 1 ]; then
    printf '\n=== 校验生成物与 HEAD 一致 ===\n+ %s\n' "$f"
    return 0
  fi
  if ! git -C "$ROOT" cat-file -e "HEAD:$f" 2>/dev/null; then
    die "$f 不在 HEAD 里:新增生成物请先提交,否则 CI 会对不上"
  fi
  if ! diff -q <(git -C "$ROOT" show "HEAD:$f" | tr -d '\r') <(tr -d '\r' < "$ROOT/$f") >/dev/null; then
    echo "--- $f 与 HEAD 的差异(前 40 行) ---" >&2
    diff -u <(git -C "$ROOT" show "HEAD:$f" | tr -d '\r') <(tr -d '\r' < "$ROOT/$f") 2>&1 | head -40 >&2 || true
    die "$f 与代码不一致:重新生成并提交"
  fi
  echo "生成物一致: $f"
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
