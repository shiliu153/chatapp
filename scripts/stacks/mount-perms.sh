#!/usr/bin/env bash
# 被 compose 以 `:ro` 挂进容器、且由**容器内非 root 用户**读取的仓库文件:启动前补回 0644。
#
# 为什么需要这一层
# ----------------
# worker 的 worktree 以 `umask 077` 检出时,仓库里记作 100644 的文件会落成 0600。
# MySQL 容器初始化时读 `/docker-entrypoint-initdb.d` 下的脚本,读到 0600 直接
# `Permission denied` 并以 1 退出 —— 表象是「依赖起不来 / 后端验证报一堆 1053」,
# 实际与代码无关(2026-11-14 实测偶发,详见 docs/pitfalls/testing.md
# 「在 WSL / Linux 本地跑验证」第 5 条)。git 只记录 100644 / 100755 两种模式,
# 所以这里的 `chmod` 不会产生工作区变更,重复执行也无副作用。
#
# 本文件**不改调用方的 shell 选项**(与 scripts/stacks/env.sh 同一约定):既被
# `set -euo pipefail` 的 deps.sh source,也被 `set -uo pipefail` 的 scripts/test_verify.sh source,
# 因此这里只定义函数与数据,不执行任何动作。
#
# 适用范围与维护约定
# ------------------
# **凡是**满足「compose 以 `:ro` 挂进容器 + 容器内以非 root 用户读取」的仓库文件,都登记到
# 下面的 MOUNT_READ_FILES 里;`ensure_mount_readable` 只处理这张表。
# 刻意**不用 glob**(例如 `chatapp/*.sql`):glob 会把将来新增的文件悄悄卷进来,
# 一旦那个文件本该是 0600,就会变成没人知道为什么被改了口径的模式。

# 需要补读权限的挂载文件,路径相对仓库根。
# 当前只有 MySQL 的 init 脚本(docker-compose.ci.yml 把它挂在
# /docker-entrypoint-initdb.d/10-grant-test-db.sql:ro)。
MOUNT_READ_FILES=(
  chatapp/db_setup_ci.sql # MySQL 初始化脚本(mysql 用户读)
)

# 把 MOUNT_READ_FILES 里的每个文件补成 0644;文件不存在就跳过(否则会让整条验证误红)。
# 参数说明:
#   $1 — 仓库根,可选,缺省为本文件所在的仓库(scripts/stacks/ 的上两级)。
# 返回参数:
#   无。chmod 失败被吞掉:真有问题会在容器起不来时暴露,不该在装配阶段抢走报错位置。
ensure_mount_readable() {
  local root=${1:-$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)}
  local rel f
  for rel in "${MOUNT_READ_FILES[@]}"; do
    f="$root/$rel"
    [ -f "$f" ] || continue
    chmod 644 "$f" 2>/dev/null || true
  done
}

# 仅被 source 使用的库文件:直接执行它什么也不做,免得有人误以为它有子命令。
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  printf '这是一个被 source 的库文件(scripts/stacks/deps.sh 用),没有子命令。\n' >&2
  exit 2
fi
