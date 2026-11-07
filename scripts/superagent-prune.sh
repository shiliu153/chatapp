#!/usr/bin/env bash
# 列出 / 清理 dsh-superagent 的工单 worktree。默认只列,`--apply` 才动手。
#
# 只清「干净(无未提交改动)且分支已合并进 origin/master」的 worktree;
# 其余只报告不动。清理完顺带删 refs/dsh-superagent/* 这些抓取用的临时引用。
set -euo pipefail
CLONE=${CLONE:-/root/src/chatapp}
WORKROOT=${WORKROOT:-/root/.dsh/state/superagent/work}
APPLY=0
[ "${1:-}" = "--apply" ] && APPLY=1

git -C "$CLONE" fetch --no-tags origin master
BASE=$(git -C "$CLONE" rev-parse origin/master)

git -C "$CLONE" worktree list --porcelain | awk '/^worktree /{print $2}' | while read -r wt; do
  [ "$wt" = "$CLONE" ] && continue
  case $wt in "$WORKROOT"/*) ;; *) continue ;; esac
  br=$(git -C "$wt" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')
  dirty=$(git -C "$wt" status --porcelain 2>/dev/null | wc -l)
  merged=no
  if git -C "$CLONE" merge-base --is-ancestor "$br" "$BASE" 2>/dev/null; then
    merged=yes
  fi
  printf '%-62s branch=%-46s dirty=%s merged=%s\n' "$wt" "$br" "$dirty" "$merged"
  if [ "$APPLY" = 1 ] && [ "$dirty" = 0 ] && [ "$merged" = yes ]; then
    git -C "$CLONE" worktree remove --force "$wt"
    git -C "$CLONE" branch -D "$br" >/dev/null 2>&1 || true
    echo "  已清理"
  fi
done

if [ "$APPLY" = 1 ]; then
  git -C "$CLONE" worktree prune
  git -C "$CLONE" for-each-ref --format='%(refname)' 'refs/dsh-superagent/*' | while read -r ref; do
    git -C "$CLONE" update-ref -d "$ref"
    echo "删除 $ref"
  done
fi
