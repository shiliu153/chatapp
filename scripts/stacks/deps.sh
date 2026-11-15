#!/usr/bin/env bash
# 本地依赖容器(MySQL / Redis)。CI 用 workflow 的 services 提供,不调本脚本。
#
# 单独一份的理由:起停容器是「本地才有」的装配动作,不属于门禁(gates.toml 只管判定),
# 也不该留在 verify.sh 里占行数(第 4 节要求 verify.sh ≤160 行)。
#
# **项目名与端口来自 env.sh 的派生**:每个检出目录一套自己的栈(母体检出仍是
# chatapp-ci / 13306 / 16379),所以并发的两个工单互不拆台。规则与优先级见 env.sh 顶部。
set -euo pipefail
. "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
# shellcheck source=scripts/stacks/mount-perms.sh
. "$(dirname -- "${BASH_SOURCE[0]}")/mount-perms.sh"

# 本项目(**不是**「所有 chatapp-ci 容器」)是否已经在跑:按 compose 的 project + service
# 标签判,避免把别的目录那套栈当成自己的复用(复用错项目等于连到别人的库)。
compose_running() {
  local svc
  for svc in mysql redis; do
    docker ps -q \
      --filter "label=com.docker.compose.project=$COMPOSE_PROJECT_NAME" \
      --filter "label=com.docker.compose.service=$svc" 2>/dev/null | grep -q . || return 1
  done
  return 0
}

# 被 compose 以 :ro 挂进容器、由非 root 用户读取的文件,起容器前补回 0644:
# worker worktree 的 umask 077 会让它们检出成 0600,MySQL 读 init 脚本直接 Permission denied
# → 退出 1(2026-11-14 实测偶发)。清单与函数在 scripts/stacks/mount-perms.sh 一处,
# 新增挂载文件登记到那里的 MOUNT_READ_FILES(不用 glob);口径见 docs/pitfalls/testing.md
# 「在 WSL / Linux 本地跑验证」第 5 条。

case ${1:-} in
  up)
    [ "$DRY_RUN" = 1 ] || ensure_mount_readable "$ROOT"
    if [ "$DRY_RUN" = 0 ] && compose_running; then
      echo "复用已在跑的依赖容器(项目 $COMPOSE_PROJECT_NAME,MySQL $MYSQL_PORT / Redis $REDIS_PORT)"
    else
      run "起依赖容器($COMPOSE_PROJECT_NAME:MySQL $MYSQL_PORT / Redis $REDIS_PORT)" \
        docker compose -p "$COMPOSE_PROJECT_NAME" -f "$COMPOSE" up -d --wait
    fi
    ;;
  down)
    # 注意:这里必须用 if,不能写 `[ … ] && { … }` —— 后者在 set -e 下,
    # 条件为假会让整条列表返回非零,直接把脚本打死。
    if [ "$KEEP_DEPS" = 1 ]; then
      echo "保留依赖容器(--keep-deps)"
      exit 0
    fi
    # 只拆本项目:`-p` 显式指定,拆谁由派生结果决定,不看环境里残留的 COMPOSE_PROJECT_NAME。
    run "拆除依赖容器($COMPOSE_PROJECT_NAME)" \
      docker compose -p "$COMPOSE_PROJECT_NAME" -f "$COMPOSE" down -v
    ;;
  *)
    die "用法: $0 up|down"
    ;;
esac
