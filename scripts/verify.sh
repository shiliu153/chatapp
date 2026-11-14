#!/usr/bin/env bash
# 本地验证入口。命令序列与环境变量**不再手抄 CI**:
#   - 门禁清单 = scripts/gates.toml,执行器 = scripts/run_gates.py(本地与 CI 同一个);
#   - 各栈的装配(起容器 / 装依赖 / 迁移 / 生成物校验)= scripts/stacks/*.sh(CI 也调它)。
# 口径见 docs/standards/sources-of-truth.md §2.3;新增一道门禁只需改 gates.toml 一处。
#
# 依赖:docker(WSL 里通过 Docker Desktop 的 WSL 集成)、后端用专用 venv(bootstrap 子命令建)、
# web 用 npm、app 用 Linux Flutter(默认 ~/flutter,可用 FLUTTER_BIN 覆盖)。
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
# shellcheck source=scripts/stacks/env.sh
. "$ROOT/scripts/stacks/env.sh"

usage() {
  cat <<'EOF'
用法: scripts/verify.sh [选项] <子命令> [子命令...]

子命令:
  backend    起依赖 → 迁移 → OpenAPI 生成物校验 → 后端门禁(gates.toml 的 backend 组)
  web        npm ci → 生成 API 类型 → 网页端门禁(web 组)
  imserver   imserver 单元 / 集成 / HTTP e2e(docker)
  app        flutter pub get → App 门禁(analyze + test)
  contract   跨栈契约门禁(gates.toml 的 contract 组)
  all        依次跑 backend web imserver app contract
  deps       只起依赖容器
  bootstrap  建后端 venv 并装 requirements.lock(首次或依赖变更后跑一次)

选项:
  --list       列出子命令
  --dry-run    只打印将执行的命令
  --keep-deps  结束后不拆依赖容器
EOF
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

  # 各栈的实现都在 scripts/stacks/*.sh 里 —— 与 CI 的四条 workflow 调的是同一份文件。
  local ran_backend=0
  for s in "${stacks[@]}"; do
    case $s in
      deps) bash "$ROOT/scripts/stacks/deps.sh" up ;;
      bootstrap) bash "$ROOT/scripts/stacks/bootstrap.sh" ;;
      backend)
        bash "$ROOT/scripts/stacks/deps.sh" up
        bash "$ROOT/scripts/stacks/backend.sh"
        ran_backend=1
        ;;
      web) bash "$ROOT/scripts/stacks/web.sh" ;;
      imserver) bash "$ROOT/scripts/stacks/imserver.sh" ;;
      app) bash "$ROOT/scripts/stacks/app.sh" ;;
      contract) run_gates contract ;;
      all)
        bash "$ROOT/scripts/stacks/deps.sh" up
        bash "$ROOT/scripts/stacks/backend.sh"
        bash "$ROOT/scripts/stacks/web.sh"
        bash "$ROOT/scripts/stacks/imserver.sh"
        bash "$ROOT/scripts/stacks/app.sh"
        run_gates contract
        ran_backend=1
        ;;
    esac
  done
  if [ "$ran_backend" = 1 ]; then
    bash "$ROOT/scripts/stacks/deps.sh" down
  fi
  printf '\n全部通过\n'
}

main "$@"
