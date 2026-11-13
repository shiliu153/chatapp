#!/usr/bin/env bash
# systemd timer 的实际入口:跑一轮巡检,有异常就发一条告警(同一种异常 6 小时内只发一次)。
#
# 为什么要有去重:定时器 15 分钟一轮,一个卡死的 assignment 会连续命中几十轮 ——
# 不去重就是每 15 分钟一封邮件,人会直接把告警规则关掉,那比没有告警更糟。
# 指纹变了(换了异常种类)或距上次发送超过 6 小时,才再发一次。
#
# 退出码语义(给 systemd 看,和 healthcheck.py 的 0/1/2 不同):
#   0 = 本轮没事,或者异常已经成功报出去了 —— 告警通道是我们选的通道,报出去就算完成。
#   1 = **巡检自己没完成**(判不出来,或者告警发不出去)。只有这一种才该让 systemd 标红:
#       否则「worker 有异常」会让 unit 每 15 分钟 failed 一次,真正的故障被自己的噪音埋掉。
set -uo pipefail

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ENV_FILE=${SUPERAGENT_HEALTH_ENV:-/root/.dsh/superagent-health.env}
STATE_DIR=${SUPERAGENT_HEALTH_STATE:-/root/.dsh/state/superagent-health}
RESEND_AFTER=${SUPERAGENT_HEALTH_RESEND_SECONDS:-21600}   # 6h
mkdir -p "$STATE_DIR"

# shellcheck source=/dev/null
[ -f "$ENV_FILE" ] && . "$ENV_FILE"

ISSUE_ARGS=()
if [ -n "${SUPERAGENT_HEALTH_ISSUES:-}" ]; then
  for n in $SUPERAGENT_HEALTH_ISSUES; do ISSUE_ARGS+=(--issue "$n"); done
fi

# 仓库里跑时检查器在 scripts/ 下;装到 /root/.dsh/healthcheck/ 后与 run.sh 同级。
if [ -z "${SUPERAGENT_HEALTH_CHECKER:-}" ]; then
  if [ -f "$HERE/superagent_health.py" ]; then
    CHECKER="$HERE/superagent_health.py"
  else
    CHECKER="$HERE/../superagent_health.py"
  fi
else
  CHECKER=$SUPERAGENT_HEALTH_CHECKER
fi

OUT=$(mktemp); trap 'rm -f "$OUT"' EXIT
python3 "$CHECKER" ${ISSUE_ARGS[@]+"${ISSUE_ARGS[@]}"} >"$OUT" 2>"$STATE_DIR/last-stderr.log"
RC=$?

cat "$OUT"

if [ "$RC" -eq 0 ]; then
  rm -f "$STATE_DIR/last-fingerprint" "$STATE_DIR/last-sent"
  exit 0
fi

FP=$( { printf 'rc=%s\n' "$RC"; grep -E '^(❌|❓)' "$OUT" || true; } | sha256sum | cut -c1-16)
LAST_FP=$(cat "$STATE_DIR/last-fingerprint" 2>/dev/null || true)
LAST_TS=$(cat "$STATE_DIR/last-sent" 2>/dev/null || echo 0)
NOW=$(date +%s)

if [ "$FP" = "$LAST_FP" ] && [ $((NOW - LAST_TS)) -lt "$RESEND_AFTER" ]; then
  echo "run: 同一异常 $FP 已于 $(( (NOW - LAST_TS) / 60 )) 分钟前告警过,本轮不重复发(每 $((RESEND_AFTER / 3600))h 提醒一次)"
  exit 0
fi

SUBJECT="[superagent] worker 健康检查异常(rc=$RC)"
{
  echo "时间:$(date -u +%FT%TZ)"
  echo "主机:$(hostname)"
  echo
  cat "$OUT"
  echo
  echo "下一步:"
  echo "  1) bash /root/start-superagent.sh status                      # 健康位"
  echo "  2) bash /root/src/chatapp/scripts/superagent-proxy/probe.sh   # 三路出网对比"
  echo "  3) 卡死的 assignment 需要新单或重启:见 docs/ops/superagent.md §3"
  echo
  echo "本文件:$STATE_DIR/last-alert.md"
} >"$STATE_DIR/pending-alert.md"

if bash "$HERE/notify.sh" "$SUBJECT" "$STATE_DIR/pending-alert.md"; then
  printf '%s' "$FP" >"$STATE_DIR/last-fingerprint"
  printf '%s' "$NOW" >"$STATE_DIR/last-sent"
  exit 0
fi

# 发送失败**不能**记指纹:记了就等于这条异常在 6 小时内不会再报(静默丢告警);
# 而且这里必须让 systemd 看见失败 —— 那是唯一一个「巡检自身失灵」的信号。
echo "run: 告警没发出去,不记指纹(下一轮会重试);内容见 $STATE_DIR/last-alert.md" >&2
exit 1
