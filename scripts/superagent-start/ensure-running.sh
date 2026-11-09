#!/bin/bash
# 确保 superagent 在跑;没跑就拉起来,并等到真的能接单才返回。
#
# 为什么需要这个:派工单的动作是「在 issue 里评论 @shiliu655」,而读评论的
# superagent 跑在 WSL 里。WSL 没起来时评论**不会有人读**,单子看起来派了、
# 实际在空转 —— 和 docs/ops/superagent.md §4.1「入队三连」里记的那种
# 「静默丢单」长得一模一样,极难区分。所以派单前先确认这一环。
#
# 2026-11-09 实测踩到的两个坑(都已在本脚本里处理):
#   1. **残留锁**:`wsl --shutdown` 会 SIGKILL 掉 DSH,它来不及释放
#      `$STATE.lock`(proper-lockfile 锁的是整个 state 目录)。WSL 再起来时
#      新实例看到锁还在就报 `Lock file is already being held`,orchestrator
#      永远起不来,`status` 一直返回 1、API 一直 404 —— 看起来像「WSL 起了但
#      superagent 没起」,重启也不管用。所以:没有 dsh 进程却有锁 = stale,清掉。
#   2. **github 首轮很慢**:首轮要串行读完 67 个订阅 Thread,冷启动后约 20 分钟
#      (docs/ops/superagent.md §12.6)。所以「可用」不能等 github ready,
#      否则每次冷启动都要干等 20 分钟。
#
# 退出码:0 = 可以派单;1 = 拉不起来,别派
set -uo pipefail

START=/root/start-superagent.sh
STATE=${STATE:-/root/.dsh/state/superagent}
LOCK="$STATE.lock"
WAIT=${WAIT:-150}          # 等「能接单」的上限(秒)

say() { echo "[ensure] $*"; }
warn() { echo "[ensure] warn: $*" >&2; }
die() { echo "[ensure] 失败:$*" >&2; exit 1; }

[ -x "$START" ] || die "找不到 $START(先跑 scripts/superagent-start/install.sh)"

TMPJ=$(mktemp)
trap 'rm -f "$TMPJ"' EXIT

status_code() {
  bash "$START" status >"$TMPJ" 2>/dev/null
  echo $?
}

dsh_pids() { pgrep -f 'node /usr/local/bin/dsh' 2>/dev/null | tr '\n' ' '; }

# 判定「能接单」:退出码 0(十项全 ready),或 health 里除 github 外都 ready
# 且 github 是 starting(说明轮询已经在跑,只是首轮还没读完)。
usable() {
  local code
  code=$(status_code)
  [ "$code" = 0 ] && return 0
  [ "$code" = 1 ] || return 1
  python3 - "$TMPJ" <<'PY'
import json, sys
try:
    d = json.load(open(sys.argv[1], encoding='utf-8'))
except Exception:
    sys.exit(1)
h = d.get('health')
if not isinstance(h, dict) or not h:
    sys.exit(1)
# 任何一项不是 ready/starting 都不算可用
if any(v not in ('ready', 'starting') for v in h.values()):
    sys.exit(1)
# 除 github 外必须全部 ready;github 允许 starting(首轮慢)
others = {k: v for k, v in h.items() if k != 'github'}
if others and all(v == 'ready' for v in others.values()):
    sys.exit(0)
sys.exit(1)
PY
}

# ---------- 0. 等 systemd ----------
for i in $(seq 30); do
  state=$(systemctl is-system-running 2>/dev/null || true)
  case "$state" in running|degraded) break ;; esac
  [ "$i" = 1 ] && say "等 systemd 就绪(冷启动可能要几十秒)…"
  sleep 1
done
say "systemd: ${state:-unknown}"

# ---------- 1. 判定当前状态 ----------
code=$(status_code)
case "$code" in
  0) say "superagent 已在跑且全 ready" ;;
  2) die "superagent 有部件报错(status 退出码 2),重启无效 —— 去面板 http://127.0.0.1:3082 的 Overview 看是哪一项" ;;
  3) die "superagent 在等设置(status 退出码 3)—— 面板上有没填完的配置" ;;
  1)
    pids=$(dsh_pids)
    if [ -z "${pids// /}" ] && [ -d "$LOCK" ]; then
      # 没有 dsh 进程却有锁 —— 这就是 WSL 冷启动留下的 stale 锁。
      # 只在「确实没有进程」时清:有进程却抢不到锁,说明是真并发,清了会打架。
      warn "发现残留锁 $LOCK(没有 dsh 进程在跑,是上次被强杀的痕迹),清掉"
      rm -rf "$LOCK"
    fi
    say "superagent 没在跑或没响应,拉起…"
    # --timeout 90:冷启动后 DSH 要初始化(读库/迁移/起服务),60s 不够稳。
    bash "$START" start --timeout 90 >/dev/null 2>&1 || true
    ;;
  *) die "status 返回了预期外的退出码 $code" ;;
esac

# ---------- 2. 等到能接单 ----------
deadline=$(( $(date +%s) + WAIT ))
while [ "$(date +%s)" -lt "$deadline" ]; do
  if usable; then
    say "superagent 可接单(等了 $(( WAIT - (deadline - $(date +%s)) ))s)"
    break
  fi
  # 拉起后仍然抢不到锁:再清一次(可能是两次启动之间的窗口)
  if [ -z "$(dsh_pids)" ] && [ -d "$LOCK" ]; then
    warn "拉起后仍无进程且锁还在,再清一次并重启"
    rm -rf "$LOCK"
    bash "$START" start --timeout 90 >/dev/null 2>&1 || true
  fi
  sleep 3
done

usable || die "等了 ${WAIT}s 仍不能接单。看面板 http://127.0.0.1:3082 或 bash $START status"

# ---------- 3. 提示首轮轮询 ----------
# github 首轮要串行读完所有订阅 Thread(冷启动后约 20 分钟)。这期间派单
# 不会被漏掉(游标会推进),但「入队三连」里 thread/ticket 三张表可能要等。
python3 - "$TMPJ" <<'PY'
import json, sys
try:
    h = json.load(open(sys.argv[1], encoding='utf-8')).get('health') or {}
except Exception:
    sys.exit(0)
if h.get('github') == 'starting':
    print("[ensure] 提示:github 仍在首轮轮询(冷启动后约 20 分钟)。现在派单不会丢,"
          "但按 §4.1 核回执时 thread/ticket 可能要等到首轮结束。", file=sys.stderr)
PY

# ---------- 4. 周边依赖(只报告,不拦) ----------
if ! curl -fsS -m 3 "http://127.0.0.1:8788/__failover/health" >/dev/null 2>&1; then
  warn "模型兜底代理(8788)没响应,worker 的模型调用会全挂:systemctl status superagent-failover"
fi
if ! timeout 2 bash -c 'echo > /dev/tcp/127.0.0.1/7890' 2>/dev/null; then
  warn "出口代理(7890)没监听,worker 的外网操作会失败:systemctl status superagent-proxy"
fi
if command -v docker >/dev/null 2>&1; then
  # 只盯 worker 真正需要的两个容器:它们的 restart 策略是 no(实测 2026-11-09),
  # 所以 WSL 一重启就不会自己回来 —— 而 verify.sh 没有 MySQL/Redis 会全红。
  running=$(docker ps --format '{{.Names}}' 2>/dev/null)
  missing=""
  for c in chatapp-ci-mysql chatapp-ci-redis; do
    echo "$running" | grep -qx "$c" || missing="$missing $c"
  done
  if [ -n "$missing" ]; then
    warn "worker 的验证环境没起:$missing(容器 restart=no,WSL 重启后不会自恢复)"
    warn "  修:cd <工单目录> && docker compose -f docker-compose.ci.yml up -d --wait"
  else
    say "docker:chatapp-ci-mysql / chatapp-ci-redis 在跑"
  fi
else
  warn "找不到 docker 命令"
fi

say "可以派单了"
exit 0
