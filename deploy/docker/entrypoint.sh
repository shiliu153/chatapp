#!/bin/sh
# 应用容器入口:先收集静态文件,再把命令交给 CMD / docker compose run。
#
# 为什么在入口做 collectstatic:
#   - staticfiles 是 web 与 nginx 共享的 named volume,必须由应用镜像写入;
#   - migrate / shell 等一次性命令也走同一入口,保证 nginx 不会读到半套静态文件。
# Celery worker 不需要静态文件,跳过以免与 web 并发写同一个 volume。
set -eu

case "${1:-}" in
    gunicorn|python)
        python manage.py collectstatic --noinput >/dev/null
        ;;
esac

exec "$@"
