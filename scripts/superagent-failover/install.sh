#!/bin/sh
# 把 scripts/superagent-failover/proxy.mjs 装成 WSL 里的 systemd 服务 superagent-failover,
# 装完自检。幂等:再跑一次就是升级(覆盖拷贝 + 重启服务)。
#
# 为什么不是 start-superagent.sh 起它:代理的生死和 DSH 的生死是两件事 ——
# 代理崩了要自己回来,DSH 重启也不该顺手把关掉的代理再拉起来。systemd 正好管这个。
#
# 卸载:systemctl disable --now superagent-failover && rm -f /etc/systemd/system/superagent-failover.service \
#       && rm -rf /usr/local/lib/superagent-failover && systemctl daemon-reload
# 之后把 /root/.dsh/profiles/superagent/cordis.patch.yml 的 baseURL 改回 https://wb.shiliu153.me/v1,
# 否则 DSH 会指着一个不存在的代理。
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
SRC="$ROOT/scripts/superagent-failover/proxy.mjs"
DEST_DIR=/usr/local/lib/superagent-failover
UNIT=/etc/systemd/system/superagent-failover.service
NODE=${NODE:-/usr/local/bin/node}
LISTEN=${FAILOVER_LISTEN:-127.0.0.1:8788}
UPSTREAM=${FAILOVER_UPSTREAM:-https://wb.shiliu153.me}
MODELS=${FAILOVER_MODELS:-cn:deepseek-v4.1-flash,global:deepseek-v4.1-flash,global:deepseek-v4.1-flash-sg}

[ -f "$SRC" ] || { echo "找不到 $SRC" >&2; exit 1; }
[ -x "$NODE" ] || { echo "找不到 node:$NODE" >&2; exit 1; }

install -d "$DEST_DIR"
install -m 0644 "$SRC" "$DEST_DIR/proxy.mjs"
echo "已安装:$DEST_DIR/proxy.mjs"

cat > "$UNIT" <<EOF
[Unit]
Description=superagent model failover proxy (cn -> global -> sg)
# 只是转发到远端网关,不需要任何密钥:Authorization 由 DSH 自己带上、原样透传。
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
Environment=FAILOVER_LISTEN=$LISTEN
Environment=FAILOVER_UPSTREAM=$UPSTREAM
Environment=FAILOVER_MODELS=$MODELS
ExecStart=$NODE $DEST_DIR/proxy.mjs
Restart=always
RestartSec=3
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
echo "已写入:$UNIT"

systemctl daemon-reload
systemctl enable superagent-failover >/dev/null
systemctl restart superagent-failover
sleep 1

PORT=${LISTEN##*:}
echo "--- 自检 1:health ---"
curl -fsS -m 5 "http://127.0.0.1:$PORT/__failover/health" && echo

echo "--- 自检 2:status ---"
curl -fsS -m 5 "http://127.0.0.1:$PORT/__failover/status" | head -20

echo "--- 自检 3:是不是真的在 listen ---"
ss -lnt | grep -F ":$PORT " || { echo "!! 端口 $PORT 没有监听" >&2; exit 1; }

echo "完成。日志:journalctl -u superagent-failover -n 50 --no-pager"
echo "别忘了把 DSH profile 的 baseURL 指到 http://127.0.0.1:$PORT/v1(见 docs/ops/superagent.md §1)。"
