#!/bin/bash
# 启动 dsh-superagent:带模型密钥、PATH,以及出口代理。
#
# 这是 /root/start-superagent.sh 的仓库版本。它之前只存在于 WSL 的 /root 下,
# 没有版本控制 —— 也就是说「worker 为什么连不上网」这件事的关键一环不在仓库里,
# 换机器/重装就丢。现在源码在 scripts/superagent-start/,用 install.sh 部署。
#
# 出口代理的选路顺序(2026-11-09 起):
#   1. WSL 内自建 mihomo(127.0.0.1:7890)—— 默认,走机场 IEPL 专线
#   2. 宿主 Clash(网关:7897)—— 兜底,mihomo 没装/没起来时用
#   3. 都没有 —— 大声警告,但**仍然启动**(不因为网络暂时不通就把整个
#      superagent 拦下;worker 起来后照样能接单,只是外网操作会失败)
#
# 为什么不按「出网成功与否」选路,而按「代理进程活没活」选路:
# 实测(§12)宿主 Clash 对 api.github.com 的失败率 50%,比直连还差。
# 拿一个会抖的探针去决定用哪条路,只会在抖动时把 worker 切到更差的那条。
# 所以判据用「进程/端口是否活着」这种确定性信号,出网质量交给 probe.sh 去量。
#
# 用法(与旧版完全一致,从 Windows 侧):
#   wsl -e bash /root/start-superagent.sh start|status|stop|restart
set -uo pipefail

[ -f /root/.dsh/superagent.env ] && . /root/.dsh/superagent.env

PROXY_PORT=${PROXY_PORT:-7890}              # mihomo 的 mixed-port
FALLBACK_PORT=${FALLBACK_PORT:-7897}        # 宿主 Clash 的 mixed-port
HOSTIP=$(ip route show default | awk '{print $3}' | head -1)
MIHOMO_PROXY="http://127.0.0.1:${PROXY_PORT}"
HOST_PROXY="http://${HOSTIP}:${FALLBACK_PORT}"

port_open() {
  [ -n "${1:-}" ] && timeout 2 bash -c "echo > /dev/tcp/$1/$2" 2>/dev/null
}

# ---------- 选路 ----------
PROXY=""
PROXY_WHY=""
if port_open 127.0.0.1 "$PROXY_PORT"; then
  PROXY="$MIHOMO_PROXY"
  PROXY_WHY="WSL mihomo(机场专线)"
elif [ -n "$HOSTIP" ] && port_open "$HOSTIP" "$FALLBACK_PORT"; then
  PROXY="$HOST_PROXY"
  PROXY_WHY="宿主 Clash 兜底"
  echo "warn: WSL mihomo(127.0.0.1:${PROXY_PORT})没在听,回退宿主 ${HOST_PROXY}" >&2
  echo "      装/修:bash /root/src/chatapp/scripts/superagent-proxy/install.sh" >&2
else
  # 两条都不通。仍然把 mihomo 的地址设进去:代理可能是刚重启还没 listen,
  # 而 worker 是长驻进程,等它起来就通了,不需要再重启一次 DSH。
  PROXY="$MIHOMO_PROXY"
  PROXY_WHY="无可用代理(已按 mihomo 地址预置)"
  echo "warn: 没有任何代理在听(127.0.0.1:${PROXY_PORT} / ${HOST_PROXY})" >&2
  echo "      worker 的外网操作(git/npm/pub/GitHub 轮询)会全部失败。" >&2
  echo "      修:bash /root/src/chatapp/scripts/superagent-proxy/install.sh" >&2
fi

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

    # 出网探针:只报告,不参与选路(理由见文件头)。
    if curl -fsS -m 5 -x "$PROXY" -o /dev/null "https://api.github.com/rate_limit" 2>/dev/null; then
      echo "出网探针:api.github.com 通" >&2
    else
      echo "warn: 出网探针失败(经 $PROXY 访问 api.github.com)。" >&2
      echo "      先跑 probe.sh 看三路对比,别急着改选路逻辑。" >&2
    fi
    ;;
esac

exec python3 scripts/dsh-superagent "$@"
