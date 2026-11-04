#!/usr/bin/env bash
# =============================================================================
# chat 服务一键从零部署(Docker Compose 全栈)
#
# 在一台全新的 Linux 服务器上完成:
#   安装 Docker → 生成密钥 → 渲染配置 → 构建镜像 → 建库/迁移 → 启动
#   Django(gunicorn)+ Celery + MySQL 8 + Redis 7 + 自建 imserver + nginx + Web 前端
#   可选:certbot 自动签发 Let's Encrypt 证书 + 每日续期
#
# 用法:
#   sudo bash deploy/oneclick.sh --domain chat.example.com --email you@example.com
#   sudo bash deploy/oneclick.sh --no-tls
#   sudo bash deploy/oneclick.sh --render-only --no-tls      # 只生成配置,不装不启动
#
# 设计原则:
#   1. 幂等:重复执行只补齐缺失项,不覆盖已有数据库与密钥;
#   2. 可预演:--render-only 不需要 root、不装 Docker、不碰端口;
#   3. 密钥只落 $APP_DIR/secrets(600),数据库/Redis 不发布宿主机端口;
#   4. 所有配置由模板渲染,重跑脚本会覆盖 $APP_DIR 下的生成物。
# =============================================================================
set -Eeuo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd -- "$SCRIPT_DIR/.." && pwd)

# --- 默认参数 ---------------------------------------------------------------
APP_DIR="/opt/chatapp"
DOMAIN=""
EMAIL=""
PUBLIC_URL=""
NO_TLS=0
STAGING=0
RENDER_ONLY=0
ROTATE_SECRETS=0
SKIP_DOCKER_INSTALL=0
ALLOW_DEV_SMS=0
NO_BUILD=0
HTTP_PORT=80
HTTPS_PORT=443
DOCKER_SUBNET="172.28.0.0/16"
# nginx 在 compose 网络里的固定地址:H-2 要求可信代理只写这一个地址,
# 而不是整个 /16(否则任何容器都能伪造 X-Real-IP)。
NGINX_IP="172.28.0.10"
# L-9:MySQL root 只允许来自 compose 子网(不是 "%")。按 /16 取前三段。
MYSQL_ROOT_HOST=$(printf '%s' "$DOCKER_SUBNET" | awk -F'[./]' '{print $1"."$2"."$3".%"}')
ADMIN_PHONE=""
ADMIN_PASSWORD=""
PIP_INDEX_URL="https://mirrors.aliyun.com/pypi/simple/"
NPM_REGISTRY="https://registry.npmmirror.com"
IMSERVER_TAR=""
DOCKER_REPO_URL="https://mirrors.aliyun.com/docker-ce/linux/centos/docker-ce.repo"

# --- 颜色与日志 -------------------------------------------------------------
if [ -t 1 ]; then
    C_RESET=$'\033[0m'; C_BLUE=$'\033[34m'; C_GREEN=$'\033[32m'
    C_YELLOW=$'\033[33m'; C_RED=$'\033[31m'
else
    C_RESET=""; C_BLUE=""; C_GREEN=""; C_YELLOW=""; C_RED=""
fi

log()  { printf '%s==>%s %s\n' "$C_BLUE" "$C_RESET" "$*"; }
ok()   { printf '%s✓%s %s\n' "$C_GREEN" "$C_RESET" "$*"; }
warn() { printf '%s!%s %s\n' "$C_YELLOW" "$C_RESET" "$*" >&2; }
die()  { printf '%s✗%s %s\n' "$C_RED" "$C_RESET" "$*" >&2; exit 1; }

on_exit() {
    local code=$?
    if [ "$code" -ne 0 ]; then
        printf "\n%s✗ 部署中断(退出码 %s),请查看上面的日志。%s\n" "$C_RED" "$code" "$C_RESET" >&2
    fi
}
trap on_exit EXIT

usage() {
    cat <<'EOF'
chat 服务一键部署(Docker Compose)

必需/常用:
  --domain <域名>            站点域名;启用 HTTPS 时必填
  --email <邮箱>             Let's Encrypt 到期通知;启用 HTTPS 时必填
  --no-tls                   只跑 HTTP(不申请证书)
  --public-url <URL>         手动指定对外地址,如 http://1.2.3.4:8080
  --app-dir <目录>           部署目录,默认 /opt/chatapp
  --http-port <端口>         宿主机 HTTP 端口,默认 80
  --https-port <端口>        宿主机 HTTPS 端口,默认 443

可选:
  --staging                  用 Let's Encrypt staging 签证书(避免触发正式限流)
  --render-only              只渲染配置,不安装 Docker、不启动容器
  --rotate-secrets           重新生成 SECRET_KEY/数据库口令/IM 密钥(会踢下线)
  --skip-docker-install      不自动安装 Docker(已装但 compose 缺失时仍会补插件)
  --no-build                 跳过镜像构建,直接用现有镜像
  --imserver-image-tar <文件> 用本地 docker save 的 imserver 镜像,避免在 2C2G 上编译
  --allow-dev-sms            允许写入 SMS_DEV_MODE=1(固定验证码 123456)
                             仅限封闭测试;公网/TLS 部署必须显式加这个开关
  --admin-phone <手机号>     运营管理员手机号(公网/TLS 部署必填)
  --admin-password <口令>    管理员口令(仅首次创建时生效)
  --pip-index-url <URL>      pip 镜像,默认阿里云
  --npm-registry <URL>       npm 镜像,默认 npmmirror
  --docker-repo-url <URL>    RHEL 系 Docker CE 仓库,默认阿里云
  -h, --help                 显示本帮助

示例:
  sudo bash deploy/oneclick.sh --domain chat.example.com --email ops@example.com
  sudo bash deploy/oneclick.sh --no-tls --public-url http://203.0.113.10
  sudo bash deploy/oneclick.sh --render-only --no-tls --app-dir ./deploy-render
EOF
}

need_value() {
    if [ $# -lt 2 ] || [ -z "$2" ]; then
        die "参数 $1 需要一个值(用 --help 查看用法)"
    fi
}

# --- 参数解析 ---------------------------------------------------------------
while [ $# -gt 0 ]; do
    case "$1" in
        --domain)            need_value "$1" "${2:-}"; DOMAIN=$2; shift 2 ;;
        --email)             need_value "$1" "${2:-}"; EMAIL=$2; shift 2 ;;
        --public-url)        need_value "$1" "${2:-}"; PUBLIC_URL=$2; shift 2 ;;
        --app-dir)           need_value "$1" "${2:-}"; APP_DIR=$2; shift 2 ;;
        --http-port)         need_value "$1" "${2:-}"; HTTP_PORT=$2; shift 2 ;;
        --https-port)        need_value "$1" "${2:-}"; HTTPS_PORT=$2; shift 2 ;;
        --admin-phone)       need_value "$1" "${2:-}"; ADMIN_PHONE=$2; shift 2 ;;
        --admin-password)    need_value "$1" "${2:-}"; ADMIN_PASSWORD=$2; shift 2 ;;
        --pip-index-url)     need_value "$1" "${2:-}"; PIP_INDEX_URL=$2; shift 2 ;;
        --npm-registry)      need_value "$1" "${2:-}"; NPM_REGISTRY=$2; shift 2 ;;
        --docker-repo-url)   need_value "$1" "${2:-}"; DOCKER_REPO_URL=$2; shift 2 ;;
        --imserver-image-tar) need_value "$1" "${2:-}"; IMSERVER_TAR=$2; shift 2 ;;
        --no-tls)            NO_TLS=1; shift ;;
        --staging)           STAGING=1; shift ;;
        --allow-dev-sms)     ALLOW_DEV_SMS=1; shift ;;
        --render-only)       RENDER_ONLY=1; shift ;;
        --rotate-secrets)    ROTATE_SECRETS=1; shift ;;
        --skip-docker-install) SKIP_DOCKER_INSTALL=1; shift ;;
        --no-build)          NO_BUILD=1; shift ;;
        -h|--help)           usage; exit 0 ;;
        *)                   die "未知参数: $1(用 --help 查看用法)" ;;
    esac
done

# 校验端口
case "$HTTP_PORT" in ''|*[!0-9]*) die "--http-port 必须是数字" ;; esac
case "$HTTPS_PORT" in ''|*[!0-9]*) die "--https-port 必须是数字" ;; esac
if [ "$HTTP_PORT" -lt 1 ] || [ "$HTTP_PORT" -gt 65535 ]; then
    die "--http-port 超出 1–65535"
fi
if [ "$HTTPS_PORT" -lt 1 ] || [ "$HTTPS_PORT" -gt 65535 ]; then
    die "--https-port 超出 1–65535"
fi

# 域名统一小写,避免证书目录/ALLOWED_HOSTS 大小写不一致
if [ -n "$DOMAIN" ]; then
    case "$DOMAIN" in
        *://*|*/*) die "--domain 只写域名,不要带协议或路径" ;;
    esac
    DOMAIN=$(printf '%s' "$DOMAIN" | tr '[:upper:]' '[:lower:]')
    # M-7:域名会原样渲染进 nginx 的 server_name,只放行合法字符,防配置注入
    case "$DOMAIN" in
        *[!a-z0-9.-]*) die "--domain 只允许字母/数字/点/连字符: $DOMAIN" ;;
        *..*|.*|*.)    die "--domain 不能包含 '..'、也不能以点开头或结尾: $DOMAIN" ;;
    esac
    [ "${#DOMAIN}" -le 253 ] || die "--domain 长度不能超过 253 个字符"
fi
if [ -n "$ADMIN_PASSWORD" ]; then
    case "$ADMIN_PASSWORD" in
        *$'\n'*) die "--admin-password 不能包含换行" ;;
    esac
fi

# render-only 默认写到当前目录,避免非 root 写 /opt 失败
if [ "$RENDER_ONLY" = 1 ] && [ "$APP_DIR" = "/opt/chatapp" ]; then
    APP_DIR="$PWD/deploy-render"
fi
case "$APP_DIR" in
    /*) ;;
    *) APP_DIR="$PWD/$APP_DIR" ;;
esac

# --- 环境与仓库检查 ---------------------------------------------------------
if [ "$RENDER_ONLY" = 0 ]; then
    [ "$(id -u)" -eq 0 ] || die "请用 root 运行:sudo bash deploy/oneclick.sh ..."
    [ "$(uname -s)" = "Linux" ] || die "只支持 Linux"
fi

for f in chatapp/manage.py web/package.json imserver/CMakeLists.txt deploy/docker-compose.yml.tmpl; do
    [ -e "$REPO_DIR/$f" ] || die "仓库不完整,缺少 $f"
done

if [ -n "$IMSERVER_TAR" ] && [ ! -f "$IMSERVER_TAR" ]; then
    die "--imserver-image-tar 文件不存在: $IMSERVER_TAR"
fi

ensure_base_tools() {
    local missing=() c
    for c in curl openssl sed awk grep; do
        command -v "$c" >/dev/null 2>&1 || missing+=("$c")
    done
    [ ${#missing[@]} -eq 0 ] && return 0
    if [ "$RENDER_ONLY" = 1 ]; then
        die "缺少命令: ${missing[*]}"
    fi
    log "安装基础工具: ${missing[*]}"
    if command -v dnf >/dev/null 2>&1; then
        dnf install -y "${missing[@]}"
    elif command -v apt-get >/dev/null 2>&1; then
        apt-get update -y && apt-get install -y "${missing[@]}"
    else
        die "缺少命令 ${missing[*]},且没有 dnf/apt-get"
    fi
}

ensure_base_tools

# --- 解析对外地址 -----------------------------------------------------------
TLS=1
[ "$NO_TLS" = 1 ] && TLS=0

detect_public_ip() {
    local ip=""
    for url in https://api.ipify.org https://ifconfig.me/ip https://ipinfo.io/ip; do
        ip=$(curl -4 -fsS --max-time 5 "$url" 2>/dev/null | tr -d '[:space:]' || true)
        if printf '%s' "$ip" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$'; then
            printf '%s\n' "$ip"
            return 0
        fi
    done
    ip=$(hostname -I 2>/dev/null | awk '{print $1}' || true)
    if [ -n "$ip" ]; then
        printf '%s\n' "$ip"
        return 0
    fi
    return 1
}

if [ "$TLS" = 1 ]; then
    [ -n "$DOMAIN" ] || die "启用 HTTPS 时必须给 --domain(或加 --no-tls)"
    [ -n "$EMAIL" ] || die "启用 HTTPS 时必须给 --email(Let's Encrypt 到期通知)"
    [ "$HTTP_PORT" = "80" ] || die "Let's Encrypt HTTP-01 需要 80 端口,请把 --http-port 设为 80"
    # Django 的 SECURE_SSL_REDIRECT 只会拼 https://<host>(不带端口),自定义 443 会跳错
    [ "$HTTPS_PORT" = "443" ] || die "HTTPS 模式固定 443;自定义端口只用于 HTTP 测试"
    PUBLIC_URL="https://$DOMAIN"
    SERVER_NAME="$DOMAIN"
else
    if [ -z "$PUBLIC_URL" ]; then
        if [ -n "$DOMAIN" ]; then
            if [ "$HTTP_PORT" = "80" ]; then
                PUBLIC_URL="http://$DOMAIN"
            else
                PUBLIC_URL="http://$DOMAIN:$HTTP_PORT"
            fi
        else
            if [ "$RENDER_ONLY" = 1 ]; then
                PUBLIC_URL="http://127.0.0.1"
            else
                ip=$(detect_public_ip) || die "无法识别公网 IP,请用 --public-url 指定"
                PUBLIC_URL="http://$ip"
            fi
        fi
    fi
    SERVER_NAME="${DOMAIN:-_}"
fi

PUBLIC_URL=${PUBLIC_URL%/}
case "$PUBLIC_URL" in
    http://*|https://*) ;;
    *) die "--public-url 必须以 http:// 或 https:// 开头: $PUBLIC_URL" ;;
esac
if [ "$TLS" = 0 ]; then
    case "$PUBLIC_URL" in
        https://*) die "--no-tls 模式下 --public-url 不能是 https://(nginx 只监听 HTTP)" ;;
    esac
fi
PUBLIC_AUTHORITY=${PUBLIC_URL#*://}
PUBLIC_AUTHORITY=${PUBLIC_AUTHORITY%%/*}
PUBLIC_HOST=${PUBLIC_AUTHORITY%%:*}
[ -n "$PUBLIC_HOST" ] || die "无法从 PUBLIC_URL 解析主机名: $PUBLIC_URL"

# --- C-1:固定验证码只允许封闭测试 ------------------------------------------
# SMS_DEV_MODE=1 时任何手机号都能用 123456 登录(含运营账号)。默认不写这个值;
# TLS 或非回环地址的部署必须由操作者显式加 --allow-dev-sms 确认「这是封闭测试」。
is_loopback_host() {
    case "$1" in
        127.*|localhost|::1|"[::1]") return 0 ;;
        *) return 1 ;;
    esac
}
PUBLIC_IS_LOOPBACK=0
is_loopback_host "$PUBLIC_HOST" && PUBLIC_IS_LOOPBACK=1

if [ "$TLS" = 1 ] || [ "$PUBLIC_IS_LOOPBACK" = 0 ]; then
    if [ "$ALLOW_DEV_SMS" != 1 ]; then
        die "拒绝生成公网配置:未加 --allow-dev-sms 时 SMS_DEV_MODE=0,
     而当前没有接真实短信商,站点将无法登录。
     如果这台机器只做封闭测试,请显式加 --allow-dev-sms 并确保不对公网开放注册;
     否则请先接短信商,再把 SMS_DEV_MODE 设为 0。"
    fi
fi
SMS_DEV_MODE=0
if [ "$ALLOW_DEV_SMS" = 1 ]; then
    SMS_DEV_MODE=1
    warn "已启用 SMS_DEV_MODE=1(固定验证码 123456):仅限封闭测试,严禁对公网开放"
fi

if [ "$TLS" = 1 ]; then
    WS_SCHEME="wss"
    CERT_DIR="/etc/letsencrypt/live/$DOMAIN"
else
    WS_SCHEME="ws"
    CERT_DIR="/etc/letsencrypt/live/$DOMAIN"
fi
if [ "$HTTPS_PORT" = "443" ]; then
    HTTPS_PORT_SUFFIX=""
else
    HTTPS_PORT_SUFFIX=":$HTTPS_PORT"
fi

ALLOWED_HOSTS="127.0.0.1,localhost,web"
add_allowed_host() {
    case ",$ALLOWED_HOSTS," in
        *",$1,"*) ;;
        *) ALLOWED_HOSTS="$ALLOWED_HOSTS,$1" ;;
    esac
}
add_allowed_host "$PUBLIC_HOST"
[ -n "$DOMAIN" ] && add_allowed_host "$DOMAIN"

# Web 版本用于 /app/config 的版本门槛(与 web/package.json 同源)
WEB_VERSION=$(sed -n 's/^[[:space:]]*"version":[[:space:]]*"\([^"]*\)".*/\1/p' "$REPO_DIR/web/package.json" | head -n1 || true)
[ -n "$WEB_VERSION" ] || WEB_VERSION="1.0.0"

# --- 目录与密钥 -------------------------------------------------------------
SECRETS_DIR="$APP_DIR/secrets"
VALUES_FILE="$SECRETS_DIR/values.env"
ADMIN_TXT="$SECRETS_DIR/admin.txt"

gen_hex() { openssl rand -hex "$1"; }

umask 077
mkdir -p "$APP_DIR"/{secrets,mysql/init,nginx/conf.d,bin,logs}
chmod 700 "$SECRETS_DIR"

# 复用已有密钥;--rotate-secrets 只轮换应用级密钥。
# 注意:root 口令必须保留 —— 它已经写进 MySQL 数据卷,换掉会锁死后续 db-init。
if [ -f "$VALUES_FILE" ]; then
    set -a
    # shellcheck disable=SC1090
    . "$VALUES_FILE"
    set +a
fi
if [ "$ROTATE_SECRETS" = 1 ]; then
    SECRET_KEY=""
    DB_PASSWORD=""
    IM_DB_PASSWORD=""
    IM_JWT_SECRET=""
    IM_INTERNAL_SECRET=""
    IM_MEDIA_SIGN_SECRET=""
fi

SECRET_KEY=${SECRET_KEY:-$(gen_hex 32)}
DB_PASSWORD=${DB_PASSWORD:-$(gen_hex 12)}
MYSQL_ROOT_PASSWORD=${MYSQL_ROOT_PASSWORD:-$(gen_hex 12)}
IM_DB_PASSWORD=${IM_DB_PASSWORD:-$(gen_hex 12)}
IM_JWT_SECRET=${IM_JWT_SECRET:-$(gen_hex 32)}
IM_INTERNAL_SECRET=${IM_INTERNAL_SECRET:-$(gen_hex 32)}
IM_MEDIA_SIGN_SECRET=${IM_MEDIA_SIGN_SECRET:-$(gen_hex 32)}

# 管理员口令:命令行 > 已保存 > 新生成
if [ -z "$ADMIN_PASSWORD" ] && [ -f "$ADMIN_TXT" ]; then
    ADMIN_PASSWORD=$(sed -n 's/^PASSWORD=//p' "$ADMIN_TXT" | head -n1 || true)
    if [ -z "$ADMIN_PHONE" ]; then
        ADMIN_PHONE=$(sed -n 's/^PHONE=//p' "$ADMIN_TXT" | head -n1 || true)
    fi
fi
if [ -z "$ADMIN_PHONE" ]; then
    if [ "$TLS" = 1 ] || [ "$PUBLIC_IS_LOOPBACK" = 0 ]; then
        die "公网/TLS 部署必须显式指定 --admin-phone(运营管理员手机号)"
    fi
    ADMIN_PHONE=13900000000
    warn "未指定 --admin-phone,使用占位手机号 13900000000(仅限本地/预览)"
fi
ADMIN_PASSWORD=${ADMIN_PASSWORD:-$(gen_hex 12)}

# 用 %q 做 shell 转义:即使 --admin-password 带空格/符号,重跑时 source 也不会被拆开
{
    printf '# 由 deploy/oneclick.sh 生成。请备份本文件;数据库 root 口令丢失后无法找回。\n'
    printf 'SECRET_KEY=%q\n' "$SECRET_KEY"
    printf 'DB_PASSWORD=%q\n' "$DB_PASSWORD"
    printf 'MYSQL_ROOT_PASSWORD=%q\n' "$MYSQL_ROOT_PASSWORD"
    printf 'IM_DB_PASSWORD=%q\n' "$IM_DB_PASSWORD"
    printf 'IM_JWT_SECRET=%q\n' "$IM_JWT_SECRET"
    printf 'IM_INTERNAL_SECRET=%q\n' "$IM_INTERNAL_SECRET"
    printf 'IM_MEDIA_SIGN_SECRET=%q\n' "$IM_MEDIA_SIGN_SECRET"
    printf 'ADMIN_PHONE=%q\n' "$ADMIN_PHONE"
    printf 'ADMIN_PASSWORD=%q\n' "$ADMIN_PASSWORD"
} > "$VALUES_FILE"
chmod 600 "$VALUES_FILE"

cat > "$ADMIN_TXT" <<EOF
PHONE=$ADMIN_PHONE
PASSWORD=$ADMIN_PASSWORD
EOF
chmod 600 "$ADMIN_TXT"

# --- 模板渲染 ---------------------------------------------------------------
render_tmpl() {
    local src=$1 dst=$2
    shift 2
    local expr="" kv key val
    for kv in "$@"; do
        key=${kv%%=*}
        val=${kv#*=}
        val=$(printf '%s' "$val" | sed -e 's/[\\&|]/\\&/g')
        expr="${expr}s|__${key}__|${val}|g;"
    done
    sed -e "$expr" "$src" > "$dst"
}

write_app_env() {
    local https_flag=$1
    local csrf=""
    [ "$TLS" = 1 ] && csrf="$PUBLIC_URL"
    cat > "$SECRETS_DIR/chatapp.env" <<EOF
# 由 deploy/oneclick.sh 生成;不要手改(重跑脚本会覆盖)
SECRET_KEY=$SECRET_KEY
DEBUG=0
ALLOWED_HOSTS=$ALLOWED_HOSTS
DB_NAME=chatapp
DB_USER=chatapp
DB_PASSWORD=$DB_PASSWORD
DB_HOST=mysql
DB_PORT=3306
DB_SSL_DISABLED=1
REDIS_URL=redis://redis:6379/0
BROKER_URL=redis://redis:6379/1

IM_SELF_URL=http://imserver:9101
IM_SELF_WS_URL=$WS_SCHEME://$PUBLIC_AUTHORITY/im/ws
IM_SELF_HTTP_URL=$PUBLIC_URL/im/api
IM_SELF_SECRET=$IM_JWT_SECRET
IM_SELF_INTERNAL_SECRET=$IM_INTERNAL_SECRET
IM_SELF_TOKEN_TTL=86400
IM_MEDIA_SIGN_SECRET=$IM_MEDIA_SIGN_SECRET
IM_MEDIA_SIGN_TTL=3600
CHAT_IMAGE_RETENTION_DAYS=30
CHAT_VOICE_RETENTION_DAYS=30

MEDIA_BASE_URL=$PUBLIC_URL
HTTPS_ENABLED=$https_flag
CSRF_TRUSTED_ORIGINS=$csrf
SECURE_HSTS_SECONDS=31536000
SECURE_HSTS_PRELOAD=0
NUM_PROXIES=1
TRUSTED_PROXY_IPS=127.0.0.1,::1,$NGINX_IP

OPS_OTP_REQUIRED=1
OPS_ALLOWED_IPS=
AUTO_APPROVE=0
SMS_DEV_MODE=$SMS_DEV_MODE

MIN_APP_VERSION=$WEB_VERSION
LATEST_APP_VERSION=$WEB_VERSION
APP_DOWNLOAD_URL=

USER_STORAGE_QUOTA_MB=200
MEDIA_DISK_WARN_MB=5000
CANDIDATE_POOL_SIZE=200
EOF
    chmod 600 "$SECRETS_DIR/chatapp.env"
}

write_imserver_env() {
    cat > "$SECRETS_DIR/imserver.env" <<EOF
# 由 deploy/oneclick.sh 生成;不要手改(重跑脚本会覆盖)
# 容器内监听 0.0.0.0 是 compose 网络内部地址;没有发布宿主机端口。
IM_LISTEN_WS=0.0.0.0:9100
IM_LISTEN_HTTP=0.0.0.0:9101
IM_ALLOW_PUBLIC_BIND=1
IM_MYSQL_DSN=mysql://imserver:$IM_DB_PASSWORD@mysql:3306/chatapp_im
IM_REDIS_URL=redis://redis:6379/2
IM_JWT_SECRET=$IM_JWT_SECRET
IM_INTERNAL_SECRET=$IM_INTERNAL_SECRET
IM_MIGRATIONS_DIR=/usr/local/share/imserver/migrations
IM_ALLOWED_ORIGINS=$PUBLIC_URL
IM_TRUSTED_PROXIES=127.0.0.1,::1,$NGINX_IP
# H-1:Django 在容器里,源地址不是回环;内部接口按「显式网段 + HMAC」放行。
# 只写 compose 子网(web/worker/migrate 都是一次性容器,IP 不固定)。
IM_INTERNAL_ALLOW=127.0.0.1,::1,$DOCKER_SUBNET
IM_MEDIA_PREFIX=$PUBLIC_URL/media/chat/
IM_MEDIA_SIGN_SECRET=$IM_MEDIA_SIGN_SECRET
IM_MEDIA_SIGN_TTL=3600
IM_SEND_PER_MINUTE=120
IM_IO_THREADS=2
IM_DB_THREADS=4
IM_DB_POOL=8
IM_DB_IDLE_PING_MS=60000
IM_MAX_CONN_PER_IP=20
IM_AUTH_RATE=1
IM_AUTH_BURST=60
IM_MAX_FRAME=8192
IM_TEXT_MAX=2000
EOF
    chmod 600 "$SECRETS_DIR/imserver.env"
}

write_mysql_init() {
    cat > "$APP_DIR/mysql/init/01-databases.sql" <<EOF
-- 由 deploy/oneclick.sh 生成;db-init 每次部署都执行,必须保持幂等。
CREATE DATABASE IF NOT EXISTS chatapp_im DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
ALTER DATABASE chatapp CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Django 业务账号(镜像 entrypoint 已建,这里对齐口令,支持 --rotate-secrets)
CREATE USER IF NOT EXISTS 'chatapp'@'%' IDENTIFIED WITH mysql_native_password BY '$DB_PASSWORD';
ALTER USER 'chatapp'@'%' IDENTIFIED WITH mysql_native_password BY '$DB_PASSWORD';
GRANT ALL PRIVILEGES ON chatapp.* TO 'chatapp'@'%';

-- 自建 IM 独立账号,只授权 chatapp_im
CREATE USER IF NOT EXISTS 'imserver'@'%' IDENTIFIED WITH mysql_native_password BY '$IM_DB_PASSWORD';
ALTER USER 'imserver'@'%' IDENTIFIED WITH mysql_native_password BY '$IM_DB_PASSWORD';
GRANT ALL PRIVILEGES ON chatapp_im.* TO 'imserver'@'%';

FLUSH PRIVILEGES;
EOF
    chmod 600 "$APP_DIR/mysql/init/01-databases.sql"
}

log "生成配置到 $APP_DIR"
render_tmpl "$SCRIPT_DIR/docker-compose.yml.tmpl" "$APP_DIR/docker-compose.yml" \
    "REPO_DIR=$REPO_DIR" \
    "APP_DIR=$APP_DIR" \
    "DOCKER_SUBNET=$DOCKER_SUBNET" \
    "NGINX_IP=$NGINX_IP" \
    "MYSQL_ROOT_HOST=$MYSQL_ROOT_HOST"
chmod 644 "$APP_DIR/docker-compose.yml"

render_tmpl "$SCRIPT_DIR/nginx/http.conf.tmpl" "$APP_DIR/nginx/http.conf" \
    "SERVER_NAME=$SERVER_NAME"
render_tmpl "$SCRIPT_DIR/nginx/https.conf.tmpl" "$APP_DIR/nginx/https.conf" \
    "SERVER_NAME=$SERVER_NAME" \
    "CERT_DIR=$CERT_DIR" \
    "HTTPS_PORT_SUFFIX=$HTTPS_PORT_SUFFIX"
chmod 644 "$APP_DIR/nginx/http.conf" "$APP_DIR/nginx/https.conf"

# 初始一律 HTTP;证书签下来后再换成 https.conf
cp "$APP_DIR/nginx/http.conf" "$APP_DIR/nginx/conf.d/default.conf"
chmod 644 "$APP_DIR/nginx/conf.d/default.conf"

write_app_env 0
write_imserver_env
write_mysql_init

cat > "$APP_DIR/.env" <<EOF
# 由 deploy/oneclick.sh 生成;供 docker compose 插值,不要手改
COMPOSE_PROJECT_NAME=chatapp
APP_DIR=$APP_DIR
REPO_DIR=$REPO_DIR
PUBLIC_URL=$PUBLIC_URL
HTTP_PORT=$HTTP_PORT
HTTPS_PORT=$HTTPS_PORT
DOCKER_SUBNET=$DOCKER_SUBNET
MYSQL_ROOT_PASSWORD=$MYSQL_ROOT_PASSWORD
DB_PASSWORD=$DB_PASSWORD
IMSERVER_TAG=local
PIP_INDEX_URL=$PIP_INDEX_URL
NPM_REGISTRY=$NPM_REGISTRY
EOF
chmod 600 "$APP_DIR/.env"

# 证书续期脚本(只在 TLS 模式安装定时器)
cat > "$APP_DIR/bin/certbot-renew.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
cd "$APP_DIR"
docker compose -f "$APP_DIR/docker-compose.yml" --project-directory "$APP_DIR" --profile tools \\
    run --rm certbot renew --webroot -w /var/www/certbot --quiet
docker compose -f "$APP_DIR/docker-compose.yml" --project-directory "$APP_DIR" \\
    exec -T nginx nginx -s reload
EOF
chmod 700 "$APP_DIR/bin/certbot-renew.sh"

# 每日维护:候选池随机键、访客保留期、聊天媒体过期、资料图/广场图孤儿、磁盘报表
cat > "$APP_DIR/bin/maintenance.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
cd "$APP_DIR"
docker compose -f "$APP_DIR/docker-compose.yml" --project-directory "$APP_DIR" \\
    run --rm --no-deps web sh -c '
set -e
python manage.py refresh_shuffle_keys
python manage.py purge_profile_visits --apply
python manage.py im_media_cleanup --apply
python manage.py media_cleanup --apply
python manage.py media_disk_report --fail-over
'
EOF
chmod 700 "$APP_DIR/bin/maintenance.sh"

if [ -f "$SCRIPT_DIR/chatapp" ]; then
    install -m 755 "$SCRIPT_DIR/chatapp" "$APP_DIR/bin/chatapp"
fi

ok "配置生成完成"

if [ "$RENDER_ONLY" = 1 ]; then
    printf '\n生成的文件:\n'
    find "$APP_DIR" -maxdepth 3 -type f -printf '  %p\n' | sort
    printf '\n下一步(去掉 --render-only 正式部署):\n'
    NEXT_ARGS=$([ "$TLS" = 1 ] && printf -- '--domain %s --email %s' "$DOMAIN" "$EMAIL" || printf -- '--no-tls')
    [ "$ALLOW_DEV_SMS" = 1 ] && NEXT_ARGS="$NEXT_ARGS --allow-dev-sms"
    [ -n "$ADMIN_PHONE" ] && NEXT_ARGS="$NEXT_ARGS --admin-phone $ADMIN_PHONE"
    printf '  sudo bash %s/deploy/oneclick.sh %s\n' "$REPO_DIR" "$NEXT_ARGS"
    exit 0
fi

# --- Docker -----------------------------------------------------------------
install_docker() {
    log "安装 Docker(首次约 1–3 分钟)"
    if command -v dnf >/dev/null 2>&1; then
        dnf install -y dnf-plugins-core curl ca-certificates
        dnf config-manager --add-repo "$DOCKER_REPO_URL"
        local rel
        rel=$(. /etc/os-release && printf '%s' "${VERSION_ID%%.*}")
        # Alibaba Cloud Linux 3 的 VERSION_ID=3,但 Docker CE 仓库按 el8 组织
        [ "$rel" = "3" ] && rel=8
        sed -i "s/\\\$releasever/$rel/g" /etc/yum.repos.d/docker-ce.repo
        dnf install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    elif command -v apt-get >/dev/null 2>&1; then
        apt-get update -y
        apt-get install -y ca-certificates curl
        curl -fsSL https://get.docker.com | sh
    else
        die "不支持的系统:需要 dnf 或 apt-get"
    fi
    systemctl enable --now docker
}

if ! command -v docker >/dev/null 2>&1; then
    [ "$SKIP_DOCKER_INSTALL" = 1 ] && die "Docker 未安装,但指定了 --skip-docker-install"
    install_docker
fi

if ! docker compose version >/dev/null 2>&1; then
    log "补装 docker compose 插件"
    if command -v dnf >/dev/null 2>&1; then
        dnf install -y docker-compose-plugin
    elif command -v apt-get >/dev/null 2>&1; then
        apt-get install -y docker-compose-plugin
    else
        die "缺少 docker compose 插件"
    fi
fi

if ! docker info >/dev/null 2>&1; then
    log "Docker 守护进程未运行,尝试启动"
    systemctl start docker >/dev/null 2>&1 || true
    sleep 3
    docker info >/dev/null 2>&1 || die "Docker 守护进程未运行:systemctl start docker"
fi

# --- 端口与 DNS 预检 --------------------------------------------------------
compose() {
    docker compose -f "$APP_DIR/docker-compose.yml" --project-directory "$APP_DIR" "$@"
}

port_busy() {
    local port=$1
    command -v ss >/dev/null 2>&1 || return 1
    ss -ltnH "sport = :$port" 2>/dev/null | grep -q .
}

for p in "$HTTP_PORT" "$HTTPS_PORT"; do
    if port_busy "$p"; then
        # compose 的容器名是 chatapp-nginx-1,不能按固定名字判断;用 compose 标签
        if docker ps -q \
            --filter "label=com.docker.compose.project=chatapp" \
            --filter "label=com.docker.compose.service=nginx" 2>/dev/null | grep -q .; then
            warn "端口 $p 已被本项目 nginx 占用(继续重跑)"
        else
            die "端口 $p 已被占用。换端口用 --http-port/--https-port,或先停掉占用进程(如宝塔 nginx)"
        fi
    fi
done

if [ "$TLS" = 1 ]; then
    resolved=$(getent ahostsv4 "$DOMAIN" 2>/dev/null | awk 'NR==1{print $1}' || true)
    if [ -z "$resolved" ]; then
        warn "域名 $DOMAIN 尚未解析;certbot 会失败。请先加 A 记录再重跑。"
    else
        pub_ip=$(detect_public_ip || true)
        if [ -n "$pub_ip" ] && [ "$resolved" != "$pub_ip" ]; then
            warn "DNS 解析 $resolved 与本机公网 IP $pub_ip 不一致;若走 CDN/代理可忽略。"
        fi
    fi
fi

# --- 构建与启动 -------------------------------------------------------------
log "构建镜像(首次约 5–15 分钟;imserver C++ 构建在 2C2G 上较慢)"
if [ "$NO_BUILD" = 0 ]; then
    if [ -n "$IMSERVER_TAR" ]; then
        log "加载预构建 imserver 镜像: $IMSERVER_TAR"
        load_out=$(docker load -i "$IMSERVER_TAR")
        src_image=$(printf '%s\n' "$load_out" | sed -n -e 's/^Loaded image: //p' -e 's/^Loaded image ID: //p' | tail -n1)
        [ -n "$src_image" ] || die "无法从 docker load 输出识别镜像标签"
        docker tag "$src_image" chatapp-imserver:local
        compose build web nginx
    else
        compose build web nginx imserver
    fi
else
    warn "跳过镜像构建(--no-build)"
fi

log "启动 MySQL / Redis"
compose up -d mysql redis

wait_for_healthy() {
    local svc=$1 timeout=${2:-120} elapsed=0 cid status
    cid=$(compose ps -q "$svc" | head -n1 || true)
    [ -n "$cid" ] || die "服务 $svc 没有启动"
    while [ "$elapsed" -lt "$timeout" ]; do
        status=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$cid" 2>/dev/null || echo missing)
        case "$status" in
            healthy|running) return 0 ;;
            exited|dead)
                compose logs --tail=80 "$svc" >&2 || true
                die "服务 $svc 状态 $status"
                ;;
        esac
        sleep 2
        elapsed=$((elapsed + 2))
    done
    compose logs --tail=80 "$svc" >&2 || true
    die "服务 $svc 在 ${timeout}s 内未就绪(当前 $status)"
}

wait_for_healthy mysql 180
wait_for_healthy redis 60

log "初始化数据库(建 chatapp_im 与 imserver 账号)"
compose run --rm --no-deps db-init

log "执行 imserver 数据库迁移"
compose run --rm --no-deps imserver --migrate

log "执行 Django 迁移"
compose run --rm --no-deps migrate

log "启动应用容器"
UP_FLAGS=(--no-build --no-deps)
# 轮换密钥后 env_file 内容变了,显式重建,避免旧进程继续用旧口令
[ "$ROTATE_SECRETS" = 1 ] && UP_FLAGS+=(--force-recreate)
compose up -d "${UP_FLAGS[@]}" web worker imserver
wait_for_healthy web 180
wait_for_healthy imserver 180
wait_for_healthy worker 60

log "启动 nginx"
compose up -d --no-build --no-deps --force-recreate nginx
wait_for_healthy nginx 60

# --- 运营管理员 -------------------------------------------------------------
log "创建/确认运营管理员($ADMIN_PHONE)"
ADMIN_CODE='
import os
from accounts.models import User
phone = os.environ["ADMIN_PHONE"]
password = os.environ["ADMIN_PASSWORD"]
user, created = User.objects.get_or_create(
    phone=phone, defaults={"is_staff": True, "is_superuser": True}
)
changed = created
if not user.is_staff:
    user.is_staff = True
    changed = True
if not user.is_superuser:
    user.is_superuser = True
    changed = True
if created:
    user.set_password(password)
if changed:
    user.save()
print("admin_created" if created else "admin_exists")
'
compose run --rm --no-deps \
    -e ADMIN_PHONE="$ADMIN_PHONE" \
    -e ADMIN_PASSWORD="$ADMIN_PASSWORD" \
    web python manage.py shell -c "$ADMIN_CODE"

# --- HTTPS ------------------------------------------------------------------
if [ "$TLS" = 1 ]; then
    log "申请 Let's Encrypt 证书($DOMAIN)"
    CERTBOT_ARGS=(certonly --webroot -w /var/www/certbot -d "$DOMAIN"
        --email "$EMAIL" --agree-tos --no-eff-email --non-interactive)
    [ "$STAGING" = 1 ] && CERTBOT_ARGS+=(--staging)

    if ! compose --profile tools run --rm certbot "${CERTBOT_ARGS[@]}"; then
        warn "证书申请失败,站点仍以 HTTP 运行。"
        warn "排查:域名 A 记录是否指向本机、安全组/防火墙是否放行 80、Let's Encrypt 是否限流。"
        warn "修复后重跑本脚本即可(不会重建数据库)。"
        exit 1
    fi

    cp "$APP_DIR/nginx/https.conf" "$APP_DIR/nginx/conf.d/default.conf"
    if ! compose exec -T nginx nginx -t; then
        cp "$APP_DIR/nginx/http.conf" "$APP_DIR/nginx/conf.d/default.conf"
        compose exec -T nginx nginx -s reload || true
        die "HTTPS 配置校验失败,已回退 HTTP"
    fi
    compose exec -T nginx nginx -s reload

    log "切换 Django 到 HTTPS 模式并重启 web/worker"
    write_app_env 1
    compose up -d --no-build --no-deps --force-recreate web worker
    wait_for_healthy web 180
    # web 重建后容器 IP 会变,nginx 的静态 upstream 还指着旧 IP;必须重启 nginx
    compose up -d --no-build --no-deps --force-recreate nginx
    wait_for_healthy nginx 60

    if [ -d /run/systemd/system ]; then
        cat > /etc/systemd/system/chatapp-certbot-renew.service <<EOF
[Unit]
Description=Renew Let's Encrypt certificate for chatapp
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
WorkingDirectory="$APP_DIR"
ExecStart="$APP_DIR/bin/certbot-renew.sh"
EOF
        cat > /etc/systemd/system/chatapp-certbot-renew.timer <<'EOF'
[Unit]
Description=Daily chatapp certificate renewal

[Timer]
OnCalendar=*-*-* 03:17:00
Persistent=true
RandomizedDelaySec=600

[Install]
WantedBy=timers.target
EOF
        systemctl daemon-reload
        systemctl enable --now chatapp-certbot-renew.timer >/dev/null
        ok "已安装证书续期定时器(chatapp-certbot-renew.timer)"
    else
        warn "当前环境没有 systemd;请自行加 cron 每天执行 $APP_DIR/bin/certbot-renew.sh"
    fi
fi

# --- 每日维护定时器 ---------------------------------------------------------
if [ -d /run/systemd/system ]; then
    cat > /etc/systemd/system/chatapp-maintenance.service <<EOF
[Unit]
Description=Daily maintenance for chatapp
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
WorkingDirectory="$APP_DIR"
ExecStart="$APP_DIR/bin/maintenance.sh"
EOF
    cat > /etc/systemd/system/chatapp-maintenance.timer <<'EOF'
[Unit]
Description=Daily chatapp maintenance

[Timer]
OnCalendar=*-*-* 04:00:00
Persistent=true
RandomizedDelaySec=600

[Install]
WantedBy=timers.target
EOF
    systemctl daemon-reload
    systemctl enable --now chatapp-maintenance.timer >/dev/null
    ok "已安装每日维护定时器(chatapp-maintenance.timer)"
else
    warn "当前环境没有 systemd;请自行加 cron 每天执行 $APP_DIR/bin/maintenance.sh"
fi

# --- 防火墙(仅 firewalld 在跑时)-------------------------------------------
if command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
    firewall-cmd --permanent --add-port="${HTTP_PORT}/tcp" --add-port="${HTTPS_PORT}/tcp" >/dev/null
    firewall-cmd --reload >/dev/null
    ok "firewalld 已放行 ${HTTP_PORT}/${HTTPS_PORT}"
fi

# --- 验收 -------------------------------------------------------------------
verify_health() {
    if [ "$TLS" = 1 ]; then
        curl -fsS --max-time 15 --resolve "$DOMAIN:$HTTPS_PORT:127.0.0.1" \
            "https://$DOMAIN:$HTTPS_PORT/healthz" >/dev/null
        curl -fsS --max-time 15 --resolve "$DOMAIN:$HTTPS_PORT:127.0.0.1" \
            "https://$DOMAIN:$HTTPS_PORT/api/v1/health" >/dev/null
        curl -fsS --max-time 15 --resolve "$DOMAIN:$HTTPS_PORT:127.0.0.1" \
            "https://$DOMAIN:$HTTPS_PORT/api/v1/readyz" >/dev/null
    else
        curl -fsS --max-time 15 "http://127.0.0.1:$HTTP_PORT/healthz" >/dev/null
        curl -fsS --max-time 15 -H "Host: $PUBLIC_HOST" \
            "http://127.0.0.1:$HTTP_PORT/api/v1/health" >/dev/null
        curl -fsS --max-time 15 -H "Host: $PUBLIC_HOST" \
            "http://127.0.0.1:$HTTP_PORT/api/v1/readyz" >/dev/null
    fi
}

log "验收:nginx / Django / MySQL / Redis"
if ! verify_health; then
    compose ps >&2 || true
    compose logs --tail=80 web >&2 || true
    die "健康检查失败"
fi

ln -sfn "$APP_DIR/bin/chatapp" /usr/local/bin/chatapp
ok "安装运维命令: chatapp(status|logs|backup|migrate|manage|cert-renew)"

cat <<EOF

$(printf '%s✓ 部署完成%s' "$C_GREEN" "$C_RESET")

  站点        $PUBLIC_URL
  接口健康    $PUBLIC_URL/api/v1/health
  运营后台    $PUBLIC_URL/ops/
  管理员      $ADMIN_PHONE / $ADMIN_PASSWORD
              口令也保存在 $ADMIN_TXT(600)

  部署目录    $APP_DIR
  配置/密钥   $APP_DIR/secrets/(600,请备份 values.env)
  运维命令    chatapp status | chatapp logs | chatapp backup

$(printf '%s! 首次上线必读%s' "$C_YELLOW" "$C_RESET")
  1. 安全组/防火墙放行 TCP ${HTTP_PORT}、${HTTPS_PORT};$([ "$TLS" = 1 ] && printf 'HTTP 访问会自动 301 到 HTTPS。' || printf '当前是 HTTP 模式,未启用 HTTPS。')
  2. $([ "$SMS_DEV_MODE" = 1 ] && printf 'SMS_DEV_MODE=1:验证码固定 123456,只适合封闭测试;接真实短信商后改成 0。' || printf 'SMS_DEV_MODE=0:已关闭固定验证码,需接真实短信商后才能登录。')
     运营账号(staff/superuser)不能走短信登录,请直接用 $PUBLIC_URL/ops/ 的账号口令 + TOTP。
  3. AUTO_APPROVE=0:新资料图进入待审队列,去 /ops/photos/ 审核后才会出现在候选池。
  4. 首次进 /ops/ 会用管理员账号登录,并按提示绑定 TOTP(生产默认强制)。
  5. 2C2G 上 imserver 首次编译较慢;以后可用本地构建的镜像 --imserver-image-tar 跳过编译。
  6. 本方案与宝塔现网互斥:同一台机器 80/443 只能有一套 nginx,不要同时跑。
EOF
