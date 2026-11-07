#!/usr/bin/env bash
# superagent-prune.sh 的自测:纯本地临时仓库,不碰真实母体。
#
# 重点防两件事:
#   1. 「多提交分支被 squash 合并后判成 merged=no」——
#      那是 2026-11-07 首次碰到的真故障(L3 工单有 4 个提交,prune 清不掉 worktree)。
#   2. issue #108 的两条行为契约:
#      a. 没有工单 worktree 可清时**不碰网络**(不 fetch)、打「无可清理」、exit 0;
#      b. 有活时 fetch 失败 → 退出码非 0 + 人话错误,且**一个 worktree 都不删**。
#      失败场景一律用「不可达 remote」造:worker 的 shell 从 start-superagent.sh 继承
#      https_proxy,拔网线/关代理造出来的失败不可确定性复现;`remote set-url` 才是确定的。
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

assert_fail() { # assert_fail <描述> <输出里应该出现>:期望退出码**非** 0
  local desc=$1 needle=${2:-} ok=1
  [ "$RC" != 0 ] || ok=0
  [ -z "$needle" ] || case $OUT in *"$needle"*) ;; *) ok=0 ;; esac
  if [ "$ok" = 1 ]; then say "ok   $desc"; else
    say "FAIL $desc(期望退出码非 0 /「$needle」,实际 $RC)"
    printf '%s\n' "$OUT" | sed 's/^/     | /'
    fail=1
  fi
}

assert_dir() { # assert_dir <描述> <路径>:目录必须还在(防误删)
  if [ -d "$2" ]; then say "ok   $1"; else say "FAIL $1(目录不见了:$2)"; fail=1; fi
}

assert_no() { # assert_no <描述> <输出里不该出现>:用来证明「这件事根本没发生」
  case $OUT in
    *"$2"*) say "FAIL $1(输出里不该出现「$2」)"; printf '%s\n' "$OUT" | sed 's/^/     | /'; fail=1 ;;
    *) say "ok   $1" ;;
  esac
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

# ── 下面是 issue #108 的两条行为契约 ────────────────────────────────────────────
# 把 origin 指到不存在的路径:fetch 必然失败,且与真实网络/proxy 无关(可确定复现)。
break_remote() { git -C "$T/clone" remote set-url origin "$T/does-not-exist.git"; }

# ── F:WORKROOT 空(没有工单 worktree)+ remote 不可达 → 不碰网络,exit 0 打「无可清理」
setup
break_remote
run
assert "空 WORKROOT + remote 不可达 → exit 0 且「无可清理」" 0 "无可清理"
assert_no "空 WORKROOT → 根本没去 fetch(输出里没有那个坏 remote)" "does-not-exist"

# ── G:同上但 --apply → 一样 exit 0(不能因为「要动手」就先去联网),且什么都不动
setup
break_remote
git -C "$T/clone" update-ref refs/dsh-superagent/fake "$(git -C "$T/clone" rev-parse master)"
run --apply
assert "空 WORKROOT + 不可达 + --apply → 仍 exit 0「无可清理」" 0 "无可清理"
assert_no "--apply 时也没去 fetch" "does-not-exist"
if git -C "$T/clone" rev-parse -q --verify refs/dsh-superagent/fake >/dev/null 2>&1; then
  say "ok   空 WORKROOT 时连本地 ref 都不动(没活就只报告)"
else
  say "FAIL 空 WORKROOT 时居然删了 refs/dsh-superagent/*"
  fail=1
fi

# ── H:WORKROOT 目录本身不存在 → 同样「无可清理」exit 0
setup
break_remote
export WORKROOT="$T/no-such-workroot"
run --apply
assert "WORKROOT 不存在 + 不可达 → exit 0「无可清理」" 0 "无可清理"
export WORKROOT="$T/work"

# ── I:WORKROOT 非空(有活)+ remote 不可达 → 非 0 + 人话错误 + 什么都不删
setup
wt=$(make_worktree agent/net-fail 1)
break_remote
run --apply
assert_fail "非空 + 不可达 → 退出码非 0 且人话错误「无法判定是否已合并」" "无法判定是否已合并"
assert_dir "非空 + 不可达 → worktree 原封不动(不误删)" "$wt"
if git -C "$T/clone" rev-parse -q --verify refs/heads/agent/net-fail >/dev/null 2>&1; then
  say "ok   非空 + 不可达 → 分支也没被删"
else
  say "FAIL 非空 + 不可达 → 分支被删了"
  fail=1
fi
assert_no "非空 + 不可达 → 没有误报「已清理」" "已清理"

# ── J:连「本地看着已合并」也不能拿过期基线去删
setup
wt=$(make_worktree agent/net-merged 1)
merge_squashed agent/net-merged
break_remote
run --apply
assert_fail "已合并 + 不可达 → 仍然非 0(不拿本地旧基线猜)" "无法判定是否已合并"
assert_dir "已合并 + 不可达 → worktree 保留" "$wt"

# ── K:网络正常 + WORKROOT 空 → 也走「无可清理」这条捷径(不是靠 fetch 失败兜住的)
setup
run --apply
assert "可达 remote + 空 WORKROOT → exit 0「无可清理」" 0 "无可清理"

# ── L:分支上 0 个提交(工单刚建 worktree)→ 判 merged=empty,绝不清理
# 2026-11-08 实测:旧版 `git cherry` 对空分支没有 `+` 行,会判 merged=yes;
# 那天 #125 的 worktree 是靠 dirty=3 才没被删,干净的空 worktree 会被直接刪掉。
setup
wt=$(make_worktree agent/fresh 0)
run --apply
assert "0 提交(刚建 worktree)→ 判 merged=empty" 0 "merged=empty"
assert_no "0 提交 → 没有误报「已清理」" "已清理"
assert_dir "0 提交 → worktree 必须留着(可能在飞)" "$wt"
if git -C "$T/clone" rev-parse -q --verify refs/heads/agent/fresh >/dev/null 2>&1; then
  say "ok   0 提交 → 分支也留着"
else
  say "FAIL 0 提交 → 分支被删了"
  fail=1
fi

# ── M:有在飞工单时不动 refs(已合并的照样清,在飞的保留,refs 全留)
setup
git -C "$T/clone" update-ref refs/dsh-superagent/flying "$(git -C "$T/clone" rev-parse master)"
wt_keep=$(make_worktree agent/inflight 1)
wt_done=$(make_worktree agent/done 1)
merge_squashed agent/done
run --apply
assert "混合场景 → 已合并的照常清理" 0 "已清理"
assert_dir "混合场景 → 在飞的 worktree 保留" "$wt_keep"
if [ -d "$wt_done" ]; then say "FAIL 已合并的 worktree 没清掉:$wt_done"; fail=1; else say "ok   已合并的 worktree 已删除"; fi
assert "有保留时 → 明确说不动 refs" 0 "本次不动 refs/dsh-superagent/*"
if git -C "$T/clone" rev-parse -q --verify refs/dsh-superagent/flying >/dev/null 2>&1; then
  say "ok   有保留时 → refs/dsh-superagent/* 原封不动"
else
  say "FAIL 有保留时居然删了 refs/dsh-superagent/*"
  fail=1
fi

# ── N:全部都能清(没有在飞工单)→ refs 照旧收掉(原有行为不能退化)
setup
git -C "$T/clone" update-ref refs/dsh-superagent/old "$(git -C "$T/clone" rev-parse master)"
make_worktree agent/allsingle 1 >/dev/null
merge_squashed agent/allsingle
run --apply
assert "全清场景 → 照常清理" 0 "已清理"
if git -C "$T/clone" rev-parse -q --verify refs/dsh-superagent/old >/dev/null 2>&1; then
  say "FAIL 全清场景下 refs/dsh-superagent/* 没被收掉"
  fail=1
else
  say "ok   全清场景 → refs/dsh-superagent/* 已收掉"
fi

[ "$fail" = 0 ] && say "全部通过" || say "有失败"
exit "$fail"
