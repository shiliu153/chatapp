# 后端运行镜像:Django + gunicorn + Celery 共用
#
# 构建上下文是仓库根目录(见 deploy/docker-compose.yml.tmpl),因此只能 COPY
# 仓库内路径。依赖装 requirements.lock(精确版本),不装 requirements.txt 的区间。
# 钉 Debian 12(bookworm):比 floating slim(trixie)更稳,镜像站也一定有
FROM python:3.15-slim-bookworm

# 国内服务器默认走阿里云 PyPI / Debian 镜像;可用 --build-arg 覆盖
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ARG APT_MIRROR=mirrors.aliyun.com

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 把 Debian 官方源换到镜像站;APT_MIRROR 置空可保持官方源
RUN if [ -n "${APT_MIRROR}" ]; then \
        find /etc/apt -maxdepth 2 -type f \( -name '*.list' -o -name '*.sources' \) \
            -exec sed -i "s|deb.debian.org|${APT_MIRROR}|g; s|security.debian.org|${APT_MIRROR}|g" {} + ; \
    fi

# ffmpeg/ffprobe:聊天语音转码与时长校验(缺了 /im/voices 返回 503)
# curl:compose healthcheck
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY chatapp/requirements.txt chatapp/requirements.lock ./
RUN pip install -i "${PIP_INDEX_URL}" -r requirements.lock

COPY chatapp/ /app/
COPY deploy/docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 755 /usr/local/bin/entrypoint.sh

# M-5:非 root 运行。容器被 RCE 后拿不到挂载卷的写权限,也读不到别的进程环境。
# 三个目录要预先建好并 chown:Docker 初始化命名卷时会继承镜像里的属主。
RUN groupadd --gid 10001 app \
 && useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app \
 && mkdir -p /app/media /app/staticfiles /app/logs \
 && chown -R app:app /app
USER app

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "-b", "0.0.0.0:8000", "-w", "2", "--timeout", "120", "--access-logfile", "-"]
