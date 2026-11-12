#!/usr/bin/env bash
# ``scripts/ci-scope.sh`` 的自测:纯离线(喂文件列表),不调 GitHub API。
#
# 进 CI 的 contract 轨:判定器一旦坏了,要么把重活全跳过(门禁漏),要么把每个 PR
# 都拖成 10 分钟 —— 两种都不能静默发生。
set -uo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
SCOPE="$ROOT/scripts/ci-scope.sh"
fail=0

check() { # check <描述> <期望> <栈> <文件...>
  desc=$1
  want=$2
  stack=$3
  shift 3
  tmp=$(mktemp)
  printf '%s\n' "$@" >"$tmp"
  got=$(FILES_FROM="$tmp" bash "$SCOPE" "$stack")
  rm -f "$tmp"
  if [ "$got" = "$want" ]; then
    printf 'ok   %s\n' "$desc"
  else
    printf 'FAIL %s(期望 %s,实际 %s)\n' "$desc" "$want" "$got"
    fail=1
  fi
}

# ── backend 栈
check "后端改动 → 跑"        "run=true"  backend "chatapp/im/views.py"
check "改 perf → 跑"         "run=true"  backend "perf/run.py"
check "改 API 文档 → 跑"     "run=true"  backend "docs/api/im.md"
check "改 pubspec → 跑"      "run=true"  backend "app/pubspec.yaml"
check "改 backend.yml → 跑"  "run=true"  backend ".github/workflows/backend.yml"
check "只改文档 → 跳过"      "run=false" backend "docs/ops/release.md"
check "只改网页 → 跳过"      "run=false" backend "web/src/App.vue"
check "只改 App → 跳过"      "run=false" backend "app/lib/main.dart"
check "只改 imserver → 跳过" "run=false" backend "imserver/src/main.cpp"

# ── web 栈
check "网页改动 → 跑"        "run=true"  web "web/src/App.vue"
check "改 API 文档 → 跑"     "run=true"  web "docs/api/im.md"
check "改 WS fixture → 跑"   "run=true"  web "imserver/tests/fixtures/ws/a.json"
check "改 web.yml → 跑"      "run=true"  web ".github/workflows/web.yml"
check "后端改动 → 跳过"      "run=false" web "chatapp/im/views.py"
check "只改文档 → 跳过"      "run=false" web "docs/ops/release.md"

# ── 判不出来 → fail-closed(跑)
tmp=$(mktemp)
: >"$tmp"
got=$(FILES_FROM="$tmp" bash "$SCOPE" backend)
rm -f "$tmp"
if [ "$got" = "run=true" ]; then
  printf 'ok   %s\n' "空文件列表 → 跑(fail-closed)"
else
  printf 'FAIL 空文件列表应 fail-closed,实际 %s\n' "$got"
  fail=1
fi

# ── 未知栈 → 退出码 2(防止拼错栈名后静默跳过)
if bash "$SCOPE" nosuch >/dev/null 2>&1; then
  printf 'FAIL 未知栈应退出码 2\n'
  fail=1
else
  printf 'ok   %s\n' "未知栈 → 退出码 2"
fi

[ "$fail" = 0 ] && echo "全部通过" || echo "有失败"
exit "$fail"
