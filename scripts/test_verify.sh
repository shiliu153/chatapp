#!/usr/bin/env bash
# verify.sh 的自测:只验「入口契约」(用法 / 退出码 / 子命令清单 / --dry-run),
# 不真跑测试套件——真跑由 verify.sh 自己负责,这里防的是「脚本自己错了却报绿」。
set -uo pipefail
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
V="$ROOT/scripts/verify.sh"
fail=0
check() { # check <描述> <期望退出码> <命令...>
  local desc=$1 want=$2; shift 2
  "$@" >/dev/null 2>&1; local got=$?
  if [ "$got" = "$want" ]; then printf 'ok   %s\n' "$desc"
  else printf 'FAIL %s (期望退出 %s,实际 %s)\n' "$desc" "$want" "$got"; fail=1; fi
}
check "无参数打印用法并退出 1" 1 bash "$V"
check "未知子命令退出 2" 2 bash "$V" nosuchstack
check "--list 正常退出" 0 bash "$V" --list
for s in backend web imserver app contract; do
  out=$(bash "$V" --list 2>/dev/null)
  case $out in *"$s"*) printf 'ok   --list 含 %s\n' "$s";; *) printf 'FAIL --list 缺 %s\n' "$s"; fail=1;; esac
done
# --dry-run 的可用性用 deps 验:它是骨架里就已实现的子命令,
# backend / web / app 的具体断言由各自 Task 追加。
check "deps --dry-run 退出 0" 0 bash "$V" deps --dry-run
dry=$(bash "$V" deps --dry-run 2>/dev/null)
case $dry in *"docker compose"*) echo "ok   --dry-run 打印 docker compose";; *) echo "FAIL --dry-run 未打印 docker compose"; fail=1;; esac
[ "$fail" = 0 ] && echo "全部通过" || echo "有失败"
exit "$fail"
