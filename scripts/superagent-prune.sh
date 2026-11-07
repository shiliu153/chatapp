#!/usr/bin/env bash
# 列出 / 清理 dsh-superagent 的工单 worktree。默认只列,`--apply` 才动手。
#
# 只清「干净(无未提交改动)且分支已合并进 origin/master」的 worktree;
# 其余只报告不动。清理完顺带删 refs/dsh-superagent/* 这些抓取用的临时引用。
set -euo pipefail
CLONE=${CLONE:-/root/src/chatapp}
WORKROOT=${WORKROOT:-/root/.dsh/state/superagent/work}
# 判「已合并」失败时的兜底:问 GitHub「这个 head 分支有没有已合并的 PR」。
# 默认用 agent 身份(本机已登录),可用 GH_CLI 覆盖;置空字符串可关掉网络兜底。
GH_CLI=${GH_CLI-/root/.local/bin/gh-agent}
APPLY=0
[ "${1:-}" = "--apply" ] && APPLY=1

git -C "$CLONE" fetch --no-tags origin master
BASE=$(git -C "$CLONE" rev-parse origin/master)

# 仓库 slug(owner/repo),从 origin URL 里抠出来
repo_slug() {
  git -C "$CLONE" remote get-url origin 2>/dev/null \
    | sed -e 's#^git@github.com:##' -e 's#^https://github.com/##' -e 's#\.git$##'
}

# 问 GitHub:该 head 分支是否存在已合并的 PR。打印 yes/no,任何异常都打印 no。
# 为什么需要它:见下面 while 循环里的注释 —— patch-id 只对「单提交分支」有效。
merged_by_pr() {
  local br=$1 slug n
  [ -n "${GH_CLI:-}" ] || { echo no; return 0; }
  [ -x "$GH_CLI" ] || command -v "$GH_CLI" >/dev/null 2>&1 || { echo no; return 0; }
  slug=$(repo_slug)
  case $slug in */*) ;; *) echo no; return 0 ;; esac
  n=$(timeout 30 "$GH_CLI" pr list --repo "$slug" --head "$br" --state merged \
        --json number --jq 'length' 2>/dev/null || true)
  case $n in ''|0|*[!0-9]*) echo no ;; *) echo yes ;; esac
}

git -C "$CLONE" worktree list --porcelain | awk '/^worktree /{print $2}' | while read -r wt; do
  [ "$wt" = "$CLONE" ] && continue
  case $wt in "$WORKROOT"/*) ;; *) continue ;; esac
  br=$(git -C "$wt" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')
  dirty=$(git -C "$wt" status --porcelain 2>/dev/null | wc -l)
  # 判断「已并入 master」不能用 `merge-base --is-ancestor`:本仓库一律 squash 合并,
  # 分支 tip 永远不是 master 的祖先,那样判会恒为「未合并」。
  # 用 `git cherry`(按 patch-id)只能认**单提交**分支:squash 出来的那条 master 提交
  # 与「分支唯一提交」patch 相同,能判 yes;但一个工单若有 N 个提交(改完一轮 CI 再修),
  # squash 后 master 上是一条合并 patch,cherry 会把 N 个提交全报成 `+` → 误判 merged=no。
  # 所以 patch-id 判不出来时,再问一次 GitHub(PR 是否已合并),两者任一成立即视为已合并。
  merged=no
  if git -C "$CLONE" rev-parse -q --verify "refs/heads/$br" >/dev/null 2>&1; then
    if [ -z "$(git -C "$CLONE" cherry "$BASE" "$br" 2>/dev/null | grep '^+' || true)" ]; then
      merged=yes
    elif [ "$(merged_by_pr "$br")" = yes ]; then
      merged=yes-pr
    fi
  fi
  printf '%-62s branch=%-46s dirty=%s merged=%s\n' "$wt" "$br" "$dirty" "$merged"
  if [ "$APPLY" = 1 ] && [ "$dirty" = 0 ] && [ "${merged#yes}" != "$merged" ]; then
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
