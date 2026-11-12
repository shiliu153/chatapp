FROM ubuntu:25.10 AS build
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

FROM ubuntu:25.10
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    libboost-system-dev libssl3 libmysqlclient-dev libhiredis-dev \
    ca-certificates \
 && rm -rf /var/lib/apt/lists/*
COPY --from=build /src/build/imserver /usr/local/bin/imserver
COPY --from=build /src/migrations /usr/local/share/imserver/migrations
# 聊天文字敏感词表(批次 Q):随镜像走,默认路径 /usr/local/share/imserver/data/sensitive_words.txt;
# 想换成别的文件用 IM_SENSITIVE_WORDS_FILE 指过去(改词表 = 重启容器)。
COPY --from=build /src/data /usr/local/share/imserver/data
# 词表必须对运行用户可读:容器以 uid 10001 跑,而构建上下文里的 0600(本机 checkout 的
# umask 会带进来)会让读词表直接 permission denied —— 那就成了「悄悄不拦」,比红更糟。
RUN chmod -R a+rX /usr/local/share/imserver/data
# M-5:非 root 运行(监听 9100/9101 都是 >1024 的端口,不需要特权)
RUN groupadd --gid 10001 app \
 && useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app
USER app
ENTRYPOINT ["/usr/local/bin/imserver"]
