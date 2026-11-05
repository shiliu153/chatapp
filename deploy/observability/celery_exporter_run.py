"""celery-exporter 的启动入口(用 PyPI 包而不是官方镜像,原因见 systemd 单元与文档)。

为什么不用 Docker 镜像:`danihodovic/celery-exporter` 不在国内镜像站的白名单里
(daocloud 直接拒),直连 Docker Hub 在这台机器上只有 ~18KB/s,一次拉取要一个多小时。
PyPI 走阿里云镜像秒级装完,而 celery-exporter 本身就是个 Flask + waitress 的进程。

装法(见 docs/ops/observability.md §2.2):
    python3.11 -m venv /opt/celery-exporter-venv
    /opt/celery-exporter-venv/bin/pip install prometheus-exporter-celery "redis>=6.1.0" packaging

两个依赖坑:
    1. 包依赖 Redis<6,但 celery 5.6 的 kombu 要求 redis-py>=6.1,否则启动即
       ``VersionMismatch: Redis transport requires redis-py versions 6.1.0 or later``
       —— 安装时强制 6.1+,那条 ``<6`` 的元数据只是没跟上;
    2. 少了 ``packaging`` 会在 import kombu 时报 ``ModuleNotFoundError``(它没写进依赖)。
"""

from src.cli import cli

if __name__ == "__main__":
    cli()
