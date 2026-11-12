#!/usr/bin/env bash
# 列出 / 清理 dsh-superagent 的工单 worktree。默认只列,`--apply` 才动手。
#
# 只清「干净(无未提交改动)且分支已合并进 origin/<默认分支>」的 worktree;
# 其余只报告不动。refs/dsh-superagent/* 这些抓取用的临时引用**只在「本轮一个
# worktree 都没保留」时才清**(有在飞工单时一律不碰,见下面 clean_refs 的调用点)。
#
# 与网络有关的两条行为契约(issue #108),**顺序是契约的一部分**:
#   1. 先看有没有活:`$WORKROOT` 下没有工单 worktree → 打印「无可清理」并 exit 0,
#      不 fetch、不 rev-parse BASE。人跑 `wsl -e bash -c '...'` 时起的是非登录 shell、
#      不带 https_proxy,而 worker 进程一直有代理;所以「本来就没东西可清」时去 fetch,
#      只会白卡约 130s 再抛 fatal(实测见 docs/ops/superagent.md §4 第 4 步)。
#   2. 再看网络:有活时 fetch 失败 → 退出码非 0 + 人话错误,且**一个 worktree 都不删**。
#      不能「fetch 失败就拿现有的 origin/<默认分支> 继续判」:判「已合并」的基线必须是本次
#      fetch 到的,拿过期基线判出 yes 再去删目录是危险动作。
#
# 两条 2026-11-08 补的护栏(第四轮审计当日实测踩到):
#   3. **分支上 0 个提交 → 判 merged=empty,永不清理**。`git cherry` 对空分支没有 `+` 行,
#      旧版因此判成 merged=yes;那天 #125 的 worktree 是靠 dirty=3 才没被删。
#      「刚建好 worktree、还没落文件」和「废弃的空 worktree」看起来一样,
#      判不出来时唯一安全的动作是保留(与人手 `git worktree remove` 兜底)。
#   4. **有 worktree 被保留时不清 refs**。refs/dsh-superagent/* 无法反查属于哪个工单,
#      旧版无条件全删,会把正在干活的工单的临时引用一起删掉。
set -euo pipefail

CLONE=${CLONE:-/root/src/chatapp}
WORKROOT=${WORKROOT:-/root/.dsh/state/superagent/work}
# 判「已合并」失败时的兜底:问 GitHub「这个 head 分支有没有已合并的 PR」。
# 默认用 agent 身份(本机已登录),可用 GH_CLI 覆盖;置空字符串可关掉网络兜底。
GH_CLI=${GH_CLI-/root/.local/bin/gh-agent}
APPLY=0
[ "${1:-}" = "--apply" ] && APPLY=1

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

# 删掉 refs/dsh-superagent/* 这些抓取用的临时引用。纯本地操作,不联网。
# **只在「本轮一个 worktree 都没保留」时被调用**:有在飞工单时删这些引用会伤到它。
clean_refs() {
  git -C "$CLONE" for-each-ref --format='%(refname)' 'refs/dsh-superagent/*' \
    | while IFS= read -r ref; do
        git -C "$CLONE" update-ref -d "$ref"
        echo "删除 $ref"
      done
}

# 列出「住在 $WORKROOT 下的工单 worktree」。`worktree list` 只读本地状态、不联网,
# 所以「有没有活」这一判断可以先于任何网络操作完成 —— 这正是契约 1 要的顺序。
list_worktrees() {
  git -C "$CLONE" worktree list --porcelain | while IFS= read -r line; do
    case $line in
      'worktree '*) wt=${line#worktree } ;;
      *) continue ;;
    esac
    [ "$wt" = "$CLONE" ] && continue
    case $wt in "$WORKROOT"/*) printf '%s\n' "$wt" ;; esac
  done
}

WORKTREES=$(list_worktrees)
if [ -z "$WORKTREES" ]; then
  # 只说不做:不 fetch、不 rev-parse、不删任何 ref。契约 1 的全部内容就是这一句 + exit 0。
  echo "无可清理:$WORKROOT 下没有工单 worktree(未联网,未做任何改动)"
  exit 0
fi

# 到这里才碰网络。fetch 失败就停(退出码 2 = 环境不可用):没有本次的默认分支基线,
# 就不能判「已合并」,而判不出来时唯一安全的动作是「一个都不删」。
#
# 不写死 ref 名:默认分支 2026-11-11 由 master 改名成 main,写死 `fetch origin master`
# 会变成「couldn't find remote ref master」—— 本脚本会一直 exit 2,一个目录都清不掉。
# 所以拉默认 refspec(全部 head),再从更新后的 remote-tracking ref 里认默认分支。
if ! git -C "$CLONE" fetch --no-tags origin; then
  {
    printf '%s\n' '无法 fetch,无法判定是否已合并:git fetch --no-tags origin 失败(原因见上面的 git 报错)'
    printf '%s\n' '本次不清理任何 worktree(拿过期基线判「已合并」去删目录是危险动作);请先修好网络或代理再重跑。'
  } >&2
  exit 2
fi
# 默认分支:main 优先,回退 master(改名前后都能跑)。
BASE_REF=''
for _cand in main master; do
  if git -C "$CLONE" rev-parse --verify --quiet "refs/remotes/origin/$_cand" >/dev/null 2>&1; then
    BASE_REF=$_cand
    break
  fi
done
[ -n "$BASE_REF" ] || BASE_REF=main
BASE=$(git -C "$CLONE" rev-parse "origin/$BASE_REF")

KEPT=0
# 用 herestring 而不是 `| while`:管道会让循环跑在子 shell 里,KEPT 传不出来。
while IFS= read -r wt; do
  [ -n "$wt" ] || continue
  br=$(git -C "$wt" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')
  dirty=$(git -C "$wt" status --porcelain 2>/dev/null | wc -l)
  # 分支相对本次 origin/<默认分支> 有几个「还没合并」的提交;取不到一律按 0 处理(= 保留)。
  ahead=$(git -C "$CLONE" rev-list --count "$BASE..$br" 2>/dev/null || echo 0)
  # 判断「已并入默认分支」不能用 `merge-base --is-ancestor`:本仓库一律 squash 合并,
  # 分支 tip 永远不是默认分支的祖先,那样判会恒为「未合并」。
  # 用 `git cherry`(按 patch-id)只能认**单提交**分支:squash 出来的那条默认分支提交
  # 与「分支唯一提交」patch 相同,能判 yes;但一个工单若有 N 个提交(改完一轮 CI 再修),
  # squash 后默认分支上是一条合并 patch,cherry 会把 N 个提交全报成 `+` → 误判 merged=no。
  # 所以 patch-id 判不出来时,再问一次 GitHub(PR 是否已合并),两者任一成立即视为已合并。
  merged=no
  if [ "$ahead" = 0 ]; then
    # 分支还没有任何提交 = 工单刚建 worktree / 正在写第一个文件。
    # 必须显式拦掉:空分支在 `git cherry` 下没有任何 `+` 行,旧版会判成 merged=yes,
    # 于是 `--apply` 会把一个还在干活的目录 `worktree remove --force` 掉。
    merged=empty
  elif git -C "$CLONE" rev-parse -q --verify "refs/heads/$br" >/dev/null 2>&1; then
    if [ -z "$(git -C "$CLONE" cherry "$BASE" "$br" 2>/dev/null | grep '^+' || true)" ]; then
      merged=yes
    elif [ "$(merged_by_pr "$br")" = yes ]; then
      merged=yes-pr
    fi
  fi
  printf '%-62s branch=%-46s dirty=%s ahead=%s merged=%s\n' "$wt" "$br" "$dirty" "$ahead" "$merged"
  if [ "$APPLY" = 1 ] && [ "$dirty" = 0 ] && [ "${merged#yes}" != "$merged" ]; then
    git -C "$CLONE" worktree remove --force "$wt"
    git -C "$CLONE" branch -D "$br" >/dev/null 2>&1 || true
    echo "  已清理"
  else
    KEPT=$((KEPT + 1))
  fi
done <<<"$WORKTREES"

if [ "$APPLY" = 1 ]; then
  git -C "$CLONE" worktree prune
  if [ "$KEPT" = 0 ]; then
    clean_refs
  else
    # 有在飞 / 未合并 / 有改动的工单:refs/dsh-superagent/* 无法反查归属,
    # 一刀切删会把在飞工单的临时引用一起删掉(#125 实测)。下次「全清」时再收。
    echo "保留 $KEPT 个 worktree(在飞 / 未合并 / 有改动):本次不动 refs/dsh-superagent/*"
  fi
fi
