#!/usr/bin/env bash
# 后端栈:迁移 + 生成物校验 + 门禁(gates.toml 的 backend 组)。CI 与本地同一份。
#
# 装配(起容器 / 等 MySQL / 装依赖)不在本脚本里:本地由 verify.sh 的 deps 子命令起容器,
# CI 由 backend.yml 的 services + setup-python 提供。脚本只管「两边都该做的事」。
set -euo pipefail
. "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"

# 本地没有 venv 时给可执行的下一步,而不是让 Django 的 ImportError 冒充门禁红。
# CI 里没有 venv 是正常的(setup-python 直接装依赖),用 $CI 区分。
if [ "$PY_FALLBACK" = 1 ] && [ -z "${CI:-}" ]; then
  die "没有可用的 venv:$VENV。先跑 scripts/verify.sh bootstrap"
fi

cd "$ROOT/chatapp"
run "迁移" "$PY" manage.py migrate --noinput
# 生成物同改校验(与 web 的 schema.d.ts 同模式):重新生成一次;
# 「生成物 == HEAD」的比对是注册表里的 `backend-openapi-artifact` 门禁
# (scripts/lib/artifacts.py,比内容、忽略行尾 —— CI 里的 git diff 在 Windows 检出上等于永远红)。
run "重新生成 OpenAPI 契约" "$PY" manage.py spectacular --file ../docs/api/openapi.yml --validate
cd "$ROOT"
run_gates backend
