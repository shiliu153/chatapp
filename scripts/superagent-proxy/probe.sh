#!/bin/bash
# 三路出口对比探针:直连 / 宿主 Clash / WSL 自建 mihomo。
#
# 为什么需要这个脚本:2026-11-09 换代理这件事,唯一的判据是「worker 拉 GitHub
# 到底稳不稳」。文档 §11 记的现象是 api.github.com 的新建 TLS 连接被间歇重置,
# 而当时"走宿主代理"和"直连"一样差。如果换完不看数据,就没法区分
# 「真的修好了」和「今天恰好没抖」。
#
# 用法:
#   bash probe.sh                # 各 30 次(约 1~2 分钟)
#   bash probe.sh --count 10     # 快速版
#   bash probe.sh --target https://github.com
#
# 退出码:0 = mihomo 可用且不差于直连;1 = mihomo 不可用或明显更差(别切)
set -uo pipefail

COUNT=30
TARGET=${TARGET:-https://api.github.com/rate_limit}
MIHOMO_PORT=${MIHOMO_PORT:-7890}
HOST_PORT=${HOST_PORT:-7897}
TIMEOUT=${TIMEOUT:-8}

while [ $# -gt 0 ]; do
  case "$1" in
    --count) COUNT="$2"; shift 2 ;;
    --target) TARGET="$2"; shift 2 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "未知参数:$1" >&2; exit 2 ;;
  esac
done

HOSTIP=$(ip route show default | awk '{print $3}' | head -1)
HOST_PROXY="http://${HOSTIP}:${HOST_PORT}"
MIHOMO_PROXY="http://127.0.0.1:${MIHOMO_PORT}"

probe() {
  # $1 = 标签, $2 = 代理(空字符串=直连)
  local label="$1" proxy="$2" ok=0 fail=0 total=0 i t
  for i in $(seq "$COUNT"); do
    if [ -n "$proxy" ]; then
      t=$(curl -sS -m "$TIMEOUT" -x "$proxy" -o /dev/null -w '%{time_total}' "$TARGET" 2>/dev/null) && ok=$((ok+1)) || fail=$((fail+1))
    else
      t=$(curl -sS -m "$TIMEOUT" --noproxy '*' -o /dev/null -w '%{time_total}' "$TARGET" 2>/dev/null) && ok=$((ok+1)) || fail=$((fail+1))
    fi
    [ -n "${t:-}" ] && total=$(awk -v a="$total" -v b="$t" 'BEGIN{print a+b}')
  done
  local avg="n/a"
  [ "$ok" -gt 0 ] && avg=$(awk -v t="$total" -v n="$ok" 'BEGIN{printf "%.3fs", t/n}')
  printf '%-18s ok=%-3s fail=%-3s 成功率=%3d%%  平均耗时=%s\n' \
    "$label" "$ok" "$fail" "$(( ok * 100 / COUNT ))" "$avg"
  PROBE_OK=$ok
}

echo "目标:$TARGET   次数:$COUNT"
echo "------------------------------------------------------------"
probe "直连"          ""
DIRECT_OK=$PROBE_OK
probe "宿主 Clash"    "$HOST_PROXY"
HOST_OK=$PROBE_OK
probe "WSL mihomo"    "$MIHOMO_PROXY"
MIHOMO_OK=$PROBE_OK
echo "------------------------------------------------------------"

if [ "$MIHOMO_OK" -eq 0 ]; then
  echo "结论:mihomo 完全不通 —— 先看 journalctl -u superagent-proxy -n 50 --no-pager"
  exit 1
fi

if [ "$MIHOMO_OK" -lt "$DIRECT_OK" ]; then
  echo "结论:mihomo 比直连更差($MIHOMO_OK/$COUNT vs $DIRECT_OK/$COUNT)。"
  echo "      可能是选的节点不行:调 override.yaml 的 include_pattern 换一批线路,"
  echo "      或直接把 MATCH 指向 DIRECT(只让需要翻的域名走代理)。"
  exit 1
fi

echo "结论:mihomo $MIHOMO_OK/$COUNT,直连 $DIRECT_OK/$COUNT,宿主 $HOST_OK/$COUNT —— 可以用。"
exit 0
