#!/usr/bin/env bash
# 建后端 venv 并装锁定依赖 + 门禁脚本依赖(首次或依赖变更后跑一次)。本地专用 —— CI 由 setup-python 装。
set -euo pipefail
. "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"

run "创建 venv($VENV)" python3 -m venv "$VENV"
run "升级 pip" "$VENV/bin/pip" install --upgrade pip
# 装**锁定文件**(与 CI 的 backend.yml、生产镜像的 Dockerfile 三处一致):
# 装 requirements.txt 的区间会让本地依赖组合与 CI / 生产不同。
run "安装后端依赖(锁定文件,与 CI / 生产镜像一致)" \
  "$VENV/bin/pip" install -r "$ROOT/chatapp/requirements.lock"
# 门禁脚本自己的依赖(不是后端依赖,单列一份文件,理由见 scripts/requirements-gates.txt):
# C++ 注释门禁靠 tree-sitter 认函数边界,缺了它该门禁 fail-closed(退出码 2,不会算绿)。
run "安装门禁脚本依赖(tree-sitter,见 scripts/requirements-gates.txt)" \
  "$VENV/bin/pip" install -r "$ROOT/scripts/requirements-gates.txt"
run "自检" "$PY" -c "import django, pymysql, tree_sitter, tree_sitter_cpp; print('django', django.get_version())"
