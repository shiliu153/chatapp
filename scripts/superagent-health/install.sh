#!/usr/bin/env bash
# 把巡检装成 systemd timer。装到 /root/.dsh/healthcheck/(仓库外的运行时目录),
# 于是在哪个 worktree 里跑 install 都不影响正在跑的那份;升级时重跑一次即可。
#
#   bash scripts/superagent-health/install.sh            # 安装 + 立刻跑一轮
#   bash scripts/superagent-health/install.sh --no-run   # 只装不跑
#   bash scripts/superagent-health/install.sh --uninstall
set -uo pipefail

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
TARGET=/root/.dsh/healthcheck
UNIT_DIR=/etc/systemd/system
ENV_FILE=/root/.dsh/superagent-health.env
ENV_TMPL="$HERE/superagent-health.env.example"

if [ "${1:-}" = "--uninstall" ]; then
  systemctl disable --now superagent-health.timer 2>/dev/null
  rm -f "$UNIT_DIR/superagent-health.service" "$UNIT_DIR/superagent-health.timer"
  systemctl daemon-reload
  echo "已卸载 systemd 单元(运行目录 $TARGET 保留)"
  exit 0
fi

[ "$(id -u)" = "0" ] || { echo "需要 root(写 /etc/systemd/system)" >&2; exit 1; }

mkdir -p "$TARGET"
cp -a "$HERE/../superagent_health.py" "$TARGET/"
cp -a "$HERE/notify.sh" "$HERE/run.sh" "$TARGET/"
chmod +x "$TARGET/notify.sh" "$TARGET/run.sh"

cp -a "$HERE/superagent-health.service" "$HERE/superagent-health.timer" "$UNIT_DIR/"

if [ ! -f "$ENV_FILE" ] && [ -f "$ENV_TMPL" ]; then
  cp -a "$ENV_TMPL" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  echo "已生成 $ENV_FILE(告警通道默认没配,见里面的注释)"
fi

systemctl daemon-reload
systemctl enable --now superagent-health.timer

echo
systemctl list-timers superagent-health.timer --no-pager || true
echo
if [ "${1:-}" != "--no-run" ]; then
  echo "=== 立刻跑一轮 ==="
  bash "$TARGET/run.sh"
  echo "rc=$?"
fi
