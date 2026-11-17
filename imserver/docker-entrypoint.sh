#!/usr/bin/env bash
# imserver 容器入口:默认先应用数据库迁移,成功后才起服务(fail-closed)。
#
# 为什么要有这一层:迁移 009 没应用就起新镜像,搜索会走 MATCH 而索引 ft_message_body
# 不存在 —— MySQL 报 1191,接口全量 500 + 50001。此前靠「部署前记得手工
# `docker compose run --rm imserver --migrate`」这条纪律,漏跑就是「服务起来了但搜索全红」;
# 现在把纪律变成镜像行为:迁移失败 = 容器非零退出,不带病监听端口。
#
# 行为:
#   - 无参数:先 `imserver --migrate`(逐版执行、可重复),成功后 `exec imserver`;
#   - 有参数:原样透传给 imserver —— `docker compose run --rm imserver --migrate` 继续可用,
#     一次性的迁移/排查命令不会被这层再包一次迁移;
#   - IM_SKIP_MIGRATE=1:跳过迁移直接起服务(多实例同时启动时只让一个实例迁移 / 本地调试),
#     日志留一行说明,避免「以为迁移跑了」。
#
# 容器以 uid 10001(app)运行,本脚本必须对运行用户可执行可读 —— Dockerfile 里统一 chmod 755。
set -euo pipefail

IMSERVER_BIN=/usr/local/bin/imserver

# 有参数 = 调用方明确要执行某个命令,不替它做任何决定(含 --migrate)。
if [ "$#" -gt 0 ]; then
  exec "$IMSERVER_BIN" "$@"
fi

if [ "${IM_SKIP_MIGRATE:-0}" = "1" ]; then
  echo "docker-entrypoint: IM_SKIP_MIGRATE=1, skipping schema migration and starting service as-is"
else
  echo "docker-entrypoint: applying schema migrations before start (IM_SKIP_MIGRATE=1 to skip)"
  # 失败直接冒泡:set -e 让脚本以 imserver --migrate 的退出码结束,不会 exec 服务。
  "$IMSERVER_BIN" --migrate
fi

exec "$IMSERVER_BIN"
