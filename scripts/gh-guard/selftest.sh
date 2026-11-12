#!/bin/sh
# gh-guard 的自测:用一个假「真 gh」验证拦截与放行,不需要网络、不需要登录。
set -u

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
GUARD="$ROOT/scripts/gh-guard/gh"
fail=0

FAKE=$(mktemp)
printf '#!/bin/sh\necho "REALGH $*"\n' >"$FAKE"
chmod +x "$FAKE"
export GH_REAL_BIN="$FAKE"
export GH_GUARD_LOG=$(mktemp)

# check <描述> <期望退出码> -- <参数...>
check() {
  desc=$1
  want=$2
  shift 3
  out=$(sh "$GUARD" "$@" 2>&1)
  rc=$?
  if [ "$rc" = "$want" ]; then
    printf 'ok   %s\n' "$desc"
  else
    printf 'FAIL %s(期望退出 %s,实际 %s)\n' "$desc" "$want" "$rc"
    printf '%s\n' "$out" | sed 's/^/     | /'
    fail=1
  fi
}

# check_out <描述> <期望出现在输出里的字符串> -- <参数...>
check_out() {
  desc=$1
  needle=$2
  shift 3
  out=$(sh "$GUARD" "$@" 2>&1)
  case $out in
    *"$needle"*) printf 'ok   %s\n' "$desc" ;;
    *)
      printf 'FAIL %s(输出里没有「%s」)\n' "$desc" "$needle"
      printf '%s\n' "$out" | sed 's/^/     | /'
      fail=1
      ;;
  esac
}

# ── 必须拒绝
check "拒 pr merge" 2 -- pr merge 113 --squash
check "拒 release create" 2 -- release create v1.0.0 --title x
check "拒 release upload" 2 -- release upload v1.0.0 app.apk
check "拒 api 改 master 引用" 2 -- api -X DELETE repos/o/r/git/refs/heads/master
check "拒 graphql mergePullRequest" 2 -- api graphql -f 'query=mutation{mergePullRequest(input:{})}'
# 2026-11-12 补:这两条是旧版的真实绕过口(路径不含 refs/heads,旧版放行)
check "拒 api REST 合并 PR" 2 -- api -X PUT repos/o/r/pulls/113/merge -f merge_method=squash
check "拒 api REST 合并 PR(--method 写法)" 2 -- api --method PUT repos/o/r/pulls/113/merge
check "拒 api 建 Release" 2 -- api -X POST repos/o/r/releases -f tag_name=v1
check "拒 api 改 Release" 2 -- api -X PATCH repos/o/r/releases/1 -f name=x
check "拒 api 删 Release" 2 -- api -X DELETE repos/o/r/releases/1

# ── 必须放行(否则 worker 干不了活)
check_out "放行 pr create" "REALGH pr create" -- pr create --title t --body b
check_out "放行 pr view" "REALGH pr view 113 --json state" -- pr view 113 --json state
check_out "放行 pr checks" "REALGH pr checks 113" -- pr checks 113
check_out "放行 auth git-credential" "REALGH auth git-credential" -- auth git-credential get
check_out "放行 release list(只读)" "REALGH release list" -- release list
check_out "放行 api 只读" "REALGH api user" -- api user
# 只读端点不能被误拦:worker 要能看 PR 与 Release
check_out "放行 api 只读 PR" "REALGH api repos/o/r/pulls/113" -- api repos/o/r/pulls/113
check_out "放行 api 只读 Release" "REALGH api repos/o/r/releases/tags/v1" -- api repos/o/r/releases/tags/v1
check_out "放行 api 评论 issue" "REALGH api -X POST repos/o/r/issues/1/comments" -- api -X POST repos/o/r/issues/1/comments
# 2026-11-13(L4):开单/评论/重开走的是 issue 写入,不是 PR —— 必须放行,否则
# worker 连「按 L4 工单回报进度」都做不到;L4 的开单本身由 Actions 里的
# l4-intake.yml 用 GITHUB_TOKEN 执行,不经这里的 shim。
check_out "放行 issue create" "REALGH issue create" -- issue create --title t --body b
check_out "放行 issue comment" "REALGH issue comment 1" -- issue comment 1 --body b
check_out "放行 issue reopen" "REALGH issue reopen 1" -- issue reopen 1
check_out "放行 --version" "REALGH --version" -- --version

# 记账:被拒的动作要落一行日志
if grep -q 'DENY' "$GH_GUARD_LOG"; then
  printf 'ok   拒绝动作已记账(%s)\n' "$GH_GUARD_LOG"
else
  printf 'FAIL 拒绝动作没有记账\n'
  fail=1
fi

rm -f "$FAKE" "$GH_GUARD_LOG"
[ "$fail" = 0 ] && echo "全部通过" || echo "有失败"
exit "$fail"
