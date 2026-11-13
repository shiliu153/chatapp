#!/bin/bash
# 启动 dsh-superagent:带模型密钥、PATH,以及出口代理。
#
# 这是 /root/start-superagent.sh 的仓库版本。它之前只存在于 WSL 的 /root 下,
# 没有版本控制 —— 也就是说「worker 为什么连不上网」这件事的关键一环不在仓库里,
# 换机器/重装就丢。现在源码在 scripts/superagent-start/,用 install.sh 部署。
#
# 出口代理的选路顺序(2026-11-13 起判据 = 端口活 **且** 出网真通):
#   1. WSL 内自建 mihomo(127.0.0.1:7890)—— 默认,走机场 IEPL 专线
#   2. 宿主 Clash(网关:7897)—— 兜底,mihomo 没装/没起来/出网不通时用
#   3. 都没有 —— 大声警告,但**仍然启动**(不因为网络暂时不通就把整个
#      superagent 拦下;worker 起来后照样能接单,只是外网操作会失败)
#
# 为什么 2026-11-13 让真实出网探测参与选路(此前只看「端口在听」):
# 旧判据的理由是 §12 的实测 —— 宿主 Clash 对 api.github.com 失败率 50%,
# 比直连还差,拿会抖的探针选路会把 worker 切到更差的那条。
# 2026-11-13 的事故正好落在盲区里:7890 在听、经它出网 0%(宿主 aTrust 的 WFP
# 过滤器把 WSL 直连 TCP 全拦了),于是**永不回退**,worker 全断而面板全绿。
# 现在:端口活着再补一次真实出网探测,**连续失败 EGRESS_FAIL_THRESHOLD 次
# (默认 3)才判这条路不可用** —— 单次抖动不切路,真断了十几秒内就能看见。
#
# 环境变量(全部可省,给自测与临时排障用):
#   PROXY_PORT / FALLBACK_PORT   mihomo / 宿主 Clash 的 mixed-port
#   EGRESS_PROBE=off             关掉真实出网探测(退回只看端口;离线自测用)
#   EGRESS_FAIL_THRESHOLD=N      连续失败几次才判不可用(默认 3,最小 1)
#   EGRESS_PROBE_CMD='...'       替换探测命令($1 = 代理 URL,退出码 0 = 通)
#   EGRESS_PROBE_URL/_TIMEOUT    默认探测的目标与单次超时(默认 5 秒)
#   EGRESS_PROBE_BACKOFF=秒      两次尝试之间等多久(默认 1,自测设 0)
#   SUPERAGENT_ENV_FILE=路径     读哪个 env 文件(默认 /root/.dsh/superagent.env)
#
# 用法(与旧版完全一致,从 Windows 侧):
#   wsl -e bash /root/start-superagent.sh start|status|stop|restart
set -uo pipefail

SUPERAGENT_ENV_FILE=${SUPERAGENT_ENV_FILE:-/root/.dsh/superagent.env}
[ -f "$SUPERAGENT_ENV_FILE" ] && . "$SUPERAGENT_ENV_FILE"

PROXY_PORT=${PROXY_PORT:-7890}              # mihomo 的 mixed-port
FALLBACK_PORT=${FALLBACK_PORT:-7897}        # 宿主 Clash 的 mixed-port
HOSTIP=${HOSTIP:-$(ip route show default 2>/dev/null | awk '{print $3}' | head -1)}
MIHOMO_PROXY="http://127.0.0.1:${PROXY_PORT}"
HOST_PROXY="http://${HOSTIP}:${FALLBACK_PORT}"

EGRESS_PROBE=${EGRESS_PROBE:-on}            # off = 不做真实出网探测,只看端口
EGRESS_PROBE_URL=${EGRESS_PROBE_URL:-https://api.github.com/}
EGRESS_PROBE_TIMEOUT=${EGRESS_PROBE_TIMEOUT:-5}
EGRESS_PROBE_BACKOFF=${EGRESS_PROBE_BACKOFF:-1}
EGRESS_PROBE_CMD=${EGRESS_PROBE_CMD:-}      # 空 = 用内置 curl
EGRESS_FAIL_THRESHOLD=${EGRESS_FAIL_THRESHOLD:-3}
# 阈值必须是正整数:env 写错(空/非数字/0)时按默认值办,别让一段算术报错把启动搞挂。
case "$EGRESS_FAIL_THRESHOLD" in
  ''|*[!0-9]*) EGRESS_FAIL_THRESHOLD=3 ;;
esac
[ "$EGRESS_FAIL_THRESHOLD" -ge 1 ] || EGRESS_FAIL_THRESHOLD=1

port_open() {
  [ -n "${1:-}" ] && timeout 2 bash -c "echo > /dev/tcp/$1/$2" 2>/dev/null
}

# 真实出网探测开着吗?(关掉时一切回到「只看端口」的旧行为)
egress_probe_enabled() {
  case "$EGRESS_PROBE" in
    off|OFF|0|no|false) return 1 ;;
  esac
  return 0
}

# 一次真实出网探测:退出码 0 = 这条路现在能出网。
#
# 判据是 HTTP 状态码而不是 curl 退出码:代理活着但链路坏掉时,curl 常常拿到
# 一个 5xx(机场的错误页)或空响应,`-f` 看不出「通了但不对」。非 2xx 一律算不通。
egress_probe() {
  local proxy=$1 code
  egress_probe_enabled || return 0
  if [ -n "$EGRESS_PROBE_CMD" ]; then
    # 替换成别的探测:$1 = 代理 URL,退出码 0 表示通(自测就是这么打桩的)。
    bash -c "$EGRESS_PROBE_CMD" egress-probe "$proxy" >/dev/null 2>&1
    return $?
  fi
  code=$(curl -sS -o /dev/null -w '%{http_code}' -m "$EGRESS_PROBE_TIMEOUT" \
           -x "$proxy" "$EGRESS_PROBE_URL" 2>/dev/null)
  case "$code" in
    2[0-9][0-9]) return 0 ;;
  esac
  echo "[select] egress-probe http=${code:-000} via $proxy" >&2
  return 1
}

# 连续失败 EGRESS_FAIL_THRESHOLD 次才判这条路不可用。
#
# 为什么要次数而不是一次:2026-11-09 的实测里,宿主那条路本身就有 ~8% 的抖动,
# 单次失败就切路会让 worker 在两条路之间来回跳,比留在原地更糟。
egress_ok() {
  local proxy=$1 attempt=1
  while : ; do
    egress_probe "$proxy" && return 0
    if [ "$attempt" -ge "$EGRESS_FAIL_THRESHOLD" ]; then
      echo "[select] egress-bad:连续 ${attempt} 次探测都不通(阈值 ${EGRESS_FAIL_THRESHOLD})via $proxy" >&2
      return 1
    fi
    attempt=$((attempt + 1))
    sleep "$EGRESS_PROBE_BACKOFF"
  done
}

# 选路判定:只读 port_open / egress_probe 这两个可注入的判据,结果写进
# PROXY / PROXY_SOURCE / PROXY_WHY,并往 stderr 打一行可 grep 的 `[select] …`。
#
# 自测(scripts/test_start_superagent.sh)会 source 本文件后重定义 port_open、
# 用 EGRESS_PROBE_CMD 打桩,所以这段里除了这两个判据不要再直连网络。
select_route() {
  local mihomo_port=0 host_port=0
  port_open 127.0.0.1 "$PROXY_PORT" && mihomo_port=1
  [ -n "$HOSTIP" ] && port_open "$HOSTIP" "$FALLBACK_PORT" && host_port=1

  # 1. mihomo:端口活 **且** 出网真通。端口没在听就不探(省掉启动时的等待)。
  if [ "$mihomo_port" = 1 ] && egress_ok "$MIHOMO_PROXY"; then
    PROXY="$MIHOMO_PROXY"
    PROXY_SOURCE=mihomo
    PROXY_WHY="WSL mihomo(机场专线)"
    echo "[select] mihomo ok(端口活 + 出网通)→ $PROXY" >&2
    return 0
  fi

  # 2. 宿主兜底。这一跳仍然只看端口:它已经是最后一条可用的路,
  #    再拿会抖的探针去否掉它,只会在双断时多等十几秒然后还是用它。
  if [ "$host_port" = 1 ]; then
    PROXY="$HOST_PROXY"
    PROXY_SOURCE=host
    PROXY_WHY="宿主 Clash 兜底"
    if [ "$mihomo_port" = 1 ]; then
      echo "[select] egress-bad → fallback host(127.0.0.1:${PROXY_PORT} 在听,但经它出网不通;回退 ${HOST_PROXY})" >&2
      echo "      mihomo 活着却出不了网:journalctl -u superagent-proxy -n 50 --no-pager" >&2
    else
      echo "[select] port-dead → fallback host(WSL mihomo 127.0.0.1:${PROXY_PORT} 没在听;回退 ${HOST_PROXY})" >&2
    fi
    echo "      装/修:bash /root/src/chatapp/scripts/superagent-proxy/install.sh" >&2
    return 0
  fi

  # 3. 两条都不通。仍然把 mihomo 的地址设进去:代理可能是刚重启还没 listen,
  # 而 worker 是长驻进程,等它起来就通了,不需要再重启一次 DSH。
  PROXY="$MIHOMO_PROXY"
  PROXY_SOURCE=none
  PROXY_WHY="无可用代理(已按 mihomo 地址预置)"
  if [ "$mihomo_port" = 1 ]; then
    echo "[select] egress-bad → no fallback(127.0.0.1:${PROXY_PORT} 在听但出网不通,宿主 ${HOST_PROXY} 也没在听)" >&2
  else
    echo "[select] port-dead → no fallback(127.0.0.1:${PROXY_PORT} 与 ${HOST_PROXY} 都没在听)" >&2
  fi
  echo "      worker 的外网操作(git/npm/pub/GitHub 轮询)会全部失败。" >&2
  echo "      修:bash /root/src/chatapp/scripts/superagent-proxy/install.sh" >&2
  return 0
}

main() {
  select_route

  export http_proxy="$PROXY"
  export https_proxy="$PROXY"
  export HTTP_PROXY="$PROXY"
  export HTTPS_PROXY="$PROXY"
  # no_proxy 里的每一项都有理由,别随手删:
  #   localhost/127.0.0.1/::1 —— 本地服务(含 8788 模型兜底代理)不该绕出去
  #   wb.shiliu153.me         —— 模型网关在国内,送进机场等于绕出国再绕回来
  #   172.26.x.x(HOSTIP)     —— 宿主网关本身
  export no_proxy="localhost,127.0.0.1,::1,${HOSTIP:-172.26.240.1},wb.shiliu153.me,.local"
  export NO_PROXY="$no_proxy"

  export PATH="/usr/local/bin:$HOME/.local/bin:$PATH"
  cd /root/dsh-superagent || exit 1

  # ---------- 启动前的体检(只提示,不改退出码) ----------
  case "${1:-}" in
    start|restart|status)
      echo "出口代理:$PROXY_WHY → $PROXY" >&2

      # 模型兜底代理(8788)与网络代理是两件事:它挡在 DSH 与 wb 网关之间,
      # 挂了 profile 里的 baseURL 就是个死地址,而健康位看不出来
      # (models: ready 指的是重试状态,不是连通性)。
      if ! curl -fsS -m 2 "http://127.0.0.1:8788/__failover/health" >/dev/null 2>&1; then
        echo "warn: 兜底代理 superagent-failover 没响应(127.0.0.1:8788),superagent 的模型调用会全挂" >&2
        echo "      修:systemctl restart superagent-failover;装:bash /root/src/chatapp/scripts/superagent-failover/install.sh" >&2
      fi

      # 出网体检:选路时已经探过一次(端口活才探),这里对**最终选中的**那条再报一行,
      # 让 `status` 的输出里永远有一句「现在这条到底通不通」—— 这是「出网失败要能被
      # 看见」的下限,因为 DSH 的健康位只反映进程状态,出网 0% 时它们全是 ready。
      if ! egress_probe_enabled; then
        echo "出网探针:已关闭(EGRESS_PROBE=off),只看端口" >&2
      elif egress_probe "$PROXY"; then
        echo "出网探针:经 $PROXY 访问 ${EGRESS_PROBE_URL} 通" >&2
      else
        echo "warn: 出网探针失败(经 $PROXY 访问 ${EGRESS_PROBE_URL})。" >&2
        echo "      先跑 probe.sh 看三路对比,别急着改选路逻辑。" >&2
      fi
      ;;
  esac

  exec python3 scripts/dsh-superagent "$@"
}

# 被 source(自测)时只定义函数,不选路、不 export、不 exec。
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  main "$@"
fi
