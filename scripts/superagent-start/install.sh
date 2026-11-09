#!/bin/bash
# 把仓库版的 start-superagent.sh 部署到 /root/start-superagent.sh。
#
# 为什么要这个 install 而不是直接软链:旧脚本是无版本控制的孤儿文件,
# 直接覆盖就没人能回退。这里先备份成带时间戳的副本,再原子替换。
#
# 用法(从 Windows 侧):
#   wsl -e bash -c 'bash /root/src/chatapp/scripts/superagent-start/install.sh'
#
# 部署完必须 restart 才生效 —— worker 是长驻进程,环境变量只在启动时继承。
# 脚本不会替你 restart(那会打断在飞的工单),只把命令打出来。
set -uo pipefail

SRC=$(cd "$(dirname "$0")" && pwd)/start-superagent.sh
DEST=/root/start-superagent.sh

[ -f "$SRC" ] || { echo "错误:找不到 $SRC" >&2; exit 1; }

if [ -f "$DEST" ] && cmp -s "$SRC" "$DEST"; then
  echo "[install] $DEST 已是最新,跳过"
else
  if [ -f "$DEST" ]; then
    BAK="${DEST}.bak-$(date +%Y%m%d-%H%M%S)"
    cp -a "$DEST" "$BAK"
    echo "[install] 旧版已备份到 $BAK"
  fi
  install -m 755 "$SRC" "$DEST.tmp" && mv "$DEST.tmp" "$DEST"
  echo "[install] 已部署 $DEST"
fi

bash -n "$DEST" || { echo "错误:语法检查没过" >&2; exit 1; }
echo "[install] 语法检查通过"

cat <<'EOF'

下一步(会打断在飞的工单,自己挑时机):
  wsl -e bash /root/start-superagent.sh restart
  wsl -e bash /root/start-superagent.sh status

回退:
  ls -1 /root/start-superagent.sh.bak-*     # 找最近那份
  cp -a /root/start-superagent.sh.bak-<时间戳> /root/start-superagent.sh
EOF
