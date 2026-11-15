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
# 依赖容器的「槽位」派生(scripts/stacks/env.sh 的并发防撞车规则)。钉四个方向:
# 母体检出沿用文档口径、非母体目录派生到槽位段、同一目录结果稳定、外部给的值优先。
# 做法是把 env.sh 复制进临时目录再 source —— 派生只看仓库根路径,所以这样就能离线
# 问出「这个目录会起哪套栈」,不碰 docker。
probe_env() { # probe_env <目录> [环境赋值...] → 「项目名 MySQL端口 Redis端口 DB_PORT」
  local dir=$1; shift
  mkdir -p "$dir/scripts/stacks"
  cp "$ROOT/scripts/stacks/env.sh" "$dir/scripts/stacks/env.sh"
  # shellcheck disable=SC2086  # "$@" 是若干 NAME=VALUE,必须逐词传给 env
  env -u COMPOSE_PROJECT_NAME -u MYSQL_PORT -u REDIS_PORT \
      -u DB_PORT -u BROKER_URL -u REDIS_URL -u TEST_REDIS_HOST -u TEST_REDIS_PORT \
      "$@" bash -c '. "$1/scripts/stacks/env.sh"; printf "%s %s %s %s\n" \
        "$COMPOSE_PROJECT_NAME" "$MYSQL_PORT" "$REDIS_PORT" "$DB_PORT"' _ "$dir"
}
probe_check() { # probe_check <描述> <期望> <实际>
  if [ "$2" = "$3" ]; then printf 'ok   %s(%s)\n' "$1" "$3"
  else printf 'FAIL %s(期望 %s,实际 %s)\n' "$1" "$2" "$3"; fail=1; fi
}
tmp_a=$(mktemp -d); tmp_b=$(mktemp -d)
legacy=$(probe_env "$tmp_a" CHATAPP_MAIN_CHECKOUT="$tmp_a")   # tmp_a 扮母体检出
derived=$(probe_env "$tmp_b" CHATAPP_MAIN_CHECKOUT="$tmp_a")  # tmp_b 是「别的目录」
probe_check "母体检出沿用文档口径" "chatapp-ci 13306 16379 13306" "$legacy"
again=$(probe_env "$tmp_b" CHATAPP_MAIN_CHECKOUT="$tmp_a")
probe_check "同一目录派生结果稳定" "$derived" "$again"
read -r d_proj d_mysql d_redis d_dbport <<< "$derived"
case $d_proj in
  chatapp-ci-s[0-9]*) printf 'ok   非母体目录派生项目名 %s\n' "$d_proj" ;;
  *) printf 'FAIL 非母体目录的项目名应是 chatapp-ci-s<槽>,实际 %s\n' "$d_proj"; fail=1 ;;
esac
case $d_mysql in
  134[0-9][0-9]) printf 'ok   非母体目录 MySQL 落在 13400-13499(%s)\n' "$d_mysql" ;;
  *) printf 'FAIL 非母体目录 MySQL 应在 13400-13499,实际 %s\n' "$d_mysql"; fail=1 ;;
esac
case $d_redis in
  135[0-9][0-9]) printf 'ok   非母体目录 Redis 落在 13500-13599(%s)\n' "$d_redis" ;;
  *) printf 'FAIL 非母体目录 Redis 应在 13500-13599,实际 %s\n' "$d_redis"; fail=1 ;;
esac
probe_check "DB_PORT 跟着 MySQL 端口走" "$d_mysql" "$d_dbport"
probe_check "CHATAPP_CI_SLOT 显式指定槽位" "chatapp-ci-s7 13407 13507 13407" \
  "$(probe_env "$tmp_a" CHATAPP_MAIN_CHECKOUT="$tmp_a" CHATAPP_CI_SLOT=7)"
probe_env "$tmp_a" CHATAPP_MAIN_CHECKOUT="$tmp_a" CHATAPP_CI_SLOT=abc >/dev/null 2>&1
if [ $? = 2 ]; then echo "ok   非法 CHATAPP_CI_SLOT 退出 2"
else echo "FAIL 非法 CHATAPP_CI_SLOT 应退出 2"; fail=1; fi
probe_check "外部给的项目名与端口优先" "handpicked 23306 26379 23306" \
  "$(probe_env "$tmp_b" MYSQL_PORT=23306 REDIS_PORT=26379 COMPOSE_PROJECT_NAME=handpicked)"
tmp_c=$(mktemp -d); other=""; i=0
# 路径哈希取模 100,理论上两个目录可能撞槽位;撞了就换目录重试(最多 5 次)。
while [ "$i" -lt 5 ]; do
  other=$(probe_env "$tmp_c" CHATAPP_MAIN_CHECKOUT="$tmp_a")
  [ "$other" != "$derived" ] && break
  rm -rf "$tmp_c"; tmp_c=$(mktemp -d); i=$((i + 1))
done
if [ "$other" != "$derived" ]; then
  printf 'ok   两个不同目录派生出不同的栈(%s / %s)\n' "${derived%% *}" "${other%% *}"
else printf 'FAIL 两个不同目录派生出了同一套栈(%s)\n' "$derived"; fail=1; fi
# 拆容器必须点名本项目,否则「只拆自己」不成立。
ddry=$(bash "$V" deps --dry-run 2>/dev/null)
case $ddry in
  *"-p $COMPOSE_PROJECT_NAME"*) printf 'ok   deps --dry-run 点名项目 %s\n' "$COMPOSE_PROJECT_NAME" ;;
  *) printf 'FAIL deps --dry-run 没有 -p %s\n' "$COMPOSE_PROJECT_NAME"; fail=1 ;;
esac
rm -rf "$tmp_a" "$tmp_b" "$tmp_c"
[ "$fail" = 0 ] && echo "全部通过" || echo "有失败"
exit "$fail"
