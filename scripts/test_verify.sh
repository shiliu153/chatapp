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
bdry=$(bash "$V" backend --dry-run 2>/dev/null)
for needle in "manage.py migrate" "manage.py test" "manage.py spectacular" "perf.test_run"; do
  case $bdry in *"$needle"*) printf 'ok   backend dry-run 含 %s\n' "$needle";;
    *) printf 'FAIL backend dry-run 缺 %s\n' "$needle"; fail=1;; esac
done
wdry=$(bash "$V" web --dry-run 2>/dev/null)
case $wdry in *"npm run type-check"*) printf 'ok   web dry-run 含 type-check\n';;
  *) printf 'FAIL web dry-run 缺 type-check\n'; fail=1;; esac
cdry=$(bash "$V" contract --dry-run 2>/dev/null)
case $cdry in *"sync_version.py --check"*) printf 'ok   contract dry-run 含 sync_version\n';;
  *) printf 'FAIL contract dry-run 缺 sync_version\n'; fail=1;; esac
# 第 4 节(门禁注册表):contract 分支已收成一行调用执行器,所以 --dry-run 必须由执行器
# **逐条打印**;再钉一条「打出的条数 == 注册表里 contract 的条数」—— 少了这条,
# 执行器悄悄漏跑一道门禁也能绿(那正是 C5 的复发形态)。
. "$ROOT/scripts/stacks/env.sh"
dry_n=$(bash "$V" contract --dry-run 2>/dev/null | grep -c '^+ ')
list_n=$("$PY" "$ROOT/scripts/run_gates.py" --list --json |
  "$PY" -c 'import json, sys; print(sum(1 for gate in json.load(sys.stdin) if gate["scope"] == "contract"))')
if [ "$dry_n" = "$list_n" ]; then
  printf 'ok   contract dry-run 条数 == 注册表 contract 条数(%s)\n' "$dry_n"
else
  printf 'FAIL contract dry-run 条数 %s != 注册表 %s\n' "$dry_n" "$list_n"
  fail=1
fi
[ "$fail" = 0 ] && echo "全部通过" || echo "有失败"
exit "$fail"
