#!/usr/bin/env bash
# start-superagent.sh「选路判定」的离线自测:不联网、不碰真实配置、不需要 root。
#
# 为什么值得写:这是「端口活但出网 0%」唯一的机械防线。2026-11-13 的事故里,
# 7890 在听、经它出网 0%,而旧判据只看端口 → 永不回退 → worker 全断,面板却全绿。
# 选路逻辑要是哪天被「顺手简化」回只看端口,现场不会有任何信号 —— 所以在这里钉住。
#
# 做法:source 启动脚本(它有「被 source 时不执行 main」的开关),然后
#   - 重定义 port_open,把「哪个端口在听」变成可控输入;
#   - 用 EGRESS_PROBE_CMD 给真实出网探测打桩(退出码 0 = 通)。
# 于是三档场景全在本地毫秒级跑完,不依赖真代理、不依赖本机默认路由。
#
# 用法:bash scripts/test_start_superagent.sh
set -uo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
S="$ROOT/scripts/superagent-start/start-superagent.sh"
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT

pass=0
fail=0
say() { printf '%-6s %s\n' "$1" "$2"; }
ok() { say "ok" "$1"; pass=$((pass + 1)); }
bad() { say "FAIL" "$1"; fail=$((fail + 1)); }

[ -f "$S" ] || { echo "找不到 $S"; exit 2; }

# ---------- 载入选路逻辑(只定义函数,不执行 main) ----------
# HOSTIP/PROXY_PORT/FALLBACK_PORT 在 source 时定全局,所以放在环境里传进去;
# SUPERAGENT_ENV_FILE 指到 /dev/null,免得读到本机真实配置。
export SUPERAGENT_ENV_FILE=/dev/null
export HOSTIP=172.26.240.1
export PROXY_PORT=7890
export FALLBACK_PORT=7897
export EGRESS_PROBE_BACKOFF=0        # 自测不等退避
# shellcheck source=scripts/superagent-start/start-superagent.sh
. "$S"

MIHOMO="http://127.0.0.1:7890"
HOSTPX="http://172.26.240.1:7897"

# 「哪些 host:port 在听」——用 port_open 的桩喂给选路函数
PORTS=""
port_open() {
  case " $PORTS " in
    *" $1:$2 "*) return 0 ;;
  esac
  return 1
}

# 跑一次选路:在当前 shell 里跑(结果变量要留在本进程),stderr 收进 OUT。
# 打桩命令的调用次数记在 COUNT 文件里,用来验「连续 N 次才切」。
OUT=""
run_select() {
  local err="$T/err"
  : >"$err"
  select_route 2>"$err"
  OUT=$(cat "$err")
}

# 断言:描述 / 期望的 PROXY_SOURCE / 期望的 PROXY / 期望日志里含的片段
assert_route() {
  local desc=$1 want_src=$2 want_proxy=$3 needle=${4:-}
  local why=""
  [ "$PROXY_SOURCE" = "$want_src" ] || why="PROXY_SOURCE=$PROXY_SOURCE(期望 $want_src)"
  [ "$PROXY" = "$want_proxy" ] || why="$why PROXY=$PROXY(期望 $want_proxy)"
  if [ -n "$needle" ]; then
    case "$OUT" in *"$needle"*) ;; *) why="$why 日志缺「$needle」" ;; esac
  fi
  if [ -z "$why" ]; then
    ok "$desc"
  else
    bad "$desc —— $why"
    printf '%s\n' "$OUT" | sed 's/^/     | /'
  fi
}

assert_not_in_log() { # 描述 / 不该出现的片段
  case "$OUT" in
    *"$2"*) bad "$1 —— 日志里不该出现「$2」"; printf '%s\n' "$OUT" | sed 's/^/     | /' ;;
    *) ok "$1" ;;
  esac
}

assert_count() { # 描述 / 期望的探测次数
  local got
  got=$(cat "$T/probe.calls" 2>/dev/null | wc -l | tr -d ' ')
  if [ "$got" = "$2" ]; then ok "$1(探测 $got 次)"; else bad "$1 —— 探测 $got 次,期望 $2"; fi
}

# 打桩:每次探测都记一笔,然后按 STUB_RC 决定通不通
cat >"$T/probe.sh" <<'EOF'
echo x >>"$PROBE_CALLS"
exit "${STUB_RC:-1}"
EOF
export PROBE_CALLS="$T/probe.calls"
EGRESS_PROBE_CMD="sh $T/probe.sh"
export EGRESS_PROBE_CMD

reset_probe() { # $1 = 探测桩的退出码
  : >"$T/probe.calls"
  STUB_RC=$1
  export STUB_RC
}

# ---------- 1. 端口活 + 出网通 → 仍选 mihomo(与改造前一致) ----------
PORTS="127.0.0.1:7890 172.26.240.1:7897"
EGRESS_FAIL_THRESHOLD=3
reset_probe 0
run_select
assert_route "端口活 + 出网通 → 选 mihomo" mihomo "$MIHOMO" "[select] mihomo ok"
assert_count "出网通时只探 1 次" 1

# ---------- 2. 端口活 + 出网 0% → 回退宿主,并打出可 grep 的那行 ----------
reset_probe 1
run_select
assert_route "端口活 + 出网 0% → 回退宿主代理" host "$HOSTPX" "[select] egress-bad → fallback host"
assert_count "连续失败满阈值(3)次才切" 3

# ---------- 3. 抖动一次后恢复 → 不切路(阈值防抖) ----------
cat >"$T/flap.sh" <<'EOF'
n=$(cat "$PROBE_CALLS.n" 2>/dev/null)
n=$(( ${n:-0} + 1 ))
echo "$n" >"$PROBE_CALLS.n"
[ "$n" -ge 2 ]
EOF
rm -f "$T/probe.calls.n"
EGRESS_PROBE_CMD="sh $T/flap.sh"
export EGRESS_PROBE_CMD
run_select
assert_route "抖动一次后恢复 → 不切路" mihomo "$MIHOMO" "[select] mihomo ok"
tries=$(cat "$T/probe.calls.n" 2>/dev/null || echo 0)
[ "$tries" = 2 ] && ok "抖动场景:第 2 次探测成功即停(共 $tries 次)" \
  || bad "抖动场景探了 $tries 次,期望 2"
EGRESS_PROBE_CMD="sh $T/probe.sh"
export EGRESS_PROBE_CMD

# ---------- 4. 端口不在听 → 原有「回退宿主」分支,行为不变 ----------
PORTS="172.26.240.1:7897"
reset_probe 1
run_select
assert_route "mihomo 端口不在听 → 回退宿主" host "$HOSTPX" "[select] port-dead → fallback host"
assert_count "端口不在听时不做出网探测" 0

# ---------- 5. 两条都不通 → 预置 mihomo 地址 + 警告,行为不变 ----------
PORTS=""
run_select
assert_route "两条都不通 → 预置 mihomo 地址" none "$MIHOMO" "[select] port-dead → no fallback"
case "$OUT" in
  *"会全部失败"*) ok "两条都不通时打出「外网操作会全部失败」的警告" ;;
  *) bad "两条都不通时缺警告文案"; printf '%s\n' "$OUT" | sed 's/^/     | /' ;;
esac

# ---------- 6. 端口活但出网不通 + 宿主也不在听 → 落在「都不通」 ----------
PORTS="127.0.0.1:7890"
reset_probe 1
run_select
assert_route "端口活 + 出网 0% + 无兜底 → 预置 mihomo 并警告" none "$MIHOMO" "[select] egress-bad → no fallback"

# ---------- 7. EGRESS_PROBE=off → 退回只看端口,探测一次都不跑 ----------
export EGRESS_PROBE=off
PORTS="127.0.0.1:7890 172.26.240.1:7897"
reset_probe 1
run_select
assert_route "EGRESS_PROBE=off → 只看端口,仍选 mihomo" mihomo "$MIHOMO"
assert_count "EGRESS_PROBE=off 时不跑探测命令" 0
EGRESS_PROBE=on

# ---------- 8. 阈值可覆盖 ----------
export EGRESS_FAIL_THRESHOLD=2
reset_probe 1
run_select
assert_count "EGRESS_FAIL_THRESHOLD 可覆盖(2 次)" 2
EGRESS_FAIL_THRESHOLD=3

# ---------- 9. 默认阈值 = 3(env 里写坏时也回到 3,别让算术报错) ----------
def=$(bash -c 'unset EGRESS_FAIL_THRESHOLD; SUPERAGENT_ENV_FILE=/dev/null; . "$1"; echo "$EGRESS_FAIL_THRESHOLD"' _ "$S" 2>/dev/null)
[ "$def" = 3 ] && ok "默认阈值 3" || bad "默认阈值是「$def」,期望 3"
forged=$(bash -c 'EGRESS_FAIL_THRESHOLD=abc; SUPERAGENT_ENV_FILE=/dev/null; . "$1"; echo "$EGRESS_FAIL_THRESHOLD"' _ "$S" 2>/dev/null)
[ "$forged" = 3 ] && ok "阈值写成非数字时回落到 3" || bad "非数字阈值被当成「$forged」"

# ---------- 10. 默认探测 URL 必须是 /rate_limit(issue #303) ----------
# 为什么钉住:根路径 `https://api.github.com/` 在本机机场出口上恒 403(直连才 200),
# 用它当默认值会让选路把**可用的 mihomo** 判成不通 —— 每次启动白等 18s、打假警报,
# 而且宿主那条路一旦起来就会把 worker 反向切到更差的路。这条用例就是防那次回归。
def_url=$(bash -c 'unset EGRESS_PROBE_URL; SUPERAGENT_ENV_FILE=/dev/null; . "$1"; echo "$EGRESS_PROBE_URL"' _ "$S" 2>/dev/null)
case "$def_url" in
  */rate_limit) ok "默认探测 URL 是 /rate_limit($def_url)" ;;
  *) bad "默认探测 URL 是「$def_url」,期望以 /rate_limit 结尾(根路径在机场出口上恒 403,见 issue #303)" ;;
esac

# ---------- 11. 探测命令只吃 $1 = 代理 URL ----------
# 契约:EGRESS_PROBE_CMD 里可以用 $1 取代理 URL(所以替换命令不能只写「跑个脚本」,
# 得把 $1 传进去;这里直接用内联写法验证 $1 真的是被选中的那条路)。
export PROBE_ARGS="$T/probe.args"
: >"$PROBE_ARGS"
EGRESS_PROBE_CMD="echo \"\$1\" >>'$PROBE_ARGS'"
export EGRESS_PROBE_CMD
PORTS="127.0.0.1:7890 172.26.240.1:7897"
run_select
got=$(head -1 "$PROBE_ARGS" 2>/dev/null || true)
[ "$got" = "$MIHOMO" ] && ok "探测命令拿到代理 URL 作 \$1" || bad "探测命令 \$1 是「$got」,期望 $MIHOMO"

echo "------------------------------------------------------------"
echo "通过 $pass,失败 $fail"
[ "$fail" -eq 0 ] || exit 1
