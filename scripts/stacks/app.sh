#!/usr/bin/env bash
# App 栈:pub get + 门禁(gates.toml 的 app 组:analyze / test)。CI 与本地同一份。
set -euo pipefail
. "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"

if [ "$DRY_RUN" = 0 ]; then
  assert_linux_fs app
fi

cd "$ROOT/app"
run "拉依赖" flutter pub get
cd "$ROOT"
run_gates app
