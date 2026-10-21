FROM ubuntu:24.04 AS build
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake ninja-build pkg-config \
    libboost-all-dev nlohmann-json3-dev libssl-dev \
    libmysqlclient-dev libhiredis-dev \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY . .
RUN cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DIM_BUILD_TESTS=OFF \
 && cmake --build build

FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    libboost-system-dev libssl3 libmysqlclient-dev libhiredis-dev \
    ca-certificates \
 && rm -rf /var/lib/apt/lists/*
COPY --from=build /src/build/imserver /usr/local/bin/imserver
COPY --from=build /src/migrations /usr/local/share/imserver/migrations
ENTRYPOINT ["/usr/local/bin/imserver"]
