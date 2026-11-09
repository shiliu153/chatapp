#!/usr/bin/env bash
# 本地复刻 CI 六轨的可执行入口。用法见 usage()。
#
# 设计原则:命令序列与环境变量必须与 .github/workflows/*.yml 逐项对齐,
# 但 CI 不调用本脚本——它是 CI 的镜像,不是 CI 的入口。
#
# 依赖:docker(WSL 里通过 Docker Desktop 的 WSL 集成)、后端用专用 venv(bootstrap 子命令建)、
# web 用 npm、app 用 Linux Flutter(默认 ~/flutter,可用 FLUTTER_BIN 覆盖)。
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
COMPOSE="$ROOT/docker-compose.ci.yml"
# 后端 / 契约用的解释器:专用 venv。系统 Python 上没有 Django 与 PyMySQL。
VENV=${CHATAPP_VENV:-$HOME/venvs/chatapp}
PY="$VENV/bin/python"
DRY_RUN=0
KEEP_DEPS=0

# Node 版本必须与 CI 对齐(web.yml / web-e2e.yml 都用 22)。
# 实测 Node 24 会让 web 的一条 jsdom/undici 用例失败(profile-store 的上传照片用例,
# 报 webidl.is.File 断言),那是环境差异不是代码问题——所以这里直接钉住并优先用
# $HOME/node22(安装方式见 docs/ops/superagent.md)。
NODE_DIR=${CHATAPP_NODE_DIR:-$HOME/node22}
if [ -x "$NODE_DIR/bin/node" ]; then
  PATH="$NODE_DIR/bin:$PATH"
  export PATH
fi
REQUIRED_NODE_MAJOR=${CHATAPP_NODE_MAJOR:-22}

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

# 与 backend.yml 的 env 对齐;端口用 compose 里避让后的 13306 / 16379。
export SECRET_KEY=ci-only-not-a-real-secret
export DEBUG=1
export DB_NAME=chatapp_dev
export DB_USER=chatapp
export DB_PASSWORD=chatapp_ci
export DB_HOST=127.0.0.1
export DB_PORT=13306
export DB_SSL_DISABLED=0
export BROKER_URL=redis://127.0.0.1:16379/1
export REDIS_URL=redis://127.0.0.1:16379/0
# 注意:TESTING 模式下 config/settings.py 不读 REDIS_URL,而是读 TEST_REDIS_HOST/PORT
# (见 settings.py「测试隔离」一节),用独立 DB 15/14 以免碰开发数据。这里必须一起指过来,
# 否则测试会去连 127.0.0.1:6379(Windows 上那个开发用 redis),在 WSL 里必然 Connection refused。
export TEST_REDIS_HOST=127.0.0.1
export TEST_REDIS_PORT=16379
export IM_SELF_URL=http://127.0.0.1:9101
export IM_SELF_WS_URL=ws://127.0.0.1:9100/im/ws
export IM_SELF_HTTP_URL=http://127.0.0.1:9101/im/api
export IM_SELF_SECRET=ci-fake-secret-32-bytes-minimum
export IM_SELF_INTERNAL_SECRET=ci-fake-internal-32-bytes-minimum
export SMS_DEV_MODE=1
export AUTO_APPROVE=1

usage() {
  cat <<'EOF'
用法: scripts/verify.sh [选项] <子命令> [子命令...]

子命令:
  backend    起依赖 → migrate → 后端全量测试 → OpenAPI 同改校验 → 压测脚本自测
  web        npm ci → 类型生成物同改校验 → type-check → lint → test → build
  imserver   单元 / 集成 / HTTP e2e(docker compose test)
  app        flutter analyze(零告警)+ flutter test
  contract   版本号三处一致 + App 模型字段 ⊆ OpenAPI
  all        依次跑 backend web imserver app contract
  deps       只起依赖容器
  bootstrap  建后端 venv 并装 requirements.txt(首次或依赖变更后跑一次)

选项:
  --list       列出子命令
  --dry-run    只打印将执行的命令
  --keep-deps  结束后不拆依赖容器
EOF
}

die() { printf '错误: %s\n' "$*" >&2; exit 2; }

# 校验「生成物 == HEAD 里的那一版」。
#
# 为什么不用 `git diff --exit-code`:本仓库在 Windows 上检出是 CRLF,而 WSL 里的 git
# 按 LF 理解索引,`git diff` 会把上千个文件都算成改动(实测 1094 个),这条判定在
# WSL 里等于永远红。改成「比内容、忽略行尾」:把两边的 \r 都去掉再比。
check_artifact() { # check_artifact <仓库相对路径>
  local f=$1
  if [ "$DRY_RUN" = 1 ]; then
    printf '\n=== 校验生成物与 HEAD 一致 ===\n+ %s\n' "$f"
    return 0
  fi
  if ! git -C "$ROOT" cat-file -e "HEAD:$f" 2>/dev/null; then
    die "$f 不在 HEAD 里:新增生成物请先提交,否则 CI 会对不上"
  fi
  if ! diff -q <(git -C "$ROOT" show "HEAD:$f" | tr -d '\r') <(tr -d '\r' < "$ROOT/$f") >/dev/null; then
    echo "--- $f 与 HEAD 的差异(前 40 行) ---" >&2
    diff -u <(git -C "$ROOT" show "HEAD:$f" | tr -d '\r') <(tr -d '\r' < "$ROOT/$f") 2>&1 | head -40 >&2 || true
    die "$f 与代码不一致:重新生成并提交"
  fi
  echo "生成物一致: $f"
}

run() { # run <说明> <命令...>
  local label=$1; shift
  printf '\n=== %s ===\n' "$label"
  if [ "$DRY_RUN" = 1 ]; then printf '+ %s\n' "$*"; return 0; fi
  "$@"
}

deps_up() {
  run "起依赖容器(MySQL 13306 / Redis 16379)" \
    docker compose -f "$COMPOSE" up -d --wait
}

deps_down() {
  # 注意:这里必须用 if,不能写 `[ … ] && { … }`——后者在 set -e 下,
  # 条件为假会让整条列表返回非零,直接把脚本打死。
  if [ "$KEEP_DEPS" = 1 ]; then
    echo "保留依赖容器(--keep-deps)"
    return 0
  fi
  run "拆除依赖容器" docker compose -f "$COMPOSE" down -v
}

stack_backend() {
  if [ "$DRY_RUN" = 0 ] && [ ! -x "$PY" ]; then
    die "没有可用的 venv:$PY。先跑 scripts/verify.sh bootstrap"
  fi
  cd "$ROOT/chatapp"
  run "迁移" "$PY" manage.py migrate --noinput
  run "后端全量测试" "$PY" manage.py test --noinput
  run "OpenAPI 生成物同改校验" "$PY" manage.py spectacular --file ../docs/api/openapi.yml --validate
  check_artifact docs/api/openapi.yml
  cd "$ROOT"
  run "压测脚本自测" "$PY" -m unittest perf.test_run -v
}
stack_web() {
  if [ "$DRY_RUN" = 0 ]; then
    assert_linux_fs web
    local major
    major=$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)
    if [ "$major" != "$REQUIRED_NODE_MAJOR" ]; then
      die "web 需要 Node $REQUIRED_NODE_MAJOR(与 CI 一致),当前是 $major。装好 $NODE_DIR 或设 CHATAPP_NODE_MAJOR 覆盖"
    fi
  fi
  cd "$ROOT/web"
  run "安装依赖" npm ci
  run "重新生成 API 类型" npm run gen:api
  check_artifact web/src/api/schema.d.ts
  run "类型检查" npm run type-check
  run "代码规范(零告警)" npm run lint
  run "单元/组件测试" npm run test:run
  run "构建" npm run build
  cd "$ROOT"
}

stack_contract() {
  run "版本号三处一致" "$PY" "$ROOT/scripts/sync_version.py" --check
  run "App 模型字段 ⊆ OpenAPI" "$PY" "$ROOT/scripts/check_app_models.py"
  # 两个脚本的自测:contract.yml 一直在跑它们,本地这条轨此前漏了 ——
  # 那会让「本地绿 ≈ CI 绿」在这两个门禁自己坏掉时不成立。
  run "版本号同步脚本自测" "$PY" -m unittest scripts.test_sync_version
  run "发版准备脚本自测" "$PY" -m unittest scripts.test_release_prep
}
stack_imserver() {
  # 三段与 .github/workflows/imserver.yml 的三个 step 逐项对齐:
  # 早先这里只跑 test_http.sh(集成 / e2e),unit 与 db 两条在本地形同没跑过 ——
  # 改了 C++ 却只有 CI 才看得见红,和本脚本「本地绿 ≈ CI 绿」的定位矛盾。
  run "imserver unit(AC 匹配 / config / metrics …)" \
    docker compose -f "$ROOT/imserver/docker-compose.test.yml" run --rm test bash /src/scripts/test.sh
  run "imserver db(store / message_service)" \
    docker compose -f "$ROOT/imserver/docker-compose.test.yml" run --rm test bash /src/scripts/test_integration.sh
  run "imserver 集成 / HTTP e2e" \
    docker compose -f "$ROOT/imserver/docker-compose.test.yml" run --rm test bash /src/scripts/test_http.sh
}
stack_app() {
  local flutter=${FLUTTER_BIN:-$HOME/flutter/bin/flutter}
  if [ "$DRY_RUN" = 0 ]; then
    assert_linux_fs app
    [ -x "$flutter" ] || die "找不到 Linux Flutter:$flutter(安装见 docs/ops/superagent.md)"
  fi
  cd "$ROOT/app"
  run "拉依赖" "$flutter" pub get
  run "静态检查(零告警)" "$flutter" analyze
  run "测试" "$flutter" test
  cd "$ROOT"
}

stack_bootstrap() {
  run "创建 venv($VENV)" python3 -m venv "$VENV"
  run "升级 pip" "$VENV/bin/pip" install --upgrade pip
  run "安装后端依赖" "$VENV/bin/pip" install -r "$ROOT/chatapp/requirements.txt"
  run "自检" "$PY" -c "import django, pymysql; print('django', django.get_version())"
}

main() {
  local stacks=()
  while [ $# -gt 0 ]; do
    case $1 in
      --list|--help|-h) usage; exit 0 ;;
      --dry-run) DRY_RUN=1 ;;
      --keep-deps) KEEP_DEPS=1 ;;
      backend|web|imserver|app|contract|deps|all|bootstrap) stacks+=("$1") ;;
      -*) die "未知选项 $1" ;;
      *) die "未知子命令 $1(用 --list 看清单)" ;;
    esac
    shift
  done
  if [ ${#stacks[@]} -eq 0 ]; then
    usage >&2
    exit 1
  fi

  local ran_backend=0
  for s in "${stacks[@]}"; do
    case $s in
      deps) deps_up ;;
      bootstrap) stack_bootstrap ;;
      all) deps_up; stack_backend; stack_web; stack_imserver; stack_app; stack_contract; ran_backend=1 ;;
      backend) deps_up; stack_backend; ran_backend=1 ;;
      web) stack_web ;;
      imserver) stack_imserver ;;
      app) stack_app ;;
      contract) stack_contract ;;
    esac
  done
  if [ "$ran_backend" = 1 ]; then
    deps_down
  fi
  printf '\n全部通过\n'
}

main "$@"
