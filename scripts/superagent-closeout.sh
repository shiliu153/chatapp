#!/usr/bin/env bash
# 合并后收尾:把本机同步到 origin/master,再清工单 worktree。
#
# 解决两个已实测的坑(见 docs/superpowers/plans/2026-11-07-superagent-dev-workflow.md §6/§8):
#   1. WSL 母体 /root/src/chatapp **不会**自动跟随 origin/master,而 superagent-prune.sh 就住在母体里
#      —— 不同步就用旧脚本,把 squash 合并判成 merged=no,worktree 清不掉。
#   2. 人跑 `wsl -e bash -c` 的 shell **不继承** worker 的代理,直连 github:443 会卡约 130 秒后失败。
#
# 顺序固定:fetch → 判母体 → pull --ff-only → prune → 报 Windows 侧状态。
# 用法见 usage()。退出码:0 正常(含「已是最新」);1 用法错误;2 状态异常(有本地提交/脏工作区/拉不动)。
set -uo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CLONE=${CLONE:-/root/src/chatapp}
WINREPO=${WINREPO:-/mnt/d/pycharmproject/chat_app}
WORKROOT=${WORKROOT:-/root/.dsh/state/superagent/work}
MODE=apply
QUIET=0
FETCH_TIMEOUT=${FETCH_TIMEOUT:-60}
PROXY_PORT=${PROXY_PORT:-7897}

usage() {
  cat <<'EOF'
用法: scripts/superagent-closeout.sh [选项]

把 WSL 母体同步到 origin/master,再清工单 worktree,并报告 Windows 仓库是否跟上。

选项:
  --apply       真的同步 + 清 worktree(默认就是这个;写出来和 superagent-prune.sh 的习惯对齐)
  --check       只报告,不 pull、不 prune
  --quiet       只在「有动作 / 有异常」时说话(给定时任务用)
  -h, --help    本帮助

环境变量:
  CLONE         母体克隆路径,默认 /root/src/chatapp
  WINREPO       Windows 仓库路径(只读检查),默认 /mnt/d/pycharmproject/chat_app
  WORKROOT      工单 worktree 根目录,默认 /root/.dsh/state/superagent/work
  FETCH_TIMEOUT fetch 超时秒数,默认 60
  PROXY_PORT    宿主代理端口,默认 7897

退出码:
  0  正常(已是最新 / 已同步 / prune 无可清)
  1  用法错误
  2  状态异常:母体脏、有本地提交(非快进)、或落后但拉不下来
EOF
}

note() { [ "$QUIET" = 1 ] || printf '%s\n' "$*"; }
warn() { printf '警告: %s\n' "$*" >&2; }
die()  { printf '错误: %s\n' "$*" >&2; exit 2; }

# 人的 shell 没有 worker 那套代理;网关通就自己导一份。
ensure_proxy() {
  if [ -n "${https_proxy:-}" ] || [ -n "${HTTPS_PROXY:-}" ]; then
    note "沿用已存在的代理:${https_proxy:-${HTTPS_PROXY:-}}"
    return 0
  fi
  local gw
  gw=$(ip route show default 2>/dev/null | awk '{print $3; exit}')
  [ -n "${gw:-}" ] || return 0
  if timeout 2 bash -c "exec 3<>/dev/tcp/${gw}/${PROXY_PORT}" 2>/dev/null; then
    export https_proxy="http://${gw}:${PROXY_PORT}" http_proxy="http://${gw}:${PROXY_PORT}"
    note "已自动导出代理 ${https_proxy}(宿主网关 ${gw}:${PROXY_PORT} 可连)"
  else
    warn "宿主网关 ${gw}:${PROXY_PORT} 连不上,按直连处理"
  fi
}

# 只读地取 Windows 仓库状态:--no-optional-locks 防止刷新 index 时与 Windows 侧抢锁。
win_state() {
  [ -d "$WINREPO/.git" ] || { WIN_SHA='-'; WIN_BRANCH='-'; WIN_BEHIND=0; return 0; }
  WIN_BRANCH=$(git --no-optional-locks -C "$WINREPO" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')
  WIN_SHA=$(git --no-optional-locks -C "$WINREPO" rev-parse --short HEAD 2>/dev/null || echo '?')
  if git --no-optional-locks -C "$WINREPO" cat-file -e "${REMOTE_SHA}^{commit}" 2>/dev/null; then
    WIN_BEHIND=$(git --no-optional-locks -C "$WINREPO" rev-list --count "HEAD..${REMOTE_SHA}" 2>/dev/null || echo 0)
  else
    WIN_BEHIND=0
  fi
}

main() {
  while [ $# -gt 0 ]; do
    case $1 in
      --apply) MODE=apply ;;
      --check) MODE=check ;;
      --quiet) QUIET=1 ;;
      -h|--help) usage; exit 0 ;;
      *) usage >&2; exit 1 ;;
    esac
    shift
  done

  [ -d "$CLONE/.git" ] || die "母体不是 git 仓库:$CLONE"

  ensure_proxy

  FETCH_ERR=''
  if ! FETCH_ERR=$(timeout "$FETCH_TIMEOUT" git -C "$CLONE" fetch --no-tags origin master 2>&1); then
    # fetch 失败不等于失败:**已是最新**也是合法结果。只有当「没得比对」或「落后又拉不动」才算异常。
    REMOTE_SHA=$(git -C "$CLONE" rev-parse --short origin/master 2>/dev/null || echo '')
    [ -n "$REMOTE_SHA" ] || die "fetch 失败,且本地没有 origin/master 可比对:${FETCH_ERR}"
    warn "fetch 失败,退回本地记录的 origin/master(${REMOTE_SHA})判定 —— 它可能不是最新:${FETCH_ERR}"
  fi

  MOTHER_SHA=$(git -C "$CLONE" rev-parse --short HEAD)
  REMOTE_SHA=$(git -C "$CLONE" rev-parse --short origin/master)
  win_state

  PULLED=0
  if [ "$MOTHER_SHA" = "$REMOTE_SHA" ]; then
    note "母体已最新:$MOTHER_SHA"
  elif [ "$MODE" = check ]; then
    note "母体落后 origin/master:$MOTHER_SHA → $REMOTE_SHA(--check,不动)"
  else
    [ -z "$(git -C "$CLONE" status --porcelain)" ] || die "母体有未提交改动,先人工处理:$CLONE"
    git -C "$CLONE" merge-base --is-ancestor HEAD origin/master \
      || die "母体有本地提交,不是快进(HEAD=$MOTHER_SHA,origin/master=$REMOTE_SHA);不自动处理"
    # 这里**不用 `git pull`**:它内部会再 fetch 一次,于是刚被上面容错掉的网络抖动会在这一步变成
    # die —— 收尾就停在进行到一半(决定要同步之后、prune 之前)。上面已经 fetch 过,
    # 这里只做纯本地快进,不发任何网络请求:网络问题只影响 fetch 那一步,而它有容错。
    git -C "$CLONE" merge --ff-only --quiet origin/master \
      || die "快进到 origin/master 失败(HEAD=$MOTHER_SHA,origin/master=$REMOTE_SHA);不自动处理"
    MOTHER_SHA=$(git -C "$CLONE" rev-parse --short HEAD)
    PULLED=1
    if [ -n "$FETCH_ERR" ]; then
      note "母体已同步:$MOTHER_SHA(依据本地记录的 origin/master;本次 fetch 失败,可能不是 GitHub 最新)"
    else
      note "母体已同步:$MOTHER_SHA"
    fi
  fi

  PRUNE=skipped
  if [ "$MODE" = apply ]; then
    if CLONE="$CLONE" WORKROOT="$WORKROOT" bash "$ROOT/scripts/superagent-prune.sh" --apply >/tmp/closeout-prune.$$ 2>&1; then
      PRUNE=$(grep -c '已清理' /tmp/closeout-prune.$$ || true)
      [ "${PRUNE:-0}" -gt 0 ] && note "prune:清理了 ${PRUNE} 个 worktree"
      PRUNE="ok(${PRUNE:-0})"
    else
      # prune 只在「确实有工单 worktree」时才 fetch(issue #108 修好后:没活就直接 exit 0,不联网);
      # 走到这里说明有活但 fetch 不通、或判定/清理出错 —— 网络抖动不该让「收尾」报红。
      PRUNE='warn'
      warn "prune 未成功(有活时多为 fetch 不通 → 退出码 2,一个 worktree 都没删;见 issue #108),详见 /tmp/closeout-prune.$$"
    fi
    rm -f /tmp/closeout-prune.$$
  fi

  SAME_WIN='no'
  [ "$WIN_SHA" = "$MOTHER_SHA" ] && SAME_WIN='yes'
  if [ "$SAME_WIN" = no ] && [ "$WIN_SHA" != '-' ]; then
    note "Windows 仓库(${WIN_BRANCH})在 ${WIN_SHA},落后母体 ${MOTHER_SHA} → 在 Windows 侧跑一次 git pull --ff-only"
  fi

  printf 'CLOSEOUT ok mother=%s windows=%s same=%s pulled=%s prune=%s mode=%s\n' \
    "$MOTHER_SHA" "$WIN_SHA" "$SAME_WIN" "$PULLED" "$PRUNE" "$MODE"
}

main "$@"
