#!/bin/sh
# 把 scripts/gh-guard/gh 装到 /usr/local/bin/gh(PATH 上位于 /usr/bin 之前),装完自检。
# 只在 WSL 里跑一次;worker 与人都走同一个 shim。
#
# 卸载:rm /usr/local/bin/gh(真 gh 在 /usr/bin/gh,不受影响)
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
SRC="$ROOT/scripts/gh-guard/gh"
DEST=${DEST:-/usr/local/bin/gh}

[ -f "$SRC" ] || { echo "找不到 $SRC" >&2; exit 1; }
[ -x /usr/bin/gh ] || { echo "真 gh 不在 /usr/bin/gh,请改 shim 里的 GH_REAL_BIN" >&2; exit 1; }

install -m 0755 "$SRC" "$DEST"
echo "已安装:$DEST"

echo "--- 自检 1:能拿到版本(放行) ---"
"$DEST" --version | head -1

echo "--- 自检 2:pr merge 被拒(应看到拒绝信息且退出 2) ---"
if "$DEST" pr merge 0 --squash >/dev/null 2>&1; then
  echo "!! 自检失败:pr merge 没被拦住" >&2
  exit 1
else
  echo "已拦截(退出码 $?)"
fi

echo "--- 自检 3:which gh 现在指向 shim ---"
command -v gh

echo "完成。真 gh 仍在 /usr/bin/gh。"
