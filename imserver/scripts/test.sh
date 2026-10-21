#!/usr/bin/env bash
set -euo pipefail
cmake -S /src -B /src/build -G Ninja -DCMAKE_BUILD_TYPE=Debug
cmake --build /src/build
ctest --test-dir /src/build -L unit --output-on-failure
