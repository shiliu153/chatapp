#!/usr/bin/env bash
# imserver 栈:单元 / 集成 / HTTP e2e,全部在 docker 里跑(gates.toml 的 imserver 组)。
#
# 为什么三段的命令一模一样地交给注册表:此前本地只跑 test_http.sh(集成 / e2e),
# unit 与 db 两条在本地形同没跑过 —— 改了 C++ 却只有 CI 才看得见红。现在三段同源。
set -euo pipefail
. "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"

run_gates imserver
