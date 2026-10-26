#!/usr/bin/env bash
set -euo pipefail
export IM_MEDIA_PREFIX="${IM_MEDIA_PREFIX:-http://cdn/media/chat/}"
cmake -S /src -B /src/build -G Ninja -DCMAKE_BUILD_TYPE=Debug
cmake --build /src/build
ctest --test-dir /src/build -L unit --output-on-failure
