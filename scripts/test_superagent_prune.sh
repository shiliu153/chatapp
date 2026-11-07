#!/usr/bin/env bash
# superagent-prune.sh 的自测:纯本地临时仓库,不碰真实母体。
#
# 重点防的是「多提交分支被 squash 合并后判成 merged=no」——
# 那是 2026-11-07 首次碰到的真故障(L3 工单有 4 个提交,prune 清不掉 worktree)。
set -uo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
P="$ROOT/scripts/superagent-prune.sh"
fail=0
OUT=''
RC=0

say() { printf '%s\n' "$*"; }
run() { OUT=$(bash "$P" "$@" 2>&1); RC=$?; }
assert() { # assert <描述> <期望退出码> <输出里应该出现>
  local desc=$1 want=$2 needle=${3:-} ok=1
  [ "$RC" = "$want" ] || ok=0
  [ -z "$needle" ] || case $OUT in *"$needle"*) ;; *) ok=0 ;; esac
  if [ "$ok" = 1 ]; then say "ok   $desc"; else
    say "FAIL $desc(期望 $want /「$needle」,实际 $RC)"
    printf '%s\n' "$OUT" | sed 's/^/     | /'
    fail=1
  fi
}

setup() {
  T=$(mktemp -d)
  git init -q --bare -b master "$T/origin.git"
  git clone -q "$T/origin.git" "$T/seed" 2>/dev/null
  git -C "$T/seed" config user.email t@t
  git -C "$T/seed" config user.name t
  printf 'base\n' >"$T/seed/a.txt"
  git -C "$T/seed" add -A && git -C "$T/seed" commit -qm base
  git -C "$T/seed" push -q origin master
  git clone -q "$T/origin.git" "$T/clone" 2>/dev/null
  mkdir -p "$T/work"
  # 注意:bash 里「VAR=x 函数调用」的赋值在函数返回后仍然生效,
  # 所以每个用例都必须显式重置 GH_CLI,否则兜底会串到下一个用例。
  export CLONE="$T/clone" WORKROOT="$T/work" GH_CLI=''
}

# 在 worktree 里造 n 个提交,并打印 worktree 路径
make_worktree() { # make_worktree <分支名> <提交数>
  local br=$1 n=$2 wt="$T/work/$1" i
  git -C "$T/clone" worktree add -q -b "$br" "$wt" master
  git -C "$wt" config user.email t@t
  git -C "$wt" config user.name t
  i=1
  while [ "$i" -le "$n" ]; do
    printf '%s\n' "$br-$i" >"$wt/f$i.txt"
    git -C "$wt" add -A && git -C "$wt" commit -qm "$br-$i"
    i=$((i + 1))
  done
  printf '%s\n' "$wt"
}

# 把分支「squash 成一条」合进 master(等价于本仓库的合并方式)
merge_squashed() { # merge_squashed <分支名>
  git -C "$T/clone" merge -q --squash "$1" >/dev/null
  git -C "$T/clone" -c user.email=t@t -c user.name=t commit -qm "squash $1"
  git -C "$T/clone" push -q origin master
}

# ── A:未合并的分支 → 不动
setup
make_worktree agent/unmerged 1 >/dev/null
run --apply
assert "未合并 → 保留" 0 "merged=no"

# ── B:单提交分支 + squash 合并 → 靠 patch-id 认出来
setup
make_worktree agent/single 1 >/dev/null
merge_squashed agent/single
run --apply
assert "单提交 + squash → patch-id 判已合并并清理" 0 "已清理"

# ── C:多提交分支 + squash 合并 + 无网络兜底 → 只能报 merged=no(已知限制)
setup
make_worktree agent/multi 3 >/dev/null
merge_squashed agent/multi
run --apply
assert "多提交 + squash(无兜底)→ 保守保留" 0 "merged=no"

# ── D:同样的多提交分支,但有 GitHub 兜底(假 gh 说已合并)→ 清理
setup
wt=$(make_worktree agent/multi2 3)
merge_squashed agent/multi2
FAKE=$(mktemp)
printf '#!/bin/sh\necho 1\n' >"$FAKE"
chmod +x "$FAKE"
export GH_CLI="$FAKE"
run --apply
assert "多提交 + squash + PR 兜底 → 清理" 0 "merged=yes-pr"
assert "多提交 + 兜底 → 真的清掉了 worktree" 0 "已清理"
if [ -d "$wt" ]; then say "FAIL worktree 目录还在:$wt"; fail=1; else say "ok   worktree 目录已删除"; fi
export GH_CLI=''

# ── E:脏 worktree 一律不动(即使已合并)
setup
wt=$(make_worktree agent/dirty 1)
merge_squashed agent/dirty
printf 'x\n' >"$wt/untracked.txt"
run --apply
assert "脏 → 只报告不清理" 0 "dirty=1"
if [ -d "$wt" ]; then say "ok   脏 worktree 保留"; else say "FAIL 脏 worktree 被删了"; fail=1; fi

[ "$fail" = 0 ] && say "全部通过" || say "有失败"
exit "$fail"
