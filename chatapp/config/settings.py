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
import re
import sys

from dotenv import load_dotenv

from django.core.exceptions import ImproperlyConfigured

# 项目根目录,即仓库的 chatapp/(settings.py 位于 config/ 下一级)
BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


def _read_app_version() -> str:
    """读取 App 版本号,作为 OpenAPI 文档的版本(D-5)。

    设计要点:
        ``app/pubspec.yaml`` 是发版版本号的唯一来源(见 CLAUDE.md「发版版本号必须双端同改」)。
        直接读它,OpenAPI 文档就不会再手写一份版本号而漂移;真正的三端一致性校验由
        ``scripts/sync_version.py`` 负责。

    Returns:
        形如 ``1.0.4`` 的版本号;文件缺失或解析失败时返回 ``0.0.0``(宁可有值,不让生成失败)。
    """
    pubspec = BASE_DIR.parent / "app" / "pubspec.yaml"
    try:
        text = pubspec.read_text(encoding="utf-8")
    except OSError:
        return "0.0.0"
    match = re.search(r"^version:\s*([0-9][^\s+]*)", text, re.MULTILINE)
    return match.group(1) if match else "0.0.0"


# --- 基础开关(以下默认值仅供本地开发,生产一律用 .env 覆盖) ---

# 生产必须从 .env 注入 SECRET_KEY;此处的默认值仅为让本地起得来。
# 它同时是 JWT(HS256)、验证码 HMAC 与 session 签名的密钥 —— 生产漏配等于全站可伪造,
# 因此下面在 DEBUG=0 时直接拒绝启动(H-2)。
_DEV_SECRET_KEY = "dev-insecure-change-me"
SECRET_KEY = os.getenv("SECRET_KEY", _DEV_SECRET_KEY)

# 生产必须置 DEBUG=0,否则异常页会泄漏源码与配置
DEBUG = os.getenv("DEBUG", "1") == "1"

ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")


def assert_production_secret_key(secret: str, debug: bool) -> None:
    """生产环境拒绝使用开发默认密钥。

    Args:
        secret: 当前生效的 ``SECRET_KEY``。
        debug: 当前 ``DEBUG`` 开关。

    Raises:
        ImproperlyConfigured: ``DEBUG`` 关闭且仍在使用开发默认密钥。
    """
    if not debug and secret == _DEV_SECRET_KEY:
        raise ImproperlyConfigured(
            "生产必须配置 SECRET_KEY(不能沿用开发默认值):JWT/验证码/HMAC 都依赖它")


assert_production_secret_key(SECRET_KEY, DEBUG)


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
    "drf_spectacular",   # D-5:OpenAPI 导出
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
    "telemetry",
]

MIDDLEWARE = [
    "config.middleware.RequestIdMiddleware",
    "config.middleware.MetricsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "ops.middleware.StaffSecurityMiddleware",
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

# --- 队列分级(削峰)---
# 三类任务的延迟容忍度完全不同,挤在一个队列里会让「封禁踢人」排在「配对灰条」后面:
#   critical:封禁/踢下线/聊天权限 —— 必须最快;
#   default :其余 IM 副作用;
#   notify  :配对/评论/举报通知 —— 可以等,是突发流量的主要来源;
#   bulk    :资料同步/账号导入 —— 最不急,可以慢慢跑。
CELERY_TASK_DEFAULT_QUEUE = "default"
CELERY_TASK_ROUTES = {
    "im.tasks.ban_notice": {"queue": "critical"},
    "im.tasks.ban_lifted": {"queue": "critical"},
    "im.tasks.kick_pending": {"queue": "critical"},
    "im.tasks.delete_account": {"queue": "critical"},
    "im.tasks.pair_add": {"queue": "critical"},
    "im.tasks.unmatch_blacklist": {"queue": "critical"},
    "im.tasks.blacklist_add": {"queue": "critical"},
    "im.tasks.blacklist_remove": {"queue": "critical"},
    "im.tasks.send_match_notice": {"queue": "notify"},
    "im.tasks.post_commented": {"queue": "notify"},
    "im.tasks.post_replied": {"queue": "notify"},
    "im.tasks.report_handled": {"queue": "notify"},
    "im.tasks.sync_profile": {"queue": "bulk"},
    "im.tasks.import_account": {"queue": "bulk"},
}
# notify 队列的消费速率上限(条/秒)。imserver 单机实测天花板 ~215 msg/s,
# 配对高峰(一次活动 500 对)瞬间产生 1000 条灰条,不限速会把 imserver 打满、
# ack p99 从 93ms 涨到秒级。0 = 不限速。
IM_NOTICE_RATE_PER_SEC = int(os.getenv("IM_NOTICE_RATE_PER_SEC", "50"))


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

# 后台登录失败锁定(账号 + IP 双维度);达到上限后锁定 15 分钟
AUTHENTICATION_BACKENDS = ["accounts.backends.ThrottledModelBackend"]
OPS_LOGIN_MAX_ATTEMPTS = int(os.getenv("OPS_LOGIN_MAX_ATTEMPTS", "5"))
OPS_LOGIN_LOCK_SECONDS = int(os.getenv("OPS_LOGIN_LOCK_SECONDS", "900"))

# 运营后台的第二因子与 IP 白名单:
# - OPS_OTP_REQUIRED 生产默认开;DEBUG/测试默认关,避免本地手测被挡
# - OPS_ALLOWED_IPS 为空表示不限制;生产建议填公网出口 IP 或只走 VPN
OPS_OTP_REQUIRED = os.getenv("OPS_OTP_REQUIRED",
                             "0" if (DEBUG or TESTING) else "1") == "1"
OPS_ALLOWED_IPS = os.getenv("OPS_ALLOWED_IPS", "")
# 第二因子的有效期:通过一次后最多复用这么久(默认 12 小时),超时重新要验证码。
OPS_OTP_TTL = int(os.getenv("OPS_OTP_TTL", str(12 * 3600)))

# --- 限流额度(env 可调;DEBUG 下放宽,免得两台模拟器共享 127.0.0.1 触发 IP 限流) ---
SMS_SEND_IP_RATE = os.getenv("SMS_SEND_IP_RATE", "200/hour" if DEBUG else "20/hour")
SMS_VERIFY_IP_RATE = os.getenv("SMS_VERIFY_IP_RATE", "600/hour" if DEBUG else "60/hour")
# 测试期把「按用户」的读接口额度放宽,避免同一个测试账号跨用例累积触发 429;
# 生产值仍是审计报告要求的严格额度(见各 *_RATE 注释)。
_RELAXED = "100000/hour" if TESTING else None
PRESENCE_RATE = os.getenv("PRESENCE_RATE", _RELAXED or "120/hour")       # 45s 心跳 ≈ 80/h
CANDIDATE_RATE = os.getenv("CANDIDATE_RATE", _RELAXED or "60/hour")      # 候选池随机排序,开销大
USER_SIG_RATE = os.getenv("USER_SIG_RATE", _RELAXED or "30/hour")        # 每次拉签名都可能同步外部 IM
POST_LIKE_RATE = os.getenv("POST_LIKE_RATE", _RELAXED or "120/hour")
BLOCK_RATE = os.getenv("BLOCK_RATE", _RELAXED or "60/hour")
PHOTO_UPLOAD_RATE = os.getenv("PHOTO_UPLOAD_RATE", _RELAXED or "20/hour")
PUBLIC_PROFILE_RATE = os.getenv("PUBLIC_PROFILE_RATE", _RELAXED or "120/hour")
# 访客列表/人数(M-3):列表要跑三个子查询,人数接口单请求多次聚合
VISITS_RATE = os.getenv("VISITS_RATE", _RELAXED or "120/hour")
VISITS_COUNT_RATE = os.getenv("VISITS_COUNT_RATE", _RELAXED or "240/hour")
PROBE_RATE = os.getenv("PROBE_RATE", _RELAXED or "1200/hour")   # 探针 10s 一次 ≈ 360/h
FEEDBACK_RATE = os.getenv("FEEDBACK_RATE", "50/hour" if DEBUG else "5/hour")
CHAT_IMAGE_RATE = os.getenv("CHAT_IMAGE_RATE", "30/hour")   # 聊天图片上传,按用户计数
CHAT_VOICE_RATE = os.getenv("CHAT_VOICE_RATE", "60/hour")   # 聊天语音上传,按用户计数

# 资料抓取监控(M2):同一账号一小时内浏览「多少个不同的人」超过该值就记 WARNING。
# 限流只能压慢抓取,这个计数是发现「正在被批量爬」的早期信号;只告警不拦截。
PROFILE_SCRAPE_ALERT_PER_HOUR = int(os.getenv("PROFILE_SCRAPE_ALERT_PER_HOUR", "60"))

# 访客记录(M-2):每个被访问者最多保留最近 N 条;<=0 关闭淘汰。
# 访客列表本身只展示「资料完善 + 有过审照片」的访问者,这里再兜一层表膨胀上限。
PROFILE_VISIT_MAX_PER_OWNER = int(os.getenv("PROFILE_VISIT_MAX_PER_OWNER", "500"))

# 可信代理:只有直连对端命中这份名单时,才采信 X-Real-IP / X-Forwarded-For。
# 默认只信回环 —— 生产 Django 只监听 127.0.0.1,由本机 nginx 反代(M-3)。
TRUSTED_PROXY_IPS = os.getenv("TRUSTED_PROXY_IPS", "127.0.0.1,::1")

# C-1:运营账号(staff/superuser)默认不允许走短信登录 —— 固定验证码 + 可猜的
# 管理员手机号等于把最高权限的 API 身份交出去。封闭测试确需用运营账号登 App 时,
# 显式设 SMS_ALLOW_STAFF_LOGIN=1;生产必须保持 0。
SMS_ALLOW_STAFF_LOGIN = os.getenv("SMS_ALLOW_STAFF_LOGIN", "0") == "1"

REST_FRAMEWORK = {
    # 只信任最近一层代理(nginx)追加的 XFF 末位。不设置时 DRF 会把整条
    # X-Forwarded-For 当 ident,客户端随便换一个值就能绕过 IP 限流。
    "NUM_PROXIES": int(os.getenv("NUM_PROXIES", "1")),
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "accounts.authentication.SessionJwtAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
        "moderation.permissions.IsNotHeavyBanned",
    ),
    "EXCEPTION_HANDLER": "config.exceptions.api_exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
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
        "candidates": CANDIDATE_RATE,
        "user_sig": USER_SIG_RATE,
        "post_like": POST_LIKE_RATE,
        "blocks": BLOCK_RATE,
        "upload_photo": PHOTO_UPLOAD_RATE,
        "public_profile": PUBLIC_PROFILE_RATE,
        "visits": VISITS_RATE,
        "visits_count": VISITS_COUNT_RATE,
        "probe": PROBE_RATE,
        "logout": os.getenv("LOGOUT_RATE", "60/hour"),
        "feedback": FEEDBACK_RATE,
        "chat_image": CHAT_IMAGE_RATE,
        "chat_voice": CHAT_VOICE_RATE,
        "client_error": os.getenv("CLIENT_ERROR_RATE", "120/hour"),
    },
}

# --- OpenAPI schema(D-5)---
# 机器可读契约:``python manage.py spectacular`` 生成 ``docs/api/openapi.yml``。
# 人读文档仍是 ``docs/api/*.md``(两者并存,见 docs/api/README.md)。
SPECTACULAR_SETTINGS = {
    "TITLE": "chat_app API",
    "DESCRIPTION": (
        "交友 App 后端接口(/api/v1)。\n\n"
        "本文件由 `python manage.py spectacular` 从代码生成,请勿手改;"
        "人读文档见仓库 docs/api/。"
    ),
    "VERSION": _read_app_version(),
    # /api/v1 下只放业务接口:schema 不注册成视图,生成物走 CLI 落盘。
    "SERVE_INCLUDE_SCHEMA": False,
    # 只导出 /api/v1;/ops 后台与 /metrics 不属于对外契约(门禁口径同 ApiDocsCoverageTests)。
    "SCHEMA_PATH_PREFIX": r"^/api/v1",
    # 请求体与响应体拆成两个组件:请求只含可写字段、响应含只读字段,
    # 「字段级门禁」才能与 docs/api 的「请求参数 / 响应参数」两张表逐字段对齐。
    "COMPONENT_SPLIT_REQUEST": True,
    # 稳定排序:CI 用 git diff 比对生成物,顺序抖动会变成误报。
    "SORT_OPERATIONS": True,
}

# localhost 只给本地调试用;生产 Web 与 API 同源,不需要 CORS。
CORS_ALLOWED_ORIGIN_REGEXES = []
if DEBUG:
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
# B-1 / B-1c:封闭测试期把注册面关死 —— 只有准入名单内的号码能收发验证码。
# 名单本体已落到数据库(`accounts.PhoneAllowlist`,运营后台 `/ops/allowlist/` 维护,
# 加号/停用**立刻生效、不用重启 web**);这里的 .env 值降级为「兜底种子」:
# 库里还没有这条记录时仍按它放行(冷启动、首次导入前的过渡),但库里显式停用的
# 号码优先被拒。逗号分隔的 11 位手机号;库与种子都留空 = 不限制(开发/测试)。
# 理由:固定验证码 + 任意手机号 = 谁都能接管别人账号;名单把可登录的号码从
# 「全空间」缩到「我们自己人」。**本项目确定不接短信商(2026-11-03),名单是长期机制**,
# 不是过渡方案 —— 日常运维见 docs/ops/runbook.md 与 backlog B-1c。
SMS_PHONE_WHITELIST = frozenset(
    p.strip() for p in os.getenv("SMS_PHONE_WHITELIST", "").split(",") if p.strip()
)
# 名单快照缓存 TTL(秒):写路径(/ops/ 加号、停用、种子导入)会显式清缓存立刻生效,
# 这个 TTL 只决定「绕过 /ops/ 直接改库」时最多多久被发现。
SMS_ALLOWLIST_CACHE_TTL = int(os.getenv("SMS_ALLOWLIST_CACHE_TTL", "60"))

# --- 日志:开发期要能在终端看到验证码;每行带 request_id ---
LOG_FILE = os.getenv("LOG_FILE", "")          # 置为文件路径则额外落盘(手测配 --noreload)
REQUEST_SLOW_MS = int(os.getenv("REQUEST_SLOW_MS", "500"))
# 生产置 json:单行 JSON,Loki/ES 才能按 request_id/user_id/route 检索;
# 开发保持 text(终端可读)。字段白名单见 config/logging.py。
LOG_FORMAT = os.getenv("LOG_FORMAT", "text")

# --- Prometheus 抓取令牌:/metrics 的访问控制 ---
# 生产必须设置:nginx 反代后 REMOTE_ADDR 恒为 127.0.0.1,回环判断挡不住公网。
# 未设置时 /metrics 只对回环直连开放,其余一律 404(不暴露端点存在)。
METRICS_TOKEN = os.getenv("METRICS_TOKEN", "")

# /metrics 豁免 HTTPS 强制跳转:Prometheus 在回环上直接抓 http://127.0.0.1:8000,
# 不豁免会被 301 到 https,跟随重定向后对 8000 做 TLS 握手而失败
# (2026-11-03 上线时实际踩到)。
SECURE_REDIRECT_EXEMPT = [r"^metrics$"]

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
if LOG_FORMAT == "json":
    LOGGING["formatters"]["console"] = {"()": "config.logging.JsonFormatter"}
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

# --- Web 端的 refresh token 走 HttpOnly Cookie(见 docs/superpowers/specs/2026-10-28-token-hardening-design.md) ---
# 只对带 ``X-Client: web`` 头的请求下发;App 仍走响应体,协议不变。
REFRESH_COOKIE_NAME = os.getenv("REFRESH_COOKIE_NAME", "chatapp_rt")
REFRESH_COOKIE_PATH = "/api/v1/auth/"     # 只在 refresh/logout 两个请求上携带
# 轮换宽限:多标签页同时刷新时,后到者用旧 token 仍能拿到同一对新令牌。
# 超过宽限的复用视为泄露重放,直接 401。默认 60 秒足够覆盖并发刷新。
REFRESH_REUSE_GRACE = int(os.getenv("REFRESH_REUSE_GRACE", "60"))

# --- 自建 IM(唯一后端;腾讯云 IM 分支已于 2026-11-08 删除,backlog D-4) ---
IM_SELF_URL = os.getenv("IM_SELF_URL", "http://127.0.0.1:9101")
IM_SELF_WS_URL = os.getenv("IM_SELF_WS_URL", "")
IM_SELF_HTTP_URL = os.getenv("IM_SELF_HTTP_URL", "")
IM_SELF_SECRET = os.getenv("IM_SELF_SECRET", "")
IM_SELF_INTERNAL_SECRET = os.getenv("IM_SELF_INTERNAL_SECRET", "")
IM_SELF_TOKEN_TTL = int(os.getenv("IM_SELF_TOKEN_TTL", "86400"))

if not (TESTING or DEBUG) and not (IM_SELF_SECRET and IM_SELF_INTERNAL_SECRET
                                   and IM_SELF_WS_URL and IM_SELF_HTTP_URL):
    raise ImproperlyConfigured("自建 IM 需要完整的 IM_SELF_* 配置"
                              "(SECRET / INTERNAL_SECRET / WS_URL / HTTP_URL)")

# --- 客户端最小版本(全量切换前必须能挡住旧版本)---
MIN_APP_VERSION = os.getenv("MIN_APP_VERSION", "1.0.0")
LATEST_APP_VERSION = os.getenv("LATEST_APP_VERSION", "1.0.0")
APP_DOWNLOAD_URL = os.getenv("APP_DOWNLOAD_URL", "")

# --- 照片 ---
# 生产默认「先审后发」:新照片进入 pending,由 /ops/photos/ 审核队列处理;
# 本地 DEBUG 与测试默认自动过审,免得每次手测都要点审核(H5)。
AUTO_APPROVE = os.getenv("AUTO_APPROVE",
                         "1" if (DEBUG or TESTING) else "0") == "1"
PHOTO_MAX_COUNT = 6
PHOTO_MAX_BYTES = 5 * 1024 * 1024

# --- 聊天图片(图片二期)---
CHAT_IMAGE_MAX_BYTES = 5 * 1024 * 1024
CHAT_IMAGE_MAX_SIDE = 4096
CHAT_IMAGE_THUMB_SIDE = 240

# --- 聊天图片签名 URL(与 imserver 的 IM_MEDIA_SIGN_* 必须一致)---
IM_MEDIA_SIGN_SECRET = os.getenv("IM_MEDIA_SIGN_SECRET", "")
IM_MEDIA_SIGN_TTL = int(os.getenv("IM_MEDIA_SIGN_TTL", "3600"))
if not DEBUG and not IM_MEDIA_SIGN_SECRET:
    # 漏配密钥时 nginx 的 auth_request 会变成「不签名也放行」,等于私聊媒体公开。
    # 宁可起不来,也不要静默 fail-open。
    raise ImproperlyConfigured("生产必须配置 IM_MEDIA_SIGN_SECRET(聊天媒体签名)")
# 聊天图片保留期(天);0 表示只清孤儿文件与删除残留
CHAT_IMAGE_RETENTION_DAYS = int(os.getenv("CHAT_IMAGE_RETENTION_DAYS", "30"))

# --- 聊天语音(ffmpeg 统一转 m4a/AAC)---
CHAT_VOICE_MAX_BYTES = 5 * 1024 * 1024
CHAT_VOICE_MAX_OUT_BYTES = 2 * 1024 * 1024
CHAT_VOICE_MIN_MS = 1000
CHAT_VOICE_MAX_MS = 60000
CHAT_VOICE_DURATION_TOLERANCE_MS = 2000
CHAT_VOICE_SAMPLE_RATE = 16000
CHAT_VOICE_BITRATE = "32k"
CHAT_VOICE_RETENTION_DAYS = int(os.getenv("CHAT_VOICE_RETENTION_DAYS", "30"))

# --- 存储配额与磁盘告警(M7)---
# 单账号媒体总量上限(资料图 + 广场图 + 聊天图 + 聊天语音)。按审计估算,
# 聊天图 30 次/小时 × 5MB 单日可达 3.6GB,200MB 把单个小号的天花板压住;
# 置 0 表示关闭配额(本地手测可关)。
USER_STORAGE_QUOTA_MB = int(os.getenv("USER_STORAGE_QUOTA_MB", "200"))
USER_STORAGE_QUOTA_BYTES = USER_STORAGE_QUOTA_MB * 1024 * 1024
# ``media_disk_report`` 的告警线:媒体目录总占用超过它就算磁盘吃紧
MEDIA_DISK_WARN_MB = int(os.getenv("MEDIA_DISK_WARN_MB", "5000"))

# --- 候选池(M7)---
# 候选接口按 ``Profile.shuffle_key`` 索引取一个池子,再在内存里抽样;
# 池子越大越不容易重复,取 200 对数百人的规模足够。
CANDIDATE_POOL_SIZE = int(os.getenv("CANDIDATE_POOL_SIZE", "200"))
# 候选池缓存 TTL(秒)。写路径会升版本让旧键立即失效,TTL 只决定「无人操作时
# 多久重新查一次库」——所以它只是兜底,拉长不影响正确性(见 config/cache_utils.py)。
# 2026-11-04 实测(D-2):冷池查询在 2 万资料时 **114.6ms**(全表扫 + 4 个反连接 + 排序),
# 热池 0.95ms;30s 时每个活跃用户每 30 秒就吃一次 115ms。拉到 300s 后冷查询频率降 10 倍,
# 而「划走一个人/配对/拉黑」仍然靠版本号立刻失效,不需要靠 TTL。
CANDIDATE_CACHE_TTL = int(os.getenv("CANDIDATE_CACHE_TTL", "300"))

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# IM 头像同步用:任务里没有 request,拿不到绝对 URL,配域名前缀(生产改成正式域名/CDN)
MEDIA_BASE_URL = os.getenv("MEDIA_BASE_URL", "http://127.0.0.1:8000")

LOGIN_REDIRECT_URL = "/ops/reports/"

# --- HTTPS / 安全头(域名与证书到位后置 HTTPS_ENABLED=1)---
# 说明:nginx 必须先配好 443 与 ``proxy_set_header X-Forwarded-Proto $scheme``;
# 打开后 80 端口的 Django 请求会被 301 到 https,后台 Cookie 也只走 Secure。
HTTPS_ENABLED = os.getenv("HTTPS_ENABLED", "0") == "1"
if HTTPS_ENABLED:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "3600"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = os.getenv("SECURE_HSTS_PRELOAD", "0") == "1"
    CSRF_TRUSTED_ORIGINS = [item.strip() for item in
                            os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",") if item.strip()]
    SECURE_REFERRER_POLICY = "same-origin"

# 与是否 HTTPS 无关的纵深防御头(nginx 静态页也需同步,见部署核对单)
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
