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
  # 三个 CHATAPP_CI_* 是 env.sh 的**离线探针**(撞槽判定的注入口)。这里默认填空 =
  # 「假装没有端口被占、没有自己的栈、端口都连不上」,于是派生结果只由路径决定 ——
  # 自测不会被宿主上真在跑的容器/服务带跑;要造「撞槽」场景再按需覆盖(见下面那组用例)。
  env -u COMPOSE_PROJECT_NAME -u MYSQL_PORT -u REDIS_PORT \
      -u DB_PORT -u BROKER_URL -u REDIS_URL -u TEST_REDIS_HOST -u TEST_REDIS_PORT \
      -u CHATAPP_CI_LISTENING_PORTS -u CHATAPP_CI_OWNED_SLOTS -u CHATAPP_CI_PORT_ANSWERS \
      CHATAPP_CI_LISTENING_PORTS= CHATAPP_CI_OWNED_SLOTS= CHATAPP_CI_PORT_ANSWERS= \
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
# 撞槽兜底(scripts/stacks/env.sh 规则 5):槽位是「路径哈希 % 100」,两个目录理论上会撞到
# 同一槽;撞了必须自己顺延,不能等 docker compose 拿端口冲突报错。这组用例全程离线 ——
# CHATAPP_CI_LISTENING_PORTS 假装「这些端口有人听」,CHATAPP_CI_OWNED_SLOTS 假装「这些槽
# 是自己的栈」,所以不必真起容器。
bumped=$(probe_env "$tmp_b" CHATAPP_MAIN_CHECKOUT="$tmp_a" CHATAPP_CI_LISTENING_PORTS="$d_mysql")
read -r b_proj b_mysql b_redis b_dbport <<< "$bumped"
if [ "$b_proj" != "$d_proj" ] && [ "$b_mysql" != "$d_mysql" ]; then
  printf 'ok   撞槽(MySQL %s 在听)时顺延到别的槽(%s → %s)\n' "$d_mysql" "$d_proj" "$b_proj"
else printf 'FAIL 槽 %s 的 MySQL 端口被占,却仍用原槽\n' "$d_proj"; fail=1; fi
probe_check "顺延后 DB_PORT 跟着新槽" "$b_mysql" "$b_dbport"
probe_check "顺延后 Redis 端口仍是同一个槽" "$((13500 + 10#${b_proj#chatapp-ci-s}))" "$b_redis"
probe_check "本项目自己的槽(按 working_dir 认)继续复用" "$derived" \
  "$(probe_env "$tmp_b" CHATAPP_MAIN_CHECKOUT="$tmp_a" CHATAPP_CI_LISTENING_PORTS="$d_mysql" \
    CHATAPP_CI_OWNED_SLOTS="${d_proj#chatapp-ci-s}")"
probe_env "$tmp_b" CHATAPP_MAIN_CHECKOUT="$tmp_a" CHATAPP_CI_SLOT="${d_proj#chatapp-ci-s}" \
  CHATAPP_CI_LISTENING_PORTS="$d_mysql" >/dev/null 2>&1
if [ $? = 2 ]; then echo "ok   显式 CHATAPP_CI_SLOT 撞槽时退出 2(给建议,不静默改写)"
else echo "FAIL 显式 CHATAPP_CI_SLOT 撞槽时应退出 2"; fail=1; fi
probe_check "外部显式给端口时一律不探测(CI 口径)" "handpicked 23306 26379 23306" \
  "$(probe_env "$tmp_b" MYSQL_PORT=23306 REDIS_PORT=26379 COMPOSE_PROJECT_NAME=handpicked \
    CHATAPP_CI_LISTENING_PORTS="13463 13464 13563 13564")"
if [ "$(choose_slot 99 "13499" "")" = 0 ]; then echo "ok   槽位顺延在 99 之后回到 0"
else echo "FAIL 槽位顺延在 99 之后没有回到 0"; fail=1; fi
if choose_slot 0 "$(seq -s ' ' 13400 13499)" "" >/dev/null 2>&1; then
  echo "FAIL 0-99 全被占满时 choose_slot 不该成功"; fail=1
else echo "ok   0-99 全占满时 choose_slot 返回失败"; fi
# 野生服务(docker 端口列表与 ss 都看不见,只有真连一下才发现 —— 典型是宿主上直接装的
# MySQL/Redis):不猜着用、也不静默顺延,直接退出 2 并给出一个肯定空闲的槽位建议。
wild_err=$(probe_env "$tmp_b" CHATAPP_MAIN_CHECKOUT="$tmp_a" CHATAPP_CI_PORT_ANSWERS="$d_mysql" 2>&1)
if [ $? = 2 ]; then echo "ok   端口有人应答但无人认领时退出 2"
else echo "FAIL 端口有人应答但无人认领时应退出 2(不该猜着用)"; fail=1; fi
case $wild_err in
  *"CHATAPP_CI_SLOT="*) echo "ok   野生服务场景给出具体槽位建议" ;;
  *) printf 'FAIL 野生服务场景没有给出具体槽位建议(实际输出:%s)\n' "$wild_err"; fail=1 ;;
esac
# 自己的栈在跑 + 端口有应答 = 正常复用,双保险不该把它拦死。
probe_check "自己的栈 + 端口应答时仍复用" "$derived" \
  "$(probe_env "$tmp_b" CHATAPP_MAIN_CHECKOUT="$tmp_a" CHATAPP_CI_PORT_ANSWERS="$d_mysql" \
    CHATAPP_CI_OWNED_SLOTS="${d_proj#chatapp-ci-s}")"
# 孤儿栈回收(env.sh「孤儿栈回收」一节 + deps.sh down):撞槽顺延出来的栈在占用方消失后会算回
# 原槽,down 必须把两个项目都点名。两个纯函数与状态文件都能离线验,不必起容器。
probe_check "down 点名当前槽 + 记录里的孤儿槽" "chatapp-ci-s9 chatapp-ci-s10 " \
  "$(projects_to_teardown 9 "10 9")"
probe_check "母体检出(当前项目 chatapp-ci 由 down 主路径拆)时仍点名记录里的槽" \
  "chatapp-ci-s10 " "$(projects_to_teardown "" "10")"
state_root=$(mktemp -d)
state_out=$(env TMPDIR="$state_root" bash -c \
  '. "$1/scripts/stacks/env.sh"; ROOT="$2"; remember_slot 42; remember_slot 42; remember_slot 43; remembered_slots' \
  _ "$ROOT" "$state_root")
probe_check "状态文件记录去重(42 43)" "42 43 " "$state_out"
rm -rf "$state_root"
# 拆容器必须点名本项目,否则「只拆自己」不成立。
ddry=$(bash "$V" deps --dry-run 2>/dev/null)
case $ddry in
  *"-p $COMPOSE_PROJECT_NAME"*) printf 'ok   deps --dry-run 点名项目 %s\n' "$COMPOSE_PROJECT_NAME" ;;
  *) printf 'FAIL deps --dry-run 没有 -p %s\n' "$COMPOSE_PROJECT_NAME"; fail=1 ;;
esac
rm -rf "$tmp_a" "$tmp_b" "$tmp_c"
# 挂载文件权限兜底(scripts/stacks/mount-perms.sh,deps.sh 在 `up` 前调用它)。
# 场景:worker worktree 的 umask 077 会让被 compose 以 :ro 挂进容器的文件落成 0600,
# MySQL 初始化读不到 init 脚本就 Permission denied 退出 1 —— 表象像后端用例红了,实际是环境。
# 三个方向都要钉住:0600 → 0644 真的生效、清单外的文件不被误伤、清单里的路径真在仓库里。
. "$ROOT/scripts/stacks/mount-perms.sh"
perm_root=$(mktemp -d); mkdir -p "$perm_root/chatapp"
: > "$perm_root/chatapp/db_setup_ci.sql"; chmod 600 "$perm_root/chatapp/db_setup_ci.sql"
: > "$perm_root/chatapp/keep-0600.sql"; chmod 600 "$perm_root/chatapp/keep-0600.sql"
ensure_mount_readable "$perm_root"
perm=$(stat -c %a "$perm_root/chatapp/db_setup_ci.sql")
if [ "$perm" = 644 ]; then echo "ok   挂载文件 0600 被补成 0644(db_setup_ci.sql)"
else printf 'FAIL 挂载文件没被补成 0644,实际 %s\n' "$perm"; fail=1; fi
keep=$(stat -c %a "$perm_root/chatapp/keep-0600.sql")
if [ "$keep" = 600 ]; then echo "ok   清单外的文件模式不被改动"
else printf 'FAIL 清单外的文件被改了模式(应保持 600,实际 %s)\n' "$keep"; fail=1; fi
for rel in "${MOUNT_READ_FILES[@]}"; do
  if [ -f "$ROOT/$rel" ]; then printf 'ok   挂载权限清单条目在仓库里存在(%s)\n' "$rel"
  else printf 'FAIL 挂载权限清单里的 %s 在仓库里不存在(兜底会静默失效)\n' "$rel"; fail=1; fi
done
rm -rf "$perm_root"
[ "$fail" = 0 ] && echo "全部通过" || echo "有失败"
exit "$fail"
