#!/usr/bin/env bash
# 本地与 CI 共用的环境层:`scripts/verify.sh` 与 `scripts/stacks/*.sh` 都 source 这一份。
#
# 为什么单独一份
# --------------
# 2026-11-14 之前,`verify.sh` 手抄 CI 的 env 与命令序列,于是两边慢慢分叉
# (本地 15 条 / CI 19 条,见 docs/standards/sources-of-truth.md §4 C5)。
# 现在:环境只写在这里,门禁命令只写在 `scripts/gates.toml`,两边调同一个执行器。
#
# 约定
# ----
# - 一律用 `${VAR:-默认值}`:CI 的 workflow 已经注入自己的值(MySQL 3306 / Redis 6379),
#   这里只补本地缺省(母体检出 13306 / 16379,其余目录见下面的「槽位」一段),**不覆盖 CI**。
# - 本文件**不改调用方的 shell 选项**(不 set -e):它既被 `set -euo pipefail` 的
#   verify.sh source,也被 `set -uo pipefail` 的自测 source。
# - 变量与函数是 verify.sh / stacks 脚本之间的内部约定,不是对外接口。

ROOT=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
COMPOSE="$ROOT/docker-compose.ci.yml"

die() { printf '错误: %s\n' "$*" >&2; exit 2; }

# 依赖容器的「槽位」—— 并发跑 backend 时的防撞车规则,**派生只此一处**
# --------------------------------------------------------------------
# 症状(2026-11-14,PR #333/#334/#335):多个工单同时跑 `scripts/verify.sh backend`,
# 后结束的那个 `deps down -v` 会把别的工单正在用的库拆掉,受害者成批 setUpClass 报
# pymysql 1053 / 1049 / 1044。根因是 compose 的项目名与端口都写死:同一份
# `docker-compose.ci.yml`、项目名 `chatapp-ci`、端口 13306 / 16379。
#
# 规则(优先级从高到低,先命中先算数):
#   1. 外部显式给了 `MYSQL_PORT` / `REDIS_PORT` / `COMPOSE_PROJECT_NAME` → 一律照用
#      (CI 的 workflow 就是这么注入它自己那套 service 的);
#   2. 显式给了 `CHATAPP_CI_SLOT`(0-99)→ 用该槽位(同一个目录要临时错开时用它);
#   3. 仓库根就是母体检出(`CHATAPP_MAIN_CHECKOUT`,默认 `$HOME/src/chatapp`)→ 沿用
#      文档口径:端口 13306 / 16379、项目名 chatapp-ci(README / runbook / 踩坑手册都按这套写);
#   4. 其余任何目录(worker 的工单 worktree、临时 worktree、任意克隆)→ 按路径哈希取槽
#      0-99:MySQL 13400+槽、Redis 13500+槽、项目名 `chatapp-ci-s<槽>`;
#   5. **撞槽兜底**:规则 4 命中的槽若已被「别的 compose 项目」占着(该槽的 MySQL / Redis
#      端口有人在听,而且不是本项目自己的工作区),自动顺延到下一个「两个端口都空闲」的槽,
#      并在 stderr 打一行提示;显式 `CHATAPP_CI_SLOT=N` 撞上了则**不静默改写**,直接报错并
#      给出可用槽位建议。本项目自己的栈在跑(按 compose 的 working_dir 标签认)则照旧复用。
#      判定必须留在这里:DB_PORT / BROKER_URL / TEST_REDIS_* 都由槽位派生,挪到 deps.sh
#      改端口会变成「容器起在新槽、Django 连旧槽」。
#      例外(拆除通道,2026-11-15 补):`deps.sh down` 会在 source 本文件**之前**先
#      `export CHATAPP_CI_NO_COLLISION_GUARD=1`,整块判定跳过 —— 拆栈不需要空闲端口,
#      守卫却会把「目标槽被孤儿栈占着」当成致命错误,让那套栈永远拆不掉(实测见
#      docs/standards/dev-commands.md「拆除通道」)。跳过后的认领责任在 deps.sh 的 down 分支。
# 同一个目录每次派生出同一个结果,不同目录几乎必然不同 —— 这就是「并发互不拆台」的依据。
CHATAPP_MAIN_CHECKOUT=${CHATAPP_MAIN_CHECKOUT:-$HOME/src/chatapp}

# 按仓库根路径哈希取槽(0-99)。用 cksum 而不用 md5sum / sha1sum:cksum 是 POSIX 必备,
# 精简镜像里另外两个不一定有。
path_slot() {
  local sum
  sum=$(printf '%s' "$ROOT" | cksum)
  printf '%s' "$(( ${sum%% *} % 100 ))"
}

# ---- 撞槽判定:两个探针 + 两个纯函数 -----------------------------------
# 为什么探针要能被环境变量顶掉:scripts/test_verify.sh 要在**不碰 docker、不起容器**的
# 前提下钉住「槽被占时选下一个槽」这条规则,所以两个探针各留一个离线注入口
# (CHATAPP_CI_LISTENING_PORTS / CHATAPP_CI_OWNED_SLOTS)。生产路径不设它们就走真实探测。

# 宿主上已被占用的端口,空格分隔。两个来源取并集:
#   1. docker —— 所有容器已发布的宿主端口。**这条不能省**:本机 WSL 走 Docker Desktop 的
#      引擎,容器端口发布在 Windows 宿主上,WSL 里 `ss -ltn` 看不到(2026-11-15 实测:
#      chatapp-ci-s9 明明在跑,WSL 里 13400-13699 的监听列表是空的);
#   2. ss —— WSL 自己的原生监听(例如手起的 mysqld / redis),没有这个工具就跳过。
# 两个来源都拿不到就返回空 = 认为没人占:宁可不顺延,也不要凭空挪槽(挪错等于连到别人的库)。
listening_ports() {
  if [ -n "${CHATAPP_CI_LISTENING_PORTS+x}" ]; then printf '%s' "$CHATAPP_CI_LISTENING_PORTS"; return 0; fi
  # 收尾统一成「空格分隔」:slot_free / choose_slot 都按 ` case " $list " in *" $port "* ) `
  # 判成员,混进换行就会漏判(2026-11-15 自测当场抓到:docker 的输出是多行的)。
  {
    if command -v docker >/dev/null 2>&1; then
      docker ps --format '{{.Ports}}' 2>/dev/null |
        tr ',' '\n' | sed -n 's/^.*:\([0-9][0-9]*\)->.*$/\1/p'
    fi
    if command -v ss >/dev/null 2>&1; then
      ss -ltn 2>/dev/null | awk 'NR > 1 { p = $4; sub(/.*:/, "", p); print p }'
    fi
  } | tr '\n' ' '
}

# 端口上有没有人在应答(经 localhost 转发,能打到 **Windows 宿主** 上直接起的服务)。
# 为什么要它:docker 端口列表只列容器发布的端口,`ss` 只看 WSL 自己的监听 —— 宿主上直接装的
# MySQL / Redis 占着 13400+ 段时,前两个探针都看不见,只有真去连一下才知道(2026-11-15 补)。
# 判据故意宽松:连得上就算有人,不管是谁 —— 撞槽这件事上「宁可不猜」比「猜准了省一次」值钱。
port_answers() { # port_answers <端口>
  if [ -n "${CHATAPP_CI_PORT_ANSWERS+x}" ]; then
    case " ${CHATAPP_CI_PORT_ANSWERS} " in *" $1 "*) return 0 ;; esac
    return 1
  fi
  timeout 1 bash -c "echo > /dev/tcp/127.0.0.1/$1" 2>/dev/null
}

# 本项目(按 compose 的 working_dir 标签精确认)已经占着的槽位,空格分隔。
# 不能用容器名 / 项目名前缀判:`chatapp-ci-s9-mysql` 也以 `chatapp-ci` 开头,撞槽的另一个
# 目录起的栈同样叫 `chatapp-ci-s9` —— 只有 working_dir 能区分「谁起的」。
owned_slots() {
  if [ -n "${CHATAPP_CI_OWNED_SLOTS+x}" ]; then printf '%s' "$CHATAPP_CI_OWNED_SLOTS"; return 0; fi
  command -v docker >/dev/null 2>&1 || return 0
  docker ps --filter "label=com.docker.compose.project.working_dir=$ROOT" \
    --format '{{.Label "com.docker.compose.project"}}' 2>/dev/null |
    awk '/^chatapp-ci-s[0-9]+$/ { sub(/^chatapp-ci-s/, ""); printf "%s ", $0 }'
}

# 槽位是否空闲:该槽的 MySQL / Redis 两个宿主端口都没人在听。纯函数,只读第二个参数。
slot_free() { # slot_free <槽> <监听端口清单>
  case " $2 " in *" $((13400 + $1)) "*) return 1 ;; esac
  case " $2 " in *" $((13500 + $1)) "*) return 1 ;; esac
  return 0
}

# 从起始槽往后找第一个能用的槽(最多绕一圈 100 个):这个槽是自己的栈(复用)或两个端口都空闲
# 就算能用;一个都没有就返回 1 且不打印。纯函数 —— 顺延结果因此可离线复算。
choose_slot() { # choose_slot <起始槽> <监听端口清单> <本项目已占槽位清单>
  local i=0 slot
  while [ "$i" -lt 100 ]; do
    slot=$(( ($1 + i) % 100 ))
    case " $3 " in *" $slot "*) printf '%s' "$slot"; return 0 ;; esac
    if slot_free "$slot" "$2"; then printf '%s' "$slot"; return 0; fi
    i=$((i + 1))
  done
  return 1
}

# ---- 孤儿栈回收:本目录起过哪些槽、该拆哪些项目 ---------------------------
# 为什么需要:撞槽顺延出来的栈(比如槽 10)在「占用方消失」之后,下次派生会算回原槽 9,
# 那套 s10 就成了没人认领的孤儿 —— 白占内存与端口段。所以 `deps.sh up` 把起过的槽记下来,
# `deps.sh down` 把「记录里不是当前槽」的项目也一并拆掉;拆之前必须确认该项目的 compose
# `working_dir` 标签就是本目录 —— 别人的栈一律不碰。

# 状态文件位置:走 git 的 git-path —— 普通检出落在 `.git/` 里,worktree 落在主仓库的
# `.git/worktrees/<名>/` 里;两者都不会进版本库,也随 worktree 一起消失。不在 git 仓库里时
# 退化到 `$TMPDIR`(按仓库根路径哈希命名,同一目录仍是同一份)。
ci_slot_state_file() {
  local p
  if p=$(git -C "$ROOT" rev-parse --git-path chatapp-ci-slots 2>/dev/null) && [ -n "$p" ]; then
    case $p in /*) printf '%s' "$p" ;; *) printf '%s' "$ROOT/$p" ;; esac
    return 0
  fi
  printf '%s' "${TMPDIR:-/tmp}/chatapp-ci-slots-$(printf '%s' "$ROOT" | cksum | cut -d' ' -f1)"
}

# 记下本目录起过的槽(幂等)。写不了就静默放过:状态文件只影响「收孤儿」这一步,
# 不该因为它把起容器弄失败。
remember_slot() { # remember_slot <槽>
  local f
  [ -n "${1:-}" ] || return 0
  f=$(ci_slot_state_file)
  mkdir -p "$(dirname -- "$f")" 2>/dev/null || return 0
  if ! grep -qx "$1" "$f" 2>/dev/null; then printf '%s\n' "$1" >>"$f" 2>/dev/null || true; fi
  return 0
}

# 本目录记录过的槽(空格分隔、去重)。
remembered_slots() {
  local f
  f=$(ci_slot_state_file)
  [ -f "$f" ] || return 0
  awk 'NF && !seen[$1]++ { printf "%s ", $1 }' "$f" 2>/dev/null || true
}

# 该拆哪些 compose 项目:当前派生的那个 + 记录里其余槽。纯函数(不碰 docker),
# 于是 scripts/test_verify.sh 能离线钉住「两个槽都点名」。
projects_to_teardown() { # projects_to_teardown <当前槽,可为空> <记录过的槽位清单>
  local cur=${1:-} s
  if [ -n "$cur" ]; then printf 'chatapp-ci-s%s ' "$cur"; fi
  # shellcheck disable=SC2086  # 第二个参数是空格分隔的槽位清单,必须逐词展开
  for s in ${2:-}; do
    if [ -n "$cur" ] && [ "$s" = "$cur" ]; then continue; fi
    printf 'chatapp-ci-s%s ' "$s"
  done
}

# 某个 compose 项目是不是本目录起的(按 working_dir 标签认;`-a` 连已停止的容器一起算,
# 因为孤儿栈常常是停着但还占着卷的那一坨)。
project_owned_by_this_dir() { # project_owned_by_this_dir <compose 项目名>
  command -v docker >/dev/null 2>&1 || return 1
  docker ps -aq --filter "label=com.docker.compose.project=$1" \
    --filter "label=com.docker.compose.project.working_dir=$ROOT" 2>/dev/null | grep -q .
}

# 母体检出保持文档口径;其余目录一律派生(显式 CHATAPP_CI_SLOT 在母体里也生效)。
# 校验必须留在外面这一层:放进 `$( )` 里就只在子 shell 里退出,调用方看不见非零码。
slot=""
if [ -n "${CHATAPP_CI_SLOT:-}" ]; then
  case $CHATAPP_CI_SLOT in
    ''|*[!0-9]*) die "CHATAPP_CI_SLOT 必须是 0-99 的整数,当前是「$CHATAPP_CI_SLOT」" ;;
  esac
  slot=$((10#$CHATAPP_CI_SLOT))
  [ "$slot" -le 99 ] || die "CHATAPP_CI_SLOT 必须是 0-99 的整数,当前是「$CHATAPP_CI_SLOT」"
elif [ "$ROOT" != "$CHATAPP_MAIN_CHECKOUT" ]; then
  slot=$(path_slot)
fi
# 撞槽兜底(文件头规则 5)。只在这两种情况动手:槽位非空(派生的或显式给的),且端口没被
# 外部指定 —— CI 注入 MYSQL_PORT / REDIS_PORT / COMPOSE_PROJECT_NAME 时一律不探测。
extern_ports=""
if [ -n "${MYSQL_PORT:-}${REDIS_PORT:-}${COMPOSE_PROJECT_NAME:-}" ]; then extern_ports=1; fi

# 拆除通道的开关(文件头规则 5 的例外):置 1 表示「我只是要拆栈,别问我端口空不空」。
# 只有 scripts/stacks/deps.sh 的 down 分支会设它,且必须设在自己的 source 之前。
if [ "${CHATAPP_CI_NO_COLLISION_GUARD:-0}" = 1 ]; then guard_off=1; else guard_off=0; fi

if [ -n "$slot" ] && [ -z "$extern_ports" ] && [ "$guard_off" = 0 ]; then
  busy=$(listening_ports)
  owned=$(owned_slots)
  taken=1
  # 这个槽是自己的栈(同一目录上次没拆)→ 复用,不算被占。
  case " $owned " in *" $slot "*) taken=0 ;; esac
  # 两个端口都空闲 → 直接用;但先做一次「真连一下」的双保险:docker 与 ss 都看不见的野生服务
  # (宿主上直接装的 MySQL/Redis)在这里会被抓到。抓到就**不猜**:既不用这个槽(可能连到别人的库),
  # 也不静默顺延(会掩盖「段位里有野生服务」这件事),直接报错并给一个肯定空闲的槽位建议。
  if [ "$taken" = 1 ] && slot_free "$slot" "$busy"; then
    taken=0
    for probe_port in $((13400 + slot)) $((13500 + slot)); do
      if port_answers "$probe_port"; then
        next_slot=$(choose_slot "$slot" "$busy $((13400 + slot)) $((13500 + slot))" "$owned") || next_slot=""
        die "槽 $slot 的端口 $probe_port 有人在应答,但 docker 里没有认领它的 compose 项目(多半是宿主上直接起的 MySQL/Redis);别猜着用 —— 换一个空闲槽${next_slot:+:CHATAPP_CI_SLOT=$next_slot},或先停掉那个进程"
      fi
    done
  fi
  if [ "$taken" = 1 ]; then
    # 注意 `$( ) || 赋值`:放在子 shell 里失败只影响那一层,这里显式兜住。
    next_slot=$(choose_slot "$slot" "$busy" "$owned") || next_slot=""
    if [ -z "$next_slot" ]; then
      die "槽 $slot 的端口被别的项目占着,而且 0-99 找不到空闲槽:先 docker ps --format '{{.Names}} {{.Ports}}' 收掉不用的栈"
    fi
    if [ -n "${CHATAPP_CI_SLOT:-}" ]; then
      # 显式指定的槽不静默改写:偷偷换槽会让人以为自己的 CHATAPP_CI_SLOT 生效了。
      die "CHATAPP_CI_SLOT=$slot 的端口已被别的项目占用(MySQL $((13400 + slot)) / Redis $((13500 + slot)));换一个空闲槽:CHATAPP_CI_SLOT=$next_slot"
    fi
    printf '[env] 提示:%s 派生的槽 %s 已被别的项目占用(MySQL %s / Redis %s),顺延到槽 %s(MySQL %s / Redis %s);要指定别的槽用 CHATAPP_CI_SLOT=<0-99>\n' \
      "$ROOT" "$slot" "$((13400 + slot))" "$((13500 + slot))" \
      "$next_slot" "$((13400 + next_slot))" "$((13500 + next_slot))" >&2
    slot=$next_slot
  fi
fi

if [ -n "$slot" ]; then
  COMPOSE_PROJECT_NAME=${COMPOSE_PROJECT_NAME:-chatapp-ci-s$slot}
  MYSQL_PORT=${MYSQL_PORT:-$((13400 + slot))}
  REDIS_PORT=${REDIS_PORT:-$((13500 + slot))}
else
  COMPOSE_PROJECT_NAME=${COMPOSE_PROJECT_NAME:-chatapp-ci}
  MYSQL_PORT=${MYSQL_PORT:-13306}
  REDIS_PORT=${REDIS_PORT:-16379}
fi
export COMPOSE_PROJECT_NAME MYSQL_PORT REDIS_PORT

# 解释器:本地用专用 venv,CI 没有 venv(直接用 setup-python 的 python)。
# 显式 CHATAPP_PY 最优先;run_gates.py 也读它来决定 python 门禁用哪个解释器。
VENV=${CHATAPP_VENV:-$HOME/venvs/chatapp}
if [ -n "${CHATAPP_PY:-}" ]; then
  PY=$CHATAPP_PY
  PY_FALLBACK=0
elif [ -x "$VENV/bin/python" ]; then
  PY=$VENV/bin/python
  PY_FALLBACK=0
else
  PY=python3
  PY_FALLBACK=1
fi
export CHATAPP_PY="$PY"

# Node 版本必须与 CI 对齐(web.yml / web-e2e.yml 都用 22)。实测 Node 24 会让
# profile-store 的上传照片用例报 webidl.is.File 断言失败 —— 那是环境差异不是代码问题,
# 所以这里直接钉住并优先用 $HOME/node22(安装方式见 docs/ops/superagent.md)。
NODE_DIR=${CHATAPP_NODE_DIR:-$HOME/node22}
if [ -x "$NODE_DIR/bin/node" ]; then
  PATH="$NODE_DIR/bin:$PATH"
fi
REQUIRED_NODE_MAJOR=${CHATAPP_NODE_MAJOR:-22}

# Flutter:CI 由 subosito/flutter-action 放进 PATH;本地默认 ~/flutter,可用 FLUTTER_BIN 覆盖。
if [ -n "${FLUTTER_BIN:-}" ]; then
  PATH="$(dirname -- "$FLUTTER_BIN"):$PATH"
elif [ -x "$HOME/flutter/bin/flutter" ]; then
  PATH="$HOME/flutter/bin:$PATH"
fi
export PATH

# 与 backend.yml 的 env 对齐;端口取上面派生的槽位(母体检出 = 文档口径 13306 / 16379)。
export SECRET_KEY=${SECRET_KEY:-ci-only-not-a-real-secret}
export DEBUG=${DEBUG:-1}
export DB_NAME=${DB_NAME:-chatapp_dev}
export DB_USER=${DB_USER:-chatapp}
export DB_PASSWORD=${DB_PASSWORD:-chatapp_ci}
export DB_HOST=${DB_HOST:-127.0.0.1}
export DB_PORT=${DB_PORT:-$MYSQL_PORT}
export DB_SSL_DISABLED=${DB_SSL_DISABLED:-0}
export BROKER_URL=${BROKER_URL:-redis://127.0.0.1:$REDIS_PORT/1}
export REDIS_URL=${REDIS_URL:-redis://127.0.0.1:$REDIS_PORT/0}
# 注意:TESTING 模式下 config/settings.py 不读 REDIS_URL,而是读 TEST_REDIS_HOST/PORT
# (见 settings.py「测试隔离」一节),用独立 DB 15/14 以免碰开发数据。
#
# **必须从 REDIS_URL 解析,不能写死 16379**:CI 的 workflow 只注入 REDIS_URL(Redis 在
# 6379),从没注入 TEST_REDIS_*;写死会让 CI 的测试去连 16379 → Connection refused,
# 门禁红得莫名其妙(2026-11-14 第 4 节在 CI 上实测踩到,本地 16379 恰好是对的所以看不出来)。
test_redis=${REDIS_URL#*://}
test_redis=${test_redis%%/*}
test_redis=${test_redis##*@}
export TEST_REDIS_HOST=${TEST_REDIS_HOST:-${test_redis%%:*}}
export TEST_REDIS_PORT=${TEST_REDIS_PORT:-${test_redis##*:}}
export IM_SELF_URL=${IM_SELF_URL:-http://127.0.0.1:9101}
export IM_SELF_WS_URL=${IM_SELF_WS_URL:-ws://127.0.0.1:9100/im/ws}
export IM_SELF_HTTP_URL=${IM_SELF_HTTP_URL:-http://127.0.0.1:9101/im/api}
export IM_SELF_SECRET=${IM_SELF_SECRET:-ci-fake-secret-32-bytes-minimum}
export IM_SELF_INTERNAL_SECRET=${IM_SELF_INTERNAL_SECRET:-ci-fake-internal-32-bytes-minimum}
export SMS_DEV_MODE=${SMS_DEV_MODE:-1}
export AUTO_APPROVE=${AUTO_APPROVE:-1}

# 两个开关由 verify.sh 的参数解析设置,再 export 给子脚本(它们各自是独立进程)。
DRY_RUN=${DRY_RUN:-0}
KEEP_DEPS=${KEEP_DEPS:-0}
export DRY_RUN KEEP_DEPS

run() { # run <说明> <命令...>
  local label=$1; shift
  printf '\n=== %s ===\n' "$label"
  if [ "$DRY_RUN" = 1 ]; then printf '+ %s\n' "$*"; return 0; fi
  "$@"
}

# web / app 两条栈拒绝在 /mnt/* 上跑:那是 WSL 的 9p 挂载,读 node_modules 与 flutter
# 缓存极慢,实测 vitest 起 fork worker 会直接超时(报 "[vitest-pool] Failed to start
# forks worker … Timeout waiting for worker to respond"),看上去像用例红了其实是环境。
# 正确做法是在 Linux 文件系统上的克隆里跑(worker 的 worktree 本来就在 /root 下)。
assert_linux_fs() { # assert_linux_fs <栈名>
  case $ROOT in
    /mnt/*)
      die "$1 不能在 /mnt/ 下跑(9p 太慢,vitest/flutter 会超时)。请在 WSL 的 Linux 文件系统上的克隆里执行,例如 /root/src/chatapp 的 worktree"
      ;;
  esac
}

# 调门禁执行器。门禁清单的唯一事实来源是 scripts/gates.toml —— 这里**不写任何命令**。
# --dry-run 时把「逐条打印」交给执行器,本地 `verify.sh contract --dry-run` 与 CI 的
# 执行日志因此是同一份清单(scripts/test_verify.sh 会数条数)。
run_gates() { # run_gates <scope>
  local args=(--scope "$1")
  if [ "$DRY_RUN" = 1 ]; then
    args+=(--dry-run)
  fi
  "$PY" "$ROOT/scripts/run_gates.py" "${args[@]}"
}
