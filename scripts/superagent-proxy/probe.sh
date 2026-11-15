#!/bin/bash
# 三路出口对比探针:直连 / 宿主 Clash / WSL 自建 mihomo。
#
# 为什么需要这个脚本:2026-11-09 换代理这件事,唯一的判据是「worker 拉 GitHub
# 到底稳不稳」。文档 §11 记的现象是 api.github.com 的新建 TLS 连接被间歇重置,
# 而当时"走宿主代理"和"直连"一样差。如果换完不看数据,就没法区分
# 「真的修好了」和「今天恰好没抖」。
#
# 判据为什么这么严(2026-11-15 加严):
#   1. **只有 HTTP 2xx 才算一次成功**。此前只看 curl 退出码,于是「通是通了、
#      但代理那条路返回 403」被算成成功 —— 落地页、限流页、机场错误页都会这样,
#      人看到 20/20 会以为一切正常。
#   2. **默认一次失败都不许**(--allow-fail N 可放宽)。worker 一轮轮询要串行读
#      60~100 次 GitHub(每次约 10s),单请求 2% 的失败率就足以让整轮踩雷并让
#      health.github 掉 error(§11 / §14.4 的口径)。「偶发 000」不是可以接受的抖动。
#   3. 三路对比照旧:判据仍然是「mihomo 不能比直连差」,但比较的是**成功次数**,
#      而成功的前提是 2xx。
#
# 用法:
#   bash probe.sh                  # 各 30 次(约 1~2 分钟)
#   bash probe.sh --count 10       # 快速版
#   bash probe.sh --allow-fail 1   # 排障时放宽:允许 1 次失败
#   bash probe.sh --target https://github.com
#   PROBE_VERBOSE=1 bash probe.sh  # 把每次失败样本的 HTTP 码打出来
#
# 退出码:0 = mihomo 可用(2xx 成功数达标且不差于直连);1 = 不可用或不健康(别切)
set -uo pipefail

COUNT=30
TARGET=${TARGET:-https://api.github.com/rate_limit}
MIHOMO_PORT=${MIHOMO_PORT:-7890}
HOST_PORT=${HOST_PORT:-7897}
TIMEOUT=${TIMEOUT:-8}
#: 允许多少次失败。0 = 一次都不许 —— 见文件头「判据为什么这么严」。
ALLOW_FAIL=${ALLOW_FAIL:-0}
CTRL_PORT=${CTRL_PORT:-9091}
CONTROLLER_SECRET=${CONTROLLER_SECRET:-/root/.dsh/proxy/controller.secret}

HOSTIP=$(ip route show default 2>/dev/null | awk '{print $3}' | head -1)
HOST_PROXY="http://${HOSTIP}:${HOST_PORT}"
MIHOMO_PROXY="http://127.0.0.1:${MIHOMO_PORT}"

usage() { sed -n '2,32p' "$0"; }

# 打一路探针,结果写进 PROBE_OK / PROBE_FAIL(成功 = HTTP 2xx)。
# 参数说明:
#   $1 = 标签(只用于打印) $2 = 代理地址,空字符串表示直连
# 返回参数:
#   无(结果写全局 PROBE_OK / PROBE_FAIL)
# 备注信息:
#   失败样本默认不逐条打印(30 次全挂时会刷满屏),要明细就设 PROBE_VERBOSE=1。
probe() {
  local label="$1" proxy="$2" ok=0 fail=0 total=0 i pair http t avg="n/a"
  for i in $(seq "$COUNT"); do
    if [ -n "$proxy" ]; then
      pair=$(curl -sS -m "$TIMEOUT" -x "$proxy" -o /dev/null \
               -w '%{http_code} %{time_total}' "$TARGET" 2>/dev/null)
    else
      pair=$(curl -sS -m "$TIMEOUT" --noproxy '*' -o /dev/null \
               -w '%{http_code} %{time_total}' "$TARGET" 2>/dev/null)
    fi
    http=${pair%% *}
    t=${pair##* }
    case "${http:-000}" in
      2[0-9][0-9])
        ok=$((ok + 1))
        total=$(awk -v a="$total" -v b="$t" 'BEGIN{print a+b}')
        ;;
      *)
        fail=$((fail + 1))
        if [ -n "${PROBE_VERBOSE:-}" ]; then
          echo "    失败样本 #$i:http=${http:-000}" >&2
        fi
        ;;
    esac
  done
  [ "$ok" -gt 0 ] && avg=$(awk -v t="$total" -v n="$ok" 'BEGIN{printf "%.3fs", t/n}')
  printf '%-18s ok=%-3s fail=%-3s 成功率=%3d%%  平均耗时=%s\n' \
    "$label" "$ok" "$fail" "$((ok * 100 / COUNT))" "$avg"
  PROBE_OK=$ok
  PROBE_FAIL=$fail
}

# 打印出口组的当前选中节点与最近一次健康检查结果 —— 这是「换没换节点」唯一可查的地方。
# 参数说明:
#   无(读控制器密钥 $CONTROLLER_SECRET 与端口 $CTRL_PORT)
# 返回参数:
#   无;查询失败只打印一行 n/a,不影响退出码(排障信息不该把探针本身判死)
# 备注信息:
#   为什么需要它:2026-11-14 那次 2 分钟断流,mihomo 的 journal 里**只有 match 行**
#   (每条连接一行 `using 节点选择[…IEPL 0x]`),`grep -v '\[TCP\]'` 之后一片空白 ——
#   也就是说「当时选的哪个节点、健康检查挂了没」在日志里查不出来。控制器 API 有这些数据。
show_selection() {
  if [ ! -s "$CONTROLLER_SECRET" ]; then
    echo "  (读不到 $CONTROLLER_SECRET,跳过;这张表只在装了代理的机器上有)"
    return 0
  fi
  command -v python3 >/dev/null 2>&1 || { echo "  (没有 python3,跳过)"; return 0; }
  python3 - "$CONTROLLER_SECRET" "$CTRL_PORT" <<'PY'
import json
import sys
import urllib.parse
import urllib.request

secret_path, port = sys.argv[1], sys.argv[2]
token = open(secret_path, encoding="utf-8").read().strip()


def fetch(name):
    url = f"http://127.0.0.1:{port}/proxies/" + urllib.parse.quote(name, safe="")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=3) as resp:
        return json.load(resp)


for name in ("github-fallback", "github", "节点选择"):
    try:
        data = fetch(name)
    except Exception as exc:  # noqa: BLE001 — 排障信息,链路问题不该抛栈
        print(f"  {name:<16} n/a({type(exc).__name__})")
        continue
    history = data.get("history") or []
    last = history[-1] if history else {}
    print(
        f"  {name:<16} now={data.get('now')}  最近健康检查 delay={last.get('delay', '-')}ms"
    )
PY
}

# 判定这一轮能不能用,并打印结论。
# 参数说明:
#   $1 = mihomo 成功次数 $2 = mihomo 失败次数 $3 = 直连成功次数 $4 = 直连失败次数
# 返回参数:
#   0 = 可用;1 = 不可用或不健康
# 备注信息:
#   独立成函数是为了能被 scripts/superagent-proxy/selftest.sh source 进来离线打桩
#   —— 判据本身也要有回归,不能只靠「今天跑了一次看着还行」。
judge() {
  local m_ok=$1 m_fail=$2 d_ok=$3 d_fail=$4
  if [ "$m_ok" -eq 0 ]; then
    echo "结论:mihomo 完全不通(${m_fail}/${COUNT} 失败)—— 先看 journalctl -u superagent-proxy -n 50 --no-pager"
    return 1
  fi
  if [ "$m_fail" -gt "$ALLOW_FAIL" ]; then
    echo "结论:mihomo 有 ${m_fail}/${COUNT} 次失败(允许 ${ALLOW_FAIL})—— **间歇失败也算不健康**。"
    echo "      一轮轮询要读 60~100 次 GitHub,单请求几个百分点的失败率就足以让整轮踩雷(§11)。"
    echo "      先看上面那张「当前出口组」表里的 delay:某条线路长期高延迟或刚判死,就去调"
    echo "      override.yaml 的 include_pattern 换一批线路,再跑 refresh.sh。"
    return 1
  fi
  if [ "$m_ok" -lt "$d_ok" ]; then
    echo "结论:mihomo 比直连更差(${m_ok}/${COUNT} vs ${d_ok}/${COUNT})。"
    echo "      可能是选的节点不行:调 override.yaml 的 include_pattern 换一批线路,"
    echo "      或直接把 MATCH 指向 DIRECT(只让需要翻的域名走代理)。"
    return 1
  fi
  echo "结论:mihomo ${m_ok}/${COUNT}(失败 ${m_fail}),直连 ${d_ok}/${COUNT}(失败 ${d_fail})—— 可以用。"
  return 0
}

main() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --count) COUNT="$2"; shift 2 ;;
      --target) TARGET="$2"; shift 2 ;;
      --allow-fail) ALLOW_FAIL="$2"; shift 2 ;;
      -h|--help) usage; exit 0 ;;
      *) echo "未知参数:$1" >&2; exit 2 ;;
    esac
  done
  case "$ALLOW_FAIL" in
    ''|*[!0-9]*) echo "--allow-fail 必须是整数" >&2; exit 2 ;;
  esac

  echo "目标:$TARGET   次数:$COUNT   单次超时:${TIMEOUT}s   允许失败:$ALLOW_FAIL"
  echo "------------------------------------------------------------"
  probe "直连" "";               DIRECT_OK=$PROBE_OK; DIRECT_FAIL=$PROBE_FAIL
  probe "宿主 Clash" "$HOST_PROXY"; HOST_OK=$PROBE_OK; HOST_FAIL=$PROBE_FAIL
  probe "WSL mihomo" "$MIHOMO_PROXY"; MIHOMO_OK=$PROBE_OK; MIHOMO_FAIL=$PROBE_FAIL
  echo "------------------------------------------------------------"
  echo "当前出口组(控制器 127.0.0.1:${CTRL_PORT}):"
  show_selection
  echo "------------------------------------------------------------"
  judge "$MIHOMO_OK" "$MIHOMO_FAIL" "$DIRECT_OK" "$DIRECT_FAIL"
}

# 被 source(自测)时只定义函数,不真跑探针。
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  main "$@"
fi
