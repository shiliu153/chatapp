#!/usr/bin/env bash
# superagent-closeout.sh 的自测:全部用本地临时 git 仓库,不碰网络、不碰真实母体。
# 防的是「收尾脚本自己错了却报绿」——尤其是「fetch 失败」与「落后」这两条最容易混淆的分支。
set -uo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
S="$ROOT/scripts/superagent-closeout.sh"
fail=0
OUT=''
RC=0

say() { printf '%s\n' "$*"; }

# run_closeout [args...] —— 记录 OUT 与 RC
run_closeout() {
  OUT=$(bash "$S" "$@" 2>&1)
  RC=$?
}

# 断言:名字 / 期望退出码 / 期望出现在输出里的字符串(可空)
assert() {
  local desc=$1 want=$2 needle=${3:-}
  local ok=1
  [ "$RC" = "$want" ] || ok=0
  if [ -n "$needle" ]; then
    case $OUT in *"$needle"*) ;; *) ok=0 ;; esac
  fi
  if [ "$ok" = 1 ]; then
    say "ok   $desc"
  else
    say "FAIL $desc(期望退出 $want${needle:+,输出含「$needle」};实际退出 $RC)"
    printf '%s\n' "$OUT" | sed 's/^/     | /'
    fail=1
  fi
}

setup() {
  T=$(mktemp -d)
  git init -q --bare -b master "$T/origin.git"
  git clone -q "$T/origin.git" "$T/seed" 2>/dev/null   # 空仓库克隆会打 warning,是预期
  git -C "$T/seed" config user.email t@t
  git -C "$T/seed" config user.name t
  printf 'one\n' >"$T/seed/a.txt"
  git -C "$T/seed" add -A
  git -C "$T/seed" commit -qm c1
  git -C "$T/seed" push -q origin master
  git clone -q "$T/origin.git" "$T/mother"
  git clone -q "$T/origin.git" "$T/win"
  mkdir -p "$T/work"
  export CLONE="$T/mother" WINREPO="$T/win" WORKROOT="$T/work"
  # 代理探测用 1 端口:立即拒绝,免得自测在 /dev/tcp 上等 2 秒。
  export https_proxy='' http_proxy='' PROXY_PORT=1 FETCH_TIMEOUT=10
}

upstream_commit() { # upstream_commit <文件内容>
  printf '%s\n' "$1" >"$T/seed/b.txt"
  git -C "$T/seed" add -A
  git -C "$T/seed" commit -qm "$1"
  git -C "$T/seed" push -q origin master
}

sha() { git -C "$1" rev-parse --short HEAD; }

setup

# ── A:一切最新
run_closeout
assert "已是最新时退出 0" 0 "pulled=0"
assert "已是最新时 same=yes" 0 "same=yes"

# ── B:上游有新提交 → 快进
upstream_commit two
run_closeout
assert "落后时自动快进" 0 "pulled=1"
if [ "$(sha "$T/mother")" = "$(git -C "$T/mother" rev-parse --short origin/master)" ]; then
  say "ok   快进后母体 == origin/master"
else
  say "FAIL 快进后母体 != origin/master"; fail=1
fi

# ── C:--check 只报告不动手
upstream_commit three
run_closeout --check
before=$(sha "$T/mother")
assert "--check 不动母体" 0 "pulled=0"
if [ "$before" = "$(sha "$T/mother")" ]; then say "ok   --check 后母体 HEAD 未变"; else say "FAIL --check 却改动了母体"; fail=1; fi

# ── D:母体有本地提交 → 拒绝(非快进)
git -C "$T/mother" config user.email t@t
git -C "$T/mother" config user.name t
printf 'local\n' >"$T/mother/local.txt"
git -C "$T/mother" add -A && git -C "$T/mother" commit -qm '本地提交'
upstream_commit four
run_closeout
assert "母体有本地提交时退出 2" 2 "不是快进"

# ── E:母体脏 → 拒绝
setup
upstream_commit five
printf 'dirty\n' >>"$T/mother/a.txt"
run_closeout
assert "母体脏时退出 2" 2 "未提交改动"

# ── F:Windows 仓库落后 → 报告出来(但不改它)
setup
upstream_commit six
run_closeout
assert "Windows 落后时提示 pull" 0 "Windows 仓库"

# ── G:用法错误 / --apply 与默认一致
run_closeout --nonsense
assert "未知选项退出 1" 1

upstream_commit seven
run_closeout --apply
assert "--apply 与默认行为一致(会同步)" 0 "pulled=1"

# ── H:fetch 不通、但本地记录的 origin/master 更新 → 仍然纯本地快进
# 旧实现这一步走 `git pull`,它内部会再 fetch 一次,于是网络不通就 die、收尾停在进行到一半;
# 现在只 `git merge --ff-only origin/master`(上面已 fetch 过),不发第二次网络请求。
setup
upstream_commit eight
git -C "$T/mother" fetch -q origin master                          # 本地 ref origin/master 前进到 eight
behind=$(sha "$T/mother")                                          # 母体本身还停在 setup 那条
git -C "$T/mother" remote set-url origin "$T/does-not-exist.git"   # 之后 fetch 必失败
run_closeout
assert "fetch 不通+本地 ref 更新 → 仍然同步" 0 "pulled=1"
assert "fetch 失败时如实打警告" 0 "退回本地记录的 origin/master"
if [ "$(sha "$T/mother")" = "$(git -C "$T/mother" rev-parse --short origin/master)" ] \
   && [ "$(sha "$T/mother")" != "$behind" ]; then
  say "ok   母体已纯本地快进到本地记录的 origin/master"
else
  say "FAIL 母体没快进到本地记录的 origin/master"; fail=1
fi
assert "fetch 失败时在同步提示里说明依据" 0 "依据本地记录的 origin/master"

[ "$fail" = 0 ] && say "全部通过" || say "有失败"
exit "$fail"
