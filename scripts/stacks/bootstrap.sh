#!/usr/bin/env bash
# 建后端 venv 并装锁定依赖(首次或依赖变更后跑一次)。本地专用 —— CI 由 setup-python 装。
set -euo pipefail
. "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"

run "创建 venv($VENV)" python3 -m venv "$VENV"
run "升级 pip" "$VENV/bin/pip" install --upgrade pip
# 装**锁定文件**(与 CI 的 backend.yml、生产镜像的 Dockerfile 三处一致):
# 装 requirements.txt 的区间会让本地依赖组合与 CI / 生产不同。
run "安装后端依赖(锁定文件,与 CI / 生产镜像一致)" \
  "$VENV/bin/pip" install -r "$ROOT/chatapp/requirements.lock"
run "自检" "$PY" -c "import django, pymysql; print('django', django.get_version())"
