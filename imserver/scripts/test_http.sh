#!/usr/bin/env bash
set -euo pipefail
export IM_MEDIA_PREFIX="${IM_MEDIA_PREFIX:-http://cdn/media/chat/}"
cmake -S /src -B /src/build -G Ninja -DCMAKE_BUILD_TYPE=Debug
cmake --build /src/build
export IM_LISTEN_WS="127.0.0.1:19100"
export IM_LISTEN_HTTP="127.0.0.1:19101"
/src/build/imserver --migrate
/src/build/imserver &
PID=$!
trap 'kill $PID' EXIT
for i in $(seq 1 30); do
  (echo > /dev/tcp/127.0.0.1/19100) >/dev/null 2>&1 && break
  sleep 0.2
done
export IM_TEST_HTTP="http://127.0.0.1:19101/im/api"
python3 /src/tests/integration/test_history.py
python3 /src/tests/integration/test_internal.py
python3 /src/tests/integration/test_image.py
export IM_BASE_WS="ws://127.0.0.1:19100/im/ws"
export IM_BASE_HTTP="http://127.0.0.1:19101/im/api"
python3 /repo/tools/im_e2e.py
