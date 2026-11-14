#!/usr/bin/env bash
# 网页端栈:npm ci + 生成物校验 + 门禁(gates.toml 的 web 组)。CI 与本地同一份。
set -euo pipefail
. "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"

if [ "$DRY_RUN" = 0 ]; then
  assert_linux_fs web
  major=$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)
  if [ "$major" != "$REQUIRED_NODE_MAJOR" ]; then
    die "web 需要 Node $REQUIRED_NODE_MAJOR(与 CI 一致),当前是 $major。装好 $NODE_DIR 或设 CHATAPP_NODE_MAJOR 覆盖"
  fi
fi

cd "$ROOT/web"
run "安装依赖" npm ci
# 生成物同改校验:openapi-typescript 生成的 schema.d.ts 必须与后端契约一致;
# 「生成物 == HEAD」的比对是注册表里的 `web-schema-artifact` 门禁(scripts/lib/artifacts.py)。
run "重新生成 API 类型" npm run gen:api
cd "$ROOT"
run_gates web
