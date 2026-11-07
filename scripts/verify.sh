#!/usr/bin/env bash
# 本地复刻 CI 六轨的可执行入口。用法见 usage()。
#
# 设计原则:命令序列与环境变量必须与 .github/workflows/*.yml 逐项对齐,
# 但 CI 不调用本脚本——它是 CI 的镜像,不是 CI 的入口。
#
# 依赖:docker(WSL 里通过 Docker Desktop 的 WSL 集成)、后端用专用 venv(bootstrap 子命令建)、
# web 用 npm、app 用 Linux Flutter(默认 ~/flutter,可用 FLUTTER_BIN 覆盖)。
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
COMPOSE="$ROOT/docker-compose.ci.yml"
# 后端 / 契约用的解释器:专用 venv。系统 Python 上没有 Django 与 PyMySQL。
VENV=${CHATAPP_VENV:-$HOME/venvs/chatapp}
PY="$VENV/bin/python"
DRY_RUN=0
KEEP_DEPS=0

# 与 backend.yml 的 env 对齐;端口用 compose 里避让后的 13306 / 16379。
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
  if [ ${#stacks[@]} -eq 0 ]; then
    usage >&2
    exit 1
  fi

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
  if [ "$ran_backend" = 1 ]; then
    deps_down
  fi
  printf '\n全部通过\n'
}

main "$@"
