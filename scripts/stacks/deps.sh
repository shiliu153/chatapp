#!/usr/bin/env bash
# 本地依赖容器(MySQL 13306 / Redis 16379)。CI 用 workflow 的 services 提供,不调本脚本。
#
# 单独一份的理由:起停容器是「本地才有」的装配动作,不属于门禁(gates.toml 只管判定),
# 也不该留在 verify.sh 里占行数(第 4 节要求 verify.sh ≤160 行)。
set -euo pipefail
. "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"

case ${1:-} in
  up)
    run "起依赖容器(MySQL 13306 / Redis 16379)" \
      docker compose -f "$COMPOSE" up -d --wait
    ;;
  down)
    # 注意:这里必须用 if,不能写 `[ … ] && { … }` —— 后者在 set -e 下,
    # 条件为假会让整条列表返回非零,直接把脚本打死。
    if [ "$KEEP_DEPS" = 1 ]; then
      echo "保留依赖容器(--keep-deps)"
      exit 0
    fi
    run "拆除依赖容器" docker compose -f "$COMPOSE" down -v
    ;;
  *)
    die "用法: $0 up|down"
    ;;
esac
