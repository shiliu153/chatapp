#!/usr/bin/env bash
set -euo pipefail
export IM_MEDIA_PREFIX="${IM_MEDIA_PREFIX:-http://cdn/media/chat/}"
cmake -S /src -B /src/build -G Ninja -DCMAKE_BUILD_TYPE=Debug
cmake --build /src/build
/src/build/imserver --migrate
export IM_TEST_MYSQL_DSN="$IM_MYSQL_DSN"
export IM_TEST_REDIS_URL="$IM_REDIS_URL"
ctest --test-dir /src/build -L db --output-on-failure
