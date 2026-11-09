#!/bin/bash
# 刷新机场订阅并热重载 mihomo(不重启进程,不断已在跑的连接)。
#
# 为什么不能「每天无脑重启服务」:mihomo 重启会掐掉所有活跃连接,
# 而 worker 可能正在 git fetch / npm ci / pub get。订阅更新大多数时候
# 内容根本没变,所以这里先渲染到临时文件、比对内容,变了才重载。
#
# 用法:
#   bash refresh.sh            # 正常刷新
#   bash refresh.sh --dry-run  # 只渲染并报告差异,不落盘不重载
#
# 退出码:0 = 正常(含「无变化」);1 = 拉订阅/渲染失败(旧配置保留,服务不动)
set -uo pipefail

DIR=${DIR:-/root/.dsh/proxy}
SERVICE=superagent-proxy
CTRL_PORT=${CTRL_PORT:-9091}
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
DRY_RUN=0
[ "${1:-}" = "--dry-run" ] && DRY_RUN=1

say() { echo "[refresh] $*"; }

HOSTIP=$(ip route show default | awk '{print $3}' | head -1)
HOST_PROXY=""
if [ -n "$HOSTIP" ] && timeout 2 bash -c "echo > /dev/tcp/$HOSTIP/7897" 2>/dev/null; then
  HOST_PROXY="http://$HOSTIP:7897"
fi

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

if ! python3 "$SCRIPT_DIR/render-config.py" \
  --url-file "$DIR/subscription.url" \
  --out "$TMP/config.yaml" \
  --override "$SCRIPT_DIR/override.yaml" \
  --secret-file "$DIR/controller.secret" \
  ${HOST_PROXY:+--host-proxy "$HOST_PROXY"}; then
  say "渲染失败 —— 保留现有配置,服务不动"
  exit 1
fi

if [ ! -s "$DIR/config.yaml" ]; then
  say "现有配置不存在,直接落盘"
  CHANGED=1
elif cmp -s "$TMP/config.yaml" "$DIR/config.yaml"; then
  say "订阅内容无变化,不重载"
  CHANGED=0
else
  say "订阅内容有变化:"
  # 机场每次拉订阅都会给一套不同的端口(端口池随机分配,多个端口并存),
  # 所以「全文 diff」永远有 100+ 行端口差异,人会直接无视它。
  # 这里只报真正需要人关心的两件事:节点增减、端口轮换规模。
  python3 - "$DIR/config.yaml" "$TMP/config.yaml" <<'PY' | sed 's/^/    /'
import sys, yaml
old = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
new = yaml.safe_load(open(sys.argv[2], encoding="utf-8"))
o = {p["name"]: (p.get("server"), p.get("port")) for p in old["proxies"]}
n = {p["name"]: (p.get("server"), p.get("port")) for p in new["proxies"]}
added, removed = sorted(set(n) - set(o)), sorted(set(o) - set(n))
moved = [k for k in o if k in n and o[k] != n[k]]
og = {g["name"] for g in old["proxy-groups"]}
ng = {g["name"] for g in new["proxy-groups"]}
print(f"节点:{len(o)} -> {len(n)}(新增 {len(added)},移除 {len(removed)})")
for k in added[:5]:
    print(f"  + {k}")
for k in removed[:5]:
    print(f"  - {k}")
print(f"端口/地址变化:{len(moved)} 个节点(机场端口池轮换,属正常)")
if og != ng:
    print(f"分组变化:新增 {sorted(ng - og)},移除 {sorted(og - ng)}")
PY
  CHANGED=1
fi

if [ "$DRY_RUN" = 1 ]; then
  say "--dry-run:不落盘。变更=$CHANGED"
  exit 0
fi

[ "$CHANGED" = 1 ] || exit 0

# 落盘前先留一份,出问题能立刻回退。
[ -s "$DIR/config.yaml" ] && cp -a "$DIR/config.yaml" "$DIR/config.yaml.bak"
install -m 600 "$TMP/config.yaml" "$DIR/config.yaml"

SECRET=$(cat "$DIR/controller.secret" 2>/dev/null || true)
reload() {
  curl -fsS -m 10 -X PUT \
    -H "Authorization: Bearer ${SECRET}" \
    -H "Content-Type: application/json" \
    -d "{\"path\": \"$DIR/config.yaml\", \"force\": true}" \
    "http://127.0.0.1:${CTRL_PORT}/configs" >/dev/null 2>&1
}

if reload; then
  say "已热重载(连接未断)"
else
  say "热重载失败,退回重启服务"
  systemctl restart "$SERVICE"
  sleep 2
  systemctl is-active --quiet "$SERVICE" || {
    say "服务起不来 —— 回退到备份配置"
    [ -s "$DIR/config.yaml.bak" ] && cp -a "$DIR/config.yaml.bak" "$DIR/config.yaml"
    systemctl restart "$SERVICE"
    exit 1
  }
fi

say "完成"
