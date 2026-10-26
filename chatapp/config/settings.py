"""Django 项目配置:敏感项一律从 ``chatapp/.env`` 读取,代码内不留真实凭据。

设计要点:
    1. **测试隔离**:``TESTING`` 在模块早期定义,后面多处据此切到独立 Redis DB
       (cache 15 / broker 14)与独立数据库,保证 ``manage.py test`` 绝不写开发数据;
    2. **Celery broker 的环境变量必须叫 ``BROKER_URL``**,不能叫 ``CELERY_BROKER_URL``
       —— 原因见下方 ``CELERY_BROKER_URL`` 处的说明;
    3. **共享状态一律走 Redis**:缓存、验证码、限流计数、Celery broker 都不用 LocMem,
       避免多进程部署后各进程看到不一致的状态。

注意事项:
    ``SMS_DEV_MODE=1`` 时验证码固定为 ``123456`` 且只打日志,上线前必须置 0。
"""

from datetime import timedelta
from pathlib import Path
import os
import sys

from dotenv import load_dotenv

from django.core.exceptions import ImproperlyConfigured

# 项目根目录,即仓库的 chatapp/(settings.py 位于 config/ 下一级)
BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


# --- 基础开关(以下默认值仅供本地开发,生产一律用 .env 覆盖) ---

# 生产必须从 .env 注入 SECRET_KEY;此处的默认值仅为让本地起得来
SECRET_KEY = os.getenv("SECRET_KEY", "dev-insecure-change-me")

# 生产必须置 DEBUG=0,否则异常页会泄漏源码与配置
DEBUG = os.getenv("DEBUG", "1") == "1"

ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")


# --- 应用注册 ---

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # 第三方
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    # 业务 app
    "accounts",
    "users",
    "discovery",
    "im",
    "moderation",
    "ops",
    "notifications",
    "feed",
    "feedback",
    "appconfig",
]

MIDDLEWARE = [
    "config.middleware.RequestIdMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "ops.context_processors.ops_badges",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# 「跑测试」开关:提前定义,DATABASES 等后面几处都要用它区分测试/生产行为
TESTING = sys.argv[1:2] == ["test"]


# --- 数据库 ---

_db_options = {"charset": "utf8mb4"}
if os.getenv("DB_SSL_DISABLED", "1") == "1":
    # 本地 MySQL 的 TLS 握手 ~250ms(2026-09-11 实测:每请求 ~280ms → ~22ms)。
    # dev 默认关;远程库/生产上置 DB_SSL_DISABLED=0。
    _db_options["ssl_disabled"] = True

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": os.getenv("DB_NAME", "chatapp_dev"),
        "USER": os.getenv("DB_USER", "chatapp"),
        # 口令一律来自 .env,代码里不留兜底值(避免把它当成"默认可用"的弱口令)
        "PASSWORD": os.getenv("DB_PASSWORD", ""),
        "HOST": os.getenv("DB_HOST", "127.0.0.1"),
        "PORT": os.getenv("DB_PORT", "3306"),
        "OPTIONS": _db_options,
        # 持久连接:省掉每请求的 MySQL 建连/认证开销;测试期关闭以保持用例隔离
        "CONN_MAX_AGE": 0 if TESTING else 60,
        "CONN_HEALTH_CHECKS": True,   # 复用前 SELECT 1 探活,防 MySQL 重启后的坏连接
        # 显式钉住测试库的字符集/排序规则:否则取 MySQL 服务器默认值
        # (MySQL 8 是 utf8mb4_0900_ai_ci,与 db_setup.sql 建的 utf8mb4_unicode_ci 不一致,
        #  会让"本地全绿、CI 红"这类环境差异变得难以复现)
        "TEST": {
            "CHARSET": "utf8mb4",
            "COLLATION": "utf8mb4_unicode_ci",
        },
    }
}


# --- Redis / 缓存 / Celery(共享状态一律走 Redis,不用 LocMem) ---
REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
# 注意:环境变量必须叫 BROKER_URL。celery/app/utils.py 的 broker_url 属性会优先读
# os.environ["CELERY_BROKER_URL"],若改用该名字,.env 里的值将永远压过下面的 TESTING
# 覆盖,导致测试任务漏进开发 broker(DB1)。
CELERY_BROKER_URL = os.getenv("BROKER_URL", "redis://127.0.0.1:6379/1")
if TESTING:
    # 测试用独立 DB 序号:清库不误伤开发数据;任务只入队不执行(无 worker)
    # 端口/主机同样允许覆盖:CI 或本机 6379 被占用时,用 TEST_REDIS_HOST/PORT 指到别处
    _test_host = os.getenv("TEST_REDIS_HOST", "127.0.0.1")
    _test_port = os.getenv("TEST_REDIS_PORT", "6379")
    REDIS_URL = f"redis://{_test_host}:{_test_port}/15"
    CELERY_BROKER_URL = f"redis://{_test_host}:{_test_port}/14"

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "KEY_PREFIX": "chatapp",
        "OPTIONS": {"CONNECTION_POOL_KWARGS": {"max_connections": 50}},
    }
}

CELERY_TASK_IGNORE_RESULT = True          # 副作用任务不需要结果
CELERY_TASK_ACKS_LATE = True              # 任务不丢:执行完才 ack
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True


# --- 密码校验(Django 内置四条;本项目登录走短信验证码,此处主要约束 admin 账号) ---

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# --- 国际化与时区 ---

LANGUAGE_CODE = "zh-hans"

TIME_ZONE = "Asia/Shanghai"

USE_I18N = True

USE_TZ = True


# --- 静态文件 ---

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"   # collectstatic 产物目录;生产由 nginx 直出(.gitignore 已忽略)

# --- 默认主键类型 ---

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "accounts.User"

# --- 限流额度(env 可调;DEBUG 下放宽,免得两台模拟器共享 127.0.0.1 触发 IP 限流) ---
SMS_SEND_IP_RATE = os.getenv("SMS_SEND_IP_RATE", "200/hour" if DEBUG else "20/hour")
SMS_VERIFY_IP_RATE = os.getenv("SMS_VERIFY_IP_RATE", "600/hour" if DEBUG else "60/hour")
PRESENCE_RATE = os.getenv("PRESENCE_RATE", "600/hour")   # 在线状态轮询:一个前台页面 ≈ 80/h
FEEDBACK_RATE = os.getenv("FEEDBACK_RATE", "50/hour" if DEBUG else "5/hour")
CHAT_IMAGE_RATE = os.getenv("CHAT_IMAGE_RATE", "30/hour")   # 聊天图片上传,按用户计数

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "accounts.authentication.SessionJwtAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
        "moderation.permissions.IsNotHeavyBanned",
    ),
    "EXCEPTION_HANDLER": "config.exceptions.api_exception_handler",
    "DEFAULT_PAGINATION_CLASS": "config.pagination.DefaultLimitOffsetPagination",
    "DEFAULT_THROTTLE_RATES": {
        "sms_send": SMS_SEND_IP_RATE,
        "sms_verify": SMS_VERIFY_IP_RATE,
        "swipe": "300/hour",
        "report": "20/day",
        "post_create": "20/day",
        "post_comment": "60/day",
        "post_report": "20/day",
        "presence": PRESENCE_RATE,
        "feedback": FEEDBACK_RATE,
        "chat_image": CHAT_IMAGE_RATE,
    },
}

CORS_ALLOWED_ORIGIN_REGEXES = [
    r"^http://localhost:\d+$",   # Flutter Web / 调试用
    r"^http://127\.0\.0\.1:\d+$",
]
CORS_EXPOSE_HEADERS = ["X-Request-Id"]   # 浏览器端能读到追踪头


# --- 短信验证码(开发期控制台后端;上线接短信商时加 notifications/backends.py 实现) ---
SMS_DEV_MODE = os.getenv("SMS_DEV_MODE", "1") == "1"   # 1=开发模式,验证码固定且只打日志
SMS_DEV_CODE = "123456"
SMS_CODE_TTL = 300          # 验证码有效期(秒)
SMS_RESEND_INTERVAL = 60    # 同一号码重发间隔(秒)
SMS_MAX_ATTEMPTS = 5        # 连续错误次数上限
SMS_LOCK_TTL = 900          # 触发上限后锁定时长(秒)
SMS_REPLAY_TTL = 60         # 校验成功后的幂等重放窗口(秒):响应丢失时同码可再换令牌

# --- 日志:开发期要能在终端看到验证码;每行带 request_id ---
LOG_FILE = os.getenv("LOG_FILE", "")          # 置为文件路径则额外落盘(手测配 --noreload)
REQUEST_SLOW_MS = int(os.getenv("REQUEST_SLOW_MS", "500"))

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"request_id": {"()": "config.request_id.RequestIdFilter"}},
    "formatters": {
        "console": {"format": "%(levelname)s %(asctime)s [%(request_id)s] %(name)s %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler",
                    "filters": ["request_id"], "formatter": "console"},
    },
    "loggers": {
        "accounts": {"handlers": ["console"], "level": "INFO"},
        "im": {"handlers": ["console"], "level": "INFO"},
        "chatapp.request": {"handlers": ["console"], "level": "INFO",
                            "filters": ["request_id"]},
    },
}
if LOG_FILE:
    # 注意:此时手测必须用 runserver --noreload —— autoreload 的两个进程会抢写同一文件
    LOGGING["handlers"]["file"] = {
        "class": "logging.handlers.RotatingFileHandler",
        "filename": LOG_FILE,
        "maxBytes": 5 * 1024 * 1024,
        "backupCount": 3,
        "encoding": "utf-8",
        "filters": ["request_id"],
        "formatter": "console",
    }
    LOGGING["root"] = {"handlers": ["console", "file"], "level": "INFO"}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=30),
    "ROTATE_REFRESH_TOKENS": True,     # 每次刷新都换新 refresh
    "BLACKLIST_AFTER_ROTATION": True,  # 旧的立即拉黑
}

# --- 腾讯云 IM REST(凭据只在 .env) ---
IM_SDKAPPID = os.getenv("IM_SDKAPPID", "")
IM_SECRETKEY = os.getenv("IM_SECRETKEY", "")
IM_ADMIN_IDENTIFIER = os.getenv("IM_ADMIN_IDENTIFIER", "administrator")
IM_REST_BASE = "https://console.tim.qq.com/v4"
IM_SIG_EXPIRE = 7 * 24 * 3600   # userSig 有效期(秒),腾讯上限 180 天
IM_TIMEOUT = 5                  # REST 超时(秒)

# --- 自建 IM(IM_BACKEND=self 时生效) ---
IM_BACKEND = os.getenv("IM_BACKEND", "tencent")
IM_SELF_URL = os.getenv("IM_SELF_URL", "http://127.0.0.1:9101")
IM_SELF_WS_URL = os.getenv("IM_SELF_WS_URL", "")
IM_SELF_HTTP_URL = os.getenv("IM_SELF_HTTP_URL", "")
IM_SELF_SECRET = os.getenv("IM_SELF_SECRET", "")
IM_SELF_INTERNAL_SECRET = os.getenv("IM_SELF_INTERNAL_SECRET", "")
IM_SELF_TOKEN_TTL = int(os.getenv("IM_SELF_TOKEN_TTL", "86400"))
IM_SELF_GRAYLIST = os.getenv("IM_SELF_GRAYLIST", "")

if IM_BACKEND == "self" and not (IM_SELF_SECRET and IM_SELF_INTERNAL_SECRET
                                 and IM_SELF_WS_URL and IM_SELF_HTTP_URL):
    raise ImproperlyConfigured("IM_BACKEND=self 需要完整的 IM_SELF_* 配置")

# --- 客户端最小版本(全量切换前必须能挡住旧版本)---
MIN_APP_VERSION = os.getenv("MIN_APP_VERSION", "1.0.0")
LATEST_APP_VERSION = os.getenv("LATEST_APP_VERSION", "1.0.0")
APP_DOWNLOAD_URL = os.getenv("APP_DOWNLOAD_URL", "")

# --- 照片 ---
AUTO_APPROVE = os.getenv("AUTO_APPROVE", "1") == "1"   # 开发期自动过审;上线接内容安全 API 后置 0
PHOTO_MAX_COUNT = 6
PHOTO_MAX_BYTES = 5 * 1024 * 1024

# --- 聊天图片(图片二期)---
CHAT_IMAGE_MAX_BYTES = 5 * 1024 * 1024
CHAT_IMAGE_MAX_SIDE = 4096
CHAT_IMAGE_THUMB_SIDE = 240

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# IM 头像同步用:任务里没有 request,拿不到绝对 URL,配域名前缀(生产改成正式域名/CDN)
MEDIA_BASE_URL = os.getenv("MEDIA_BASE_URL", "http://127.0.0.1:8000")

LOGIN_REDIRECT_URL = "/ops/reports/"
