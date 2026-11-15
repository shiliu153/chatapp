#!/bin/bash
# 刷新机场订阅并热重载 mihomo(不重启进程,不断已在跑的连接)。
#
# 为什么不能「每天无脑重启服务」:mihomo 重启会掐掉所有活跃连接,
# 而 worker 可能正在 git fetch / npm ci / pub get。订阅更新大多数时候
# 内容根本没变,所以这里先渲染到临时文件、比对内容,变了才重载。
#
# 除了刷订阅,它还负责**对齐主出口组**(pin_main_group):select 组会记住
# 「上次被手动选中的那个」,优先级高于配置里的 proxies[0] —— 于是精心配好的
# url-test / fallback 组可能根本不在出口链路上(2026-11-15 实测踩到)。
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

SECRET=$(cat "$DIR/controller.secret" 2>/dev/null || true)

reload() {
  curl -fsS -m 10 -X PUT \
    -H "Authorization: Bearer ${SECRET}" \
    -H "Content-Type: application/json" \
    -d "{\"path\": \"$DIR/config.yaml\", \"force\": true}" \
    "http://127.0.0.1:${CTRL_PORT}/configs" >/dev/null 2>&1
}

# 把主 select 组对齐到配置里的首位成员(github-fallback)。
#
# 为什么要这一步(2026-11-15 实测):select 组会记住「上次被选中的那个」,而且优先级
# 高于配置里的 proxies[0]。于是「节点选择」被钉在某个**具体节点**上时,我们配的
# github(url-test)与 github-fallback(fallback)两个组根本不在出口链路上,健康检查
# 全成了摆设 —— 现场看着一切正常,但那条路再没有自动换节点的能力。
# 这一步幂等:已经对齐就什么都不发;失败只警告,不影响刷新本身(断电重启后
# override.yaml 里的 profile.store-selected=false 会让它自然回到首位成员)。
MAIN_GROUP=${MAIN_GROUP:-节点选择}
pin_main_group() {
  [ -n "$SECRET" ] || return 0
  command -v python3 >/dev/null 2>&1 || return 0
  local want now enc
  want=$(python3 - "$DIR/config.yaml" "$MAIN_GROUP" <<'PY'
import sys, yaml
cfg = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
for group in cfg.get("proxy-groups") or []:
    if group.get("name") == sys.argv[2]:
        members = group.get("proxies") or []
        print(members[0] if members else "")
        break
PY
)
  [ -n "$want" ] || return 0
  enc=$(python3 -c 'import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1],safe=""))' "$MAIN_GROUP")
  now=$(curl -s -m 5 -H "Authorization: Bearer $SECRET" \
    "http://127.0.0.1:${CTRL_PORT}/proxies/$enc" \
    | python3 -c 'import json,sys;print(json.load(sys.stdin).get("now") or "")' 2>/dev/null)
  if [ "$now" = "$want" ]; then
    say "主组「$MAIN_GROUP」已指向 $want,不用动"
    return 0
  fi
  if curl -s -m 5 -X PUT -H "Authorization: Bearer $SECRET" \
       -H "Content-Type: application/json" -d "{\"name\": \"$want\"}" \
       "http://127.0.0.1:${CTRL_PORT}/proxies/$enc" >/dev/null 2>&1; then
    say "主组「$MAIN_GROUP」:$now -> $want(之前被运行时记忆钉在单个节点上)"
  else
    say "警告:主组「$MAIN_GROUP」对齐到 $want 失败(现在指向 $now)—— 出口没有健康检查"
  fi
}

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

# 配置没变也要对齐主组:人可能在面板上手动选过节点,而那种「选了就再没人管」
# 的单节点出口正是要消灭的东西(pin_main_group 幂等,已对齐时不发任何请求)。
if [ "$CHANGED" != 1 ]; then
  pin_main_group
  exit 0
fi

# 落盘前先留一份,出问题能立刻回退。
[ -s "$DIR/config.yaml" ] && cp -a "$DIR/config.yaml" "$DIR/config.yaml.bak"
install -m 600 "$TMP/config.yaml" "$DIR/config.yaml"

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

pin_main_group

say "完成"
