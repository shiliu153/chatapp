# M1a 注册登录与资料完善(后端)实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 后端实现「验证码注册登录 → 完善资料(昵称/性别/生日/城市/简介/标签/照片)→ 资料完成状态流转」的完整闭环,接口有测试、全绿。

**Architecture:** 在 M0 的 Django 骨架上加业务。`accounts` 负责短信验证码服务 + JWT 签发/刷新;`users` 负责 Profile/Photo/Tag/Preference 模型与资料接口;`moderation` 先只放一个内置违规词库(审核台留到 M3)。错误响应全局统一为 `{code, message}`,成功返回资源 JSON。开发期短信走固定验证码 + 日志,照片走 AUTO_APPROVE 自动通过,两者都留了环境开关注明上线前替换。

**Tech Stack:** Django 5.2 LTS + DRF + SimpleJWT(开启 refresh 轮换 + 黑名单)、MySQL 8、Pillow(图片校验)、Django 默认 LocMemCache(验证码/限流状态,上线前换 Redis)。

**本计划的范围边界(重要):** spec §12 的 M1 是「后端全量」,本计划只做其中**前半段(accounts + users)**;后半段 `im`(userSig 签发/account_import/配对灰条消息)与 `discovery`(候选/滑卡/配对)是下一个计划 **M1b**。因此:
- 本计划**不做**:IM 账号导入钩子、`POST /im/user_sig`、候选/滑卡/配对接口、`GET /matches`、拉黑/举报、封禁拦截(403/拒签)。
- 本计划**要做但只到「存字段、留开关」**的程度:Profile.status 的封禁状态枚举(供 M1b/M3 使用)、照片审核状态的 AUTO_APPROVE 分支(M3 接内容安全 API 时置 0)。

## Global Constraints

- 所有 shell 命令在 Windows Git Bash 里跑,路径用正斜杠;`python` 指 anaconda 环境 `Django`(Python 3.10.19);Django 命令的 cwd 一律是 `D:\pycharmproject\chat_app\chatapp`
- **严禁改动 `flutter/`(SDK 源码)与 `app/`(前端)** —— 本计划是纯后端
- 每个 Task 结束必须 `git commit`,消息格式 `feat: ... (M1a)` / `chore: ... (M1a)`
- 密钥/口令只进 `chatapp/.env`(已 gitignore);`media/`(用户上传)也已在 .gitignore,勿提交
- **接口约定(全项目统一,前端 M2 依赖它)**:
  - 成功:HTTP 2xx,body 直接是资源 JSON(不加信封)
  - 失败:HTTP 4xx/5xx,body 一律 `{"code": <HTTP 状态码>, "message": "<中文提示>"}`
  - 鉴权:`Authorization: Bearer <access token>`;全局默认 `IsAuthenticated`,公开接口显式 `AllowAny`
- 所有接口挂 `/api/v1/` 下,app 内用各自的 `urls.py`,由 `config/api_urls.py` 汇总
- 不引入 Redis/新框架:开发期缓存用 Django 内置默认 LocMemCache(`from django.core.cache import cache` 直接可用)
- 用户是 Django 新手:每步给命令与预期输出;报错先看该 Task 末尾的「卡点速查」

---

### Task 1: 统一错误响应信封 + 中文化/时区

**Files:**
- Create: `chatapp/config/exceptions.py`
- Create: `chatapp/config/tests.py`
- Modify: `chatapp/config/settings.py`(REST_FRAMEWORK / LANGUAGE_CODE / TIME_ZONE)

**Interfaces:**
- Consumes: M0 的 `/api/v1/health`(借它触发一个 405 错误来验证信封)。
- Produces: 全局异常处理器 `config.exceptions.api_exception_handler` —— 之后所有 Task 的接口报错都自动是 `{code, message}`,不需要各自处理。`config/tests.py` 是 `config` 包的测试入口。

**为什么先做这个:** 前端(M2)要写统一的错误处理,后端必须先保证错误格式一致。改一处 EXCEPTION_HANDLER,全项目生效,后面每个接口都不用再操心。

- [x] **Step 1:写失败的测试**

新建 `chatapp/config/tests.py`:

```python
from rest_framework.test import APITestCase


class ErrorEnvelopeTests(APITestCase):
    def test_error_response_uses_code_message_envelope(self):
        resp = self.client.post("/api/v1/health")  # health 只允许 GET,触发 405
        self.assertEqual(resp.status_code, 405)
        self.assertEqual(resp.json()["code"], 405)
        self.assertIn("message", resp.json())
```

- [x] **Step 2:运行确认失败**

```bash
cd "D:/pycharmproject/chat_app/chatapp" && python manage.py test config
```

预期:FAIL(`KeyError: 'code'` —— 现在返回的是 DRF 默认的 `{"detail": ...}`)。

- [x] **Step 3:实现异常处理器**

新建 `chatapp/config/exceptions.py`:

```python
from rest_framework.views import exception_handler


def _first_message(data):
    """从 DRF 各种形状的错误数据里取第一条可读信息。"""
    if isinstance(data, dict):
        if "detail" in data:
            return str(data["detail"])
        for value in data.values():
            message = _first_message(value)
            if message:
                return message
        return "请求无效"
    if isinstance(data, (list, tuple)):
        for item in data:
            message = _first_message(item)
            if message:
                return message
        return "请求无效"
    return str(data)


def api_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        return None
    response.data = {"code": response.status_code, "message": _first_message(response.data)}
    return response
```

- [x] **Step 4:在 settings.py 挂上处理器 + 本地化**

`chatapp/config/settings.py` 里 `REST_FRAMEWORK` 字典增加一行:

```python
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    "EXCEPTION_HANDLER": "config.exceptions.api_exception_handler",
}
```

同文件把这两行改掉(DRF/Django 自带的提示语会因此变成中文,做国内 App 直接用中文更省事):

```python
LANGUAGE_CODE = "zh-hans"

TIME_ZONE = "Asia/Shanghai"
```

- [x] **Step 5:运行测试确认通过**

```bash
python manage.py test config
```

预期:`Ran 1 test ... OK`。

- [x] **Step 6:提交**

```bash
cd "D:/pycharmproject/chat_app" && git add chatapp/config && git commit -m "feat: unified {code,message} error envelope + zh-hans locale (M1a)"
```

---

### Task 2: 短信验证码服务 + `POST /auth/sms/send`

**Files:**
- Create: `chatapp/accounts/services.py`、`chatapp/accounts/serializers.py`、`chatapp/accounts/throttles.py`、`chatapp/accounts/urls.py`
- Modify: `chatapp/accounts/views.py`、`chatapp/accounts/tests.py`、`chatapp/config/api_urls.py`、`chatapp/config/settings.py`

**Interfaces:**
- Consumes: Task 1 的错误信封。
- Produces:
  - 缓存键约定:`sms:code:{phone}`(验证码,TTL 300s)、`sms:sent:{phone}`(重发锁,TTL 60s)、`sms:attempts:{phone}`(错误次数)、`sms:lock:{phone}`(锁定标记,TTL 900s)
  - `accounts.services.send_code(phone) -> str`(返回验证码,测试用)与 `accounts.services.check_code(phone, code)`(无返回值,失败抛 DRF 异常)
  - `POST /api/v1/auth/sms/send`,body `{"phone": "13800138000"}`,成功 `{"status": "ok"}`
  - `accounts.serializers.PhoneSerializer`(含手机号格式校验),Task 3 继承它

**为什么有 60 秒重发 + IP 限流两层:** 前者防"对着一个号码狂点"(业务规则,spec §10),后者防"换着号码刷"(用 DRF 自带限流,spec §10 要求)。开发期验证码固定在 settings,上线换腾讯云 SMS 时只改 `services.send_code` 一处。

- [x] **Step 1:写失败的测试**

`chatapp/accounts/tests.py` 顶部补 import,文件末尾追加:

```python
from unittest.mock import patch

from django.core.cache import cache

from accounts.throttles import SmsSendThrottle
from accounts import services


class SmsSendTests(APITestCase):
    def setUp(self):
        cache.clear()               # 缓存是进程级的,测试之间必须清
        self.addCleanup(cache.clear)

    def test_send_stores_code_and_returns_ok(self):
        resp = self.client.post("/api/v1/auth/sms/send", {"phone": "13800138000"}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok"})
        self.assertEqual(cache.get("sms:code:13800138000"), "123456")

    def test_send_twice_within_interval_is_throttled(self):
        self.client.post("/api/v1/auth/sms/send", {"phone": "13800138000"}, format="json")
        resp = self.client.post("/api/v1/auth/sms/send", {"phone": "13800138000"}, format="json")
        self.assertEqual(resp.status_code, 429)
        self.assertEqual(resp.json()["code"], 429)

    def test_send_invalid_phone_rejected(self):
        resp = self.client.post("/api/v1/auth/sms/send", {"phone": "12345"}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["code"], 400)

    def test_send_ip_throttle(self):
        # DRF 的 THROTTLE_RATES 是类属性快照,测试里直接临时改 rate 才生效
        with patch.object(SmsSendThrottle, "rate", "2/hour", create=True):
            for i in range(2):
                resp = self.client.post("/api/v1/auth/sms/send", {"phone": f"1380013800{i}"}, format="json")
                self.assertEqual(resp.status_code, 200)
            resp = self.client.post("/api/v1/auth/sms/send", {"phone": "13800138009"}, format="json")
            self.assertEqual(resp.status_code, 429)
```

- [x] **Step 2:运行确认失败**

```bash
python manage.py test accounts
```

预期:ERROR 一堆 —— 这一步 `accounts.services` / `accounts.throttles` 还不存在,测试文件会因为 import 失败整个加载不了(这是"红"得最彻底的一种:连跑都跑不起来)。等 Step 4/5 建完模块,再跑一次。

- [x] **Step 3:写设置项**

`chatapp/config/settings.py` 文件末尾追加:

```python
# --- 短信验证码(开发期模拟;上线接腾讯云 SMS 时改 services.send_code) ---
SMS_DEV_MODE = os.getenv("SMS_DEV_MODE", "1") == "1"   # 1=开发模式,验证码固定且只打日志
SMS_DEV_CODE = "123456"
SMS_CODE_TTL = 300          # 验证码有效期(秒)
SMS_RESEND_INTERVAL = 60    # 同一号码重发间隔(秒)
SMS_MAX_ATTEMPTS = 5        # 连续错误次数上限
SMS_LOCK_TTL = 900          # 触发上限后锁定时长(秒)

# --- 日志:开发期要能在终端看到验证码 ---
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {"accounts": {"handlers": ["console"], "level": "INFO"}},
}
```

`REST_FRAMEWORK` 字典再加一行:

```python
    "DEFAULT_THROTTLE_RATES": {"sms_send": "20/hour"},
```

- [x] **Step 4:写服务层**

新建 `chatapp/accounts/services.py`:

```python
import logging
import random

from django.conf import settings
from django.core.cache import cache
from rest_framework.exceptions import Throttled, ValidationError

logger = logging.getLogger(__name__)


def _code_key(phone):
    return f"sms:code:{phone}"


def _sent_key(phone):
    return f"sms:sent:{phone}"


def _attempts_key(phone):
    return f"sms:attempts:{phone}"


def _lock_key(phone):
    return f"sms:lock:{phone}"


def send_code(phone: str) -> str:
    if cache.get(_sent_key(phone)):
        raise Throttled(detail="发送太频繁,请稍后再试")
    if settings.SMS_DEV_MODE:
        code = settings.SMS_DEV_CODE
    else:
        code = f"{random.randint(0, 999999):06d}"
    cache.set(_code_key(phone), code, settings.SMS_CODE_TTL)
    cache.set(_sent_key(phone), 1, settings.SMS_RESEND_INTERVAL)
    cache.delete(_attempts_key(phone))   # 重新发码 = 重置错误计数;但不清 lock,防绕过锁定
    logger.info("[开发模式] 验证码 phone=%s code=%s", phone, code)
    return code


def check_code(phone: str, code: str) -> None:
    if cache.get(_lock_key(phone)):
        raise Throttled(detail="错误次数过多,请稍后再试")
    saved = cache.get(_code_key(phone))
    if saved is None:
        raise ValidationError("验证码已过期,请重新获取")
    if saved != code:
        attempts = cache.get(_attempts_key(phone), 0) + 1
        if attempts >= settings.SMS_MAX_ATTEMPTS:
            cache.set(_lock_key(phone), 1, settings.SMS_LOCK_TTL)
            cache.delete(_code_key(phone))
            raise Throttled(detail="错误次数过多,请稍后再试")
        cache.set(_attempts_key(phone), attempts, settings.SMS_CODE_TTL)
        raise ValidationError("验证码错误")
    cache.delete(_code_key(phone))
    cache.delete(_attempts_key(phone))
```

- [x] **Step 5:写序列化器、限流器、视图、路由**

新建 `chatapp/accounts/serializers.py`:

```python
import re

from rest_framework import serializers

PHONE_RE = re.compile(r"^1[3-9]\d{9}$")


class PhoneSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=20)

    def validate_phone(self, value):
        value = value.strip()
        if not PHONE_RE.match(value):
            raise serializers.ValidationError("手机号格式不正确")
        return value


class SmsVerifySerializer(PhoneSerializer):
    code = serializers.CharField(min_length=6, max_length=6)
```

新建 `chatapp/accounts/throttles.py`:

```python
from rest_framework.throttling import SimpleRateThrottle


class SmsSendThrottle(SimpleRateThrottle):
    """按 IP 限流发送验证码;额度在 settings.DEFAULT_THROTTLE_RATES["sms_send"]。"""

    scope = "sms_send"

    def get_cache_key(self, request, view):
        # SimpleRateThrottle 要求必须自己实现缓存键;这里按客户端 IP 计数
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}
```

新建 `chatapp/accounts/urls.py`:

```python
from django.urls import path

from . import views

urlpatterns = [
    path("sms/send", views.sms_send),
]
```

`chatapp/accounts/views.py` 追加:

```python
from rest_framework.decorators import api_view, permission_classes, throttle_classes

from . import services
from .serializers import PhoneSerializer
from .throttles import SmsSendThrottle


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([SmsSendThrottle])
def sms_send(request):
    serializer = PhoneSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    services.send_code(serializer.validated_data["phone"])
    return Response({"status": "ok"})
```

`chatapp/config/api_urls.py` 整体替换:

```python
from django.urls import include, path

from accounts.views import health

urlpatterns = [
    path("health", health),
    path("auth/", include("accounts.urls")),
]
```

- [x] **Step 6:运行测试确认通过**

```bash
python manage.py test accounts
```

预期:7 个用例(原有 3 个 + 新增 4 个)全部 OK。

- [x] **Step 7:提交**

```bash
cd "D:/pycharmproject/chat_app" && git add chatapp/accounts chatapp/config && git commit -m "feat: sms code service + /auth/sms/send (M1a)"
```

**卡点速查:**
- 报 `KeyError: 'sms_send'` → `DEFAULT_THROTTLE_RATES` 没加或拼错
- 429 出现在"不该 429"的测试里 → 上一个用例的缓存没清,检查 `setUp` 里的 `cache.clear()`
- LocMemCache 是进程内的:`runserver` 单进程没问题,但 `--noreload` 之外多开进程会各存一份(开发期可接受,上线换 Redis)

---

### Task 3: 登录注册 `POST /auth/sms/verify` + JWT 轮换刷新

**Files:**
- Modify: `chatapp/accounts/views.py`、`chatapp/accounts/urls.py`、`chatapp/accounts/tests.py`、`chatapp/config/settings.py`

**Interfaces:**
- Consumes: Task 2 的 `services.check_code`、`SmsVerifySerializer`;Task 2 的缓存键。
- Produces:
  - `POST /api/v1/auth/sms/verify`,body `{"phone","code"}` → `{"access","refresh","is_new_user","user_id"}`(手机号没注册过则自动建号)
  - `POST /api/v1/auth/token/refresh`,body `{"refresh"}` → `{"access","refresh"}`(旧 refresh 立即作废 = 轮换)
  - access 有效期 30 分钟、refresh 30 天 —— M2 前端拦截器按这个约定做静默刷新

**为什么 refresh 要轮换 + 黑名单:** 轮换让"偷来的 refresh 只能用一次且必然留下痕迹";黑名单让作废真正生效(SimpleJWT 需要 `token_blacklist` app 记黑名单表)。

- [x] **Step 1:写失败的测试**

`chatapp/accounts/tests.py` 顶部补 import(`from rest_framework_simplejwt.tokens import AccessToken, RefreshToken`;`services` 在 Task 2 已导入),末尾追加:

```python
class SmsVerifyTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.phone = "13800138000"

    def issue_code(self, phone=None):
        phone = phone or self.phone
        cache.delete(f"sms:sent:{phone}")   # 测试里绕过 60 秒重发间隔
        return services.send_code(phone)

    def verify(self, code, phone=None):
        return self.client.post("/api/v1/auth/sms/verify",
                                {"phone": phone or self.phone, "code": code}, format="json")

    def test_verify_creates_user_and_returns_tokens(self):
        code = self.issue_code()
        resp = self.verify(code)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["is_new_user"])
        user = User.objects.get(phone=self.phone)
        self.assertEqual(data["user_id"], user.id)
        self.assertEqual(AccessToken(data["access"])["user_id"], str(user.id))  # claim 是字符串

    def test_verify_second_time_is_not_new_user(self):
        self.verify(self.issue_code())
        code = self.issue_code()
        resp = self.verify(code)
        self.assertFalse(resp.json()["is_new_user"])
        self.assertEqual(User.objects.filter(phone=self.phone).count(), 1)

    def test_verify_wrong_code(self):
        self.issue_code()
        resp = self.verify("000000")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("message", resp.json())
        self.assertFalse(User.objects.filter(phone=self.phone).exists())

    def test_verify_expired_code(self):
        resp = self.verify("123456")   # 从没发过码
        self.assertEqual(resp.status_code, 400)

    def test_lock_after_five_failures(self):
        code = self.issue_code()
        for _ in range(5):
            self.verify("000000")
        resp = self.verify("000000")
        self.assertEqual(resp.status_code, 429)
        resp = self.verify(code)       # 锁定期间即使码对也不行
        self.assertEqual(resp.status_code, 429)
```

```python
class TokenRefreshTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = User.objects.create_user(phone="13800138000")

    def test_refresh_rotates_and_blacklists_old_token(self):
        old = str(RefreshToken.for_user(self.user))
        resp = self.client.post("/api/v1/auth/token/refresh", {"refresh": old}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("access", resp.json())
        new = resp.json()["refresh"]
        self.assertNotEqual(new, old)
        again = self.client.post("/api/v1/auth/token/refresh", {"refresh": old}, format="json")
        self.assertEqual(again.status_code, 401)
        self.assertEqual(again.json()["code"], 401)
```

- [x] **Step 2:运行确认失败**

```bash
python manage.py test accounts
```

预期:新用例 FAIL/ERROR(路由 404 / 老 refresh 还能再用)。

(另:`services` 已在 Task 2 导入,本步只需补 JWT 的 import。)

- [x] **Step 3:配置 JWT 轮换 + 黑名单**

`chatapp/config/settings.py`:

顶部 import 区加:

```python
from datetime import timedelta
```

`INSTALLED_APPS` 的「第三方」段加一行:

```python
    "rest_framework_simplejwt.token_blacklist",
```

文件末尾追加:

```python
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=30),
    "ROTATE_REFRESH_TOKENS": True,     # 每次刷新都换新 refresh
    "BLACKLIST_AFTER_ROTATION": True,  # 旧的立即拉黑
}
```

跑迁移(blacklist 需要建表):

```bash
python manage.py migrate
```

- [x] **Step 4:实现 verify 视图 + 刷新路由**

`chatapp/accounts/views.py` 追加(import 区补 `from django.contrib.auth import get_user_model`、`from rest_framework_simplejwt.tokens import RefreshToken`、`from .serializers import SmsVerifySerializer`):

```python
User = get_user_model()


@api_view(["POST"])
@permission_classes([AllowAny])
def sms_verify(request):
    serializer = SmsVerifySerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    phone = serializer.validated_data["phone"]
    services.check_code(phone, serializer.validated_data["code"])

    user, created = User.objects.get_or_create(phone=phone)
    refresh = RefreshToken.for_user(user)
    return Response({
        "access": str(refresh.access_token),
        "refresh": str(refresh),
        "is_new_user": created,
        "user_id": user.id,
    })
```

`chatapp/accounts/urls.py` 整体替换:

```python
from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from . import views

urlpatterns = [
    path("sms/send", views.sms_send),
    path("sms/verify", views.sms_verify),
    path("token/refresh", TokenRefreshView.as_view()),
]
```

- [x] **Step 5:运行测试确认通过**

```bash
python manage.py test accounts
```

预期:13 个用例全部 OK。

- [x] **Step 6:提交**

```bash
cd "D:/pycharmproject/chat_app" && git add chatapp/accounts chatapp/config && git commit -m "feat: sms verify login + JWT refresh rotation (M1a)"
```

**卡点速查:**
- `token_blacklist` 相关报错 → 忘了 `python manage.py migrate`
- 测试库建表失败 → 测试库 `test_chatapp_dev` 权限在 `db_setup.sql` 里已授权,确认没改过

---

### Task 4: users 模型(Profile/Tag/Photo/Preference)+ 标签种子

**Files:**
- Create: `chatapp/users/models.py`(覆盖模板)、`chatapp/users/migrations/0001_initial.py`(makemigrations 生成)、`chatapp/users/migrations/0002_seed_tags.py`、`chatapp/users/admin.py`(覆盖模板)
- Modify: `chatapp/users/tests.py`(覆盖模板)、`chatapp/requirements.txt`(加 Pillow)

**Interfaces:**
- Consumes: Task 1 的时区设置(用 `timezone.localdate()` 算年龄)。
- Produces:
  - `users.models`:`Gender`(male/female)、`ProfileStatus`(incomplete/complete/banned_light/banned_heavy)、`PhotoStatus`(pending/approved/rejected)、`Tag`、`Profile`(含 `age` 属性、`missing_fields()`、`refresh_status()`)、`Photo`(FK User,`related_name="photos"`)、`Preference`(1:1 Profile,`related_name="preference"`)
  - `calculate_age(birthday, today=None) -> int`(模块级函数,序列化器与测试都调它)
  - `Profile.missing_fields()` 返回缺失项英文名列表:`["nickname","gender","birthday","city","bio","photos"]` 的子集 —— M2 引导页照它提示用户
  - **完善判定规则(本计划定的产品规则,可改):** 昵称/性别/生日/城市/简介非空 + 至少 1 张 `approved` 照片 = `complete`;标签可选

**为什么 Tag 用数据迁移种而不是 fixture:** 迁移跟着 `migrate` 自动跑,测试库也自动有种子数据,少一个"记得执行"的步骤。

- [x] **Step 1:装 Pillow 并写失败的测试**

```bash
cd "D:/pycharmproject/chat_app/chatapp" && python -m pip install "Pillow>=10.0"
```

`chatapp/requirements.txt` 末尾加一行(手工编辑):

```text
Pillow>=10.0
```

`chatapp/users/tests.py` 整体替换:

```python
from datetime import date

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from .models import Photo, Profile, ProfileStatus, Tag, calculate_age

User = get_user_model()


class AgeTests(SimpleTestCase):
    def test_calculate_age_boundary(self):
        today = date(2026, 9, 10)
        self.assertEqual(calculate_age(date(2008, 9, 11), today), 17)   # 差一天
        self.assertEqual(calculate_age(date(2008, 9, 10), today), 18)   # 生日当天刚好 18


class ProfileModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(phone="13800138000")

    def test_new_profile_is_incomplete(self):
        profile = Profile.objects.create(user=self.user)
        self.assertEqual(profile.status, ProfileStatus.INCOMPLETE)
        self.assertIn("nickname", profile.missing_fields())
        self.assertIn("photos", profile.missing_fields())

    def test_refresh_status_does_not_override_ban(self):
        profile = Profile.objects.create(user=self.user, status=ProfileStatus.BANNED_HEAVY)
        profile.refresh_status()
        self.assertEqual(profile.status, ProfileStatus.BANNED_HEAVY)


class SeedTagTests(TestCase):
    def test_tags_seeded_by_migration(self):
        self.assertGreaterEqual(Tag.objects.count(), 10)
```

- [x] **Step 2:运行确认失败**

```bash
python manage.py test users
```

预期:ERROR(`Profile` 不存在)。

- [x] **Step 3:写模型**

`chatapp/users/models.py` 整体替换:

```python
from django.conf import settings
from django.db import models
from django.utils import timezone


def calculate_age(birthday, today=None):
    today = today or timezone.localdate()
    return today.year - birthday.year - ((today.month, today.day) < (birthday.month, birthday.day))


class Gender(models.TextChoices):
    MALE = "male", "男"
    FEMALE = "female", "女"


class ProfileStatus(models.TextChoices):
    INCOMPLETE = "incomplete", "未完善"
    COMPLETE = "complete", "已完善"
    BANNED_LIGHT = "banned_light", "轻度封禁"
    BANNED_HEAVY = "banned_heavy", "重度封禁"


class PhotoStatus(models.TextChoices):
    PENDING = "pending", "待审核"
    APPROVED = "approved", "已通过"
    REJECTED = "rejected", "已驳回"


class Tag(models.Model):
    name = models.CharField("名称", max_length=20, unique=True)
    icon = models.CharField("图标", max_length=50, blank=True)

    def __str__(self):
        return self.name


class Profile(models.Model):
    BANNED_STATUSES = (ProfileStatus.BANNED_LIGHT, ProfileStatus.BANNED_HEAVY)

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    nickname = models.CharField("昵称", max_length=20, blank=True)
    gender = models.CharField("性别", max_length=10, choices=Gender.choices, blank=True)
    birthday = models.DateField("生日", null=True, blank=True)
    city = models.CharField("城市", max_length=50, blank=True)
    bio = models.CharField("简介", max_length=200, blank=True)
    tags = models.ManyToManyField(Tag, blank=True, related_name="profiles")
    status = models.CharField("状态", max_length=20, choices=ProfileStatus.choices,
                              default=ProfileStatus.INCOMPLETE)

    def __str__(self):
        return f"{self.nickname or '?'}({self.user_id})"

    @property
    def age(self):
        return calculate_age(self.birthday) if self.birthday else None

    def missing_fields(self):
        missing = []
        if not self.nickname:
            missing.append("nickname")
        if not self.gender:
            missing.append("gender")
        if not self.birthday:
            missing.append("birthday")
        if not self.city:
            missing.append("city")
        if not self.bio:
            missing.append("bio")
        if not self.user.photos.filter(status=PhotoStatus.APPROVED).exists():
            missing.append("photos")
        return missing

    def refresh_status(self):
        """在 未完善/已完善 之间流转;封禁状态不被覆盖(M1b/M3 靠它兜底)。"""
        if self.status in self.BANNED_STATUSES:
            return
        new_status = ProfileStatus.COMPLETE if not self.missing_fields() else ProfileStatus.INCOMPLETE
        if new_status != self.status:
            self.status = new_status
            self.save(update_fields=["status"])


class Photo(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="photos")
    file = models.ImageField("图片", upload_to="photos/%Y/%m/")
    order = models.PositiveSmallIntegerField("排序", default=0)
    status = models.CharField("审核状态", max_length=10, choices=PhotoStatus.choices,
                              default=PhotoStatus.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"photo#{self.pk}({self.user_id})"


class Preference(models.Model):
    profile = models.OneToOneField(Profile, on_delete=models.CASCADE, related_name="preference")
    target_gender = models.CharField("想找的性别", max_length=10, choices=Gender.choices,
                                     null=True, blank=True)   # 空 = 不限
    age_min = models.PositiveSmallIntegerField("最小年龄", default=18)
    age_max = models.PositiveSmallIntegerField("最大年龄", default=99)
    city = models.CharField("城市", max_length=50, blank=True)

    def __str__(self):
        return f"preference({self.profile_id})"
```

- [x] **Step 4:生成迁移 + 写种子迁移**

```bash
python manage.py makemigrations users
```

新建 `chatapp/users/migrations/0002_seed_tags.py`:

```python
from django.db import migrations

TAGS = [
    ("运动", "sports"), ("音乐", "music"), ("电影", "movie"), ("旅行", "travel"),
    ("美食", "food"), ("宠物", "pet"), ("游戏", "game"), ("读书", "book"),
    ("摄影", "camera"), ("健身", "fitness"), ("动漫", "anime"), ("咖啡", "coffee"),
]


def seed(apps, schema_editor):
    Tag = apps.get_model("users", "Tag")
    for name, icon in TAGS:
        Tag.objects.get_or_create(name=name, defaults={"icon": icon})


def unseed(apps, schema_editor):
    Tag = apps.get_model("users", "Tag")
    Tag.objects.filter(name__in=[name for name, _ in TAGS]).delete()


class Migration(migrations.Migration):
    dependencies = [("users", "0001_initial")]
    operations = [migrations.RunPython(seed, unseed)]
```

```bash
python manage.py migrate
```

- [x] **Step 5:注册 admin(方便用户在后台看数据)**

`chatapp/users/admin.py` 整体替换:

```python
from django.contrib import admin

from .models import Photo, Preference, Profile, Tag


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "nickname", "gender", "city", "status")
    list_filter = ("status", "gender")
    search_fields = ("nickname", "user__phone")


@admin.register(Photo)
class PhotoAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "status", "order", "created_at")
    list_filter = ("status",)


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "icon")


@admin.register(Preference)
class PreferenceAdmin(admin.ModelAdmin):
    list_display = ("profile", "target_gender", "age_min", "age_max", "city")
```

- [x] **Step 6:运行测试确认通过**

```bash
python manage.py test users
```

预期:4 个用例 OK。

- [x] **Step 7:提交**

```bash
cd "D:/pycharmproject/chat_app" && git add chatapp/users chatapp/requirements.txt && git commit -m "feat: users models (Profile/Photo/Tag/Preference) + tag seed + admin (M1a)"
```

**卡点速查:**
- `fields.E210: Cannot use ImageField because Pillow is not installed` → 回 Step 1 装 Pillow
- 种子标签测试失败 → `0002_seed_tags.py` 没建或 `migrate` 没跑

---

### Task 5: `GET /users/me` + `GET /users/tags`

**Files:**
- Create: `chatapp/users/serializers.py`、`chatapp/users/urls.py`
- Modify: `chatapp/users/views.py`(覆盖模板)、`chatapp/users/tests.py`、`chatapp/config/api_urls.py`

**Interfaces:**
- Consumes: Task 4 的模型;Task 1 的信封;JWT(Bearer)。
- Produces:
  - `GET /api/v1/users/me` → 我的资料(自动创建空的 Profile),字段:`id, phone, nickname, gender, birthday, age, city, bio, status, missing_fields, tags[], photos[], preference{}`
  - `GET /api/v1/users/tags` → 标签池 `[{id,name,icon}]`
  - `users.views._get_profile(user)` 帮助函数(后续接口都复用)
  - `ProfileSerializer`(读)供后续 Task 复用

- [x] **Step 1:写失败的测试**

`chatapp/users/tests.py` 追加:

```python
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken


class AuthMixin:
    def login(self, user):
        refresh = RefreshToken.for_user(user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")


class MeTests(AuthMixin, APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(phone="13800138000")

    def test_requires_auth(self):
        resp = self.client.get("/api/v1/users/me")
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["code"], 401)

    def test_me_creates_profile_lazily(self):
        self.login(self.user)
        resp = self.client.get("/api/v1/users/me")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["phone"], "13800138000")
        self.assertEqual(data["status"], "incomplete")
        self.assertEqual(data["photos"], [])
        self.assertEqual(data["tags"], [])
        self.assertIn("nickname", data["missing_fields"])
        self.assertTrue(Profile.objects.filter(user=self.user).exists())

    def test_tags_pool(self):
        self.login(self.user)
        resp = self.client.get("/api/v1/users/tags")
        self.assertEqual(resp.status_code, 200)
        self.assertGreaterEqual(len(resp.json()), 10)
```

- [x] **Step 2:运行确认失败**

```bash
python manage.py test users
```

预期:3 个新用例 FAIL/ERROR(404)。

- [x] **Step 3:写序列化器**

新建 `chatapp/users/serializers.py`:

```python
from rest_framework import serializers

from .models import Photo, Preference, Profile, Tag


class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ["id", "name", "icon"]


class PhotoSerializer(serializers.ModelSerializer):
    url = serializers.ImageField(source="file", read_only=True)

    class Meta:
        model = Photo
        fields = ["id", "url", "status", "order"]


class PreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Preference
        fields = ["target_gender", "age_min", "age_max", "city"]


class ProfileSerializer(serializers.ModelSerializer):
    phone = serializers.CharField(source="user.phone", read_only=True)
    age = serializers.IntegerField(read_only=True)
    tags = TagSerializer(many=True, read_only=True)
    photos = PhotoSerializer(source="user.photos", many=True, read_only=True)
    preference = PreferenceSerializer(read_only=True)
    missing_fields = serializers.ListField(child=serializers.CharField(), read_only=True)

    class Meta:
        model = Profile
        fields = ["id", "phone", "nickname", "gender", "birthday", "age", "city", "bio",
                  "status", "missing_fields", "tags", "photos", "preference"]
```

注意:`photos` 用 `source="user.photos"`、`preference` 是反向 1:1 —— 如果 Profile 还没有 preference 记录,序列化 `preference` 会报 `RelatedObjectDoesNotExist`。所以 `_get_profile` 里要顺手把 preference 也建出来(Task 8 会正式用到)。

- [x] **Step 4:写视图与路由**

`chatapp/users/views.py` 整体替换:

```python
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import Preference, Profile, Tag
from .serializers import ProfileSerializer, TagSerializer


def _get_profile(user):
    profile, _ = Profile.objects.get_or_create(user=user)
    Preference.objects.get_or_create(profile=profile)
    return profile


@api_view(["GET"])
def me(request):
    profile = _get_profile(request.user)
    return Response(ProfileSerializer(profile, context={"request": request}).data)


@api_view(["GET"])
def tag_list(request):
    return Response(TagSerializer(Tag.objects.all(), many=True).data)
```

新建 `chatapp/users/urls.py`:

```python
from django.urls import path

from . import views

urlpatterns = [
    path("me", views.me),
    path("tags", views.tag_list),
]
```

`chatapp/config/api_urls.py` 整体替换:

```python
from django.urls import include, path

from accounts.views import health

urlpatterns = [
    path("health", health),
    path("auth/", include("accounts.urls")),
    path("users/", include("users.urls")),
]
```

- [x] **Step 5:运行测试确认通过**

```bash
python manage.py test users
```

预期:7 个用例全部 OK。

- [x] **Step 6:提交**

```bash
cd "D:/pycharmproject/chat_app" && git add chatapp/users chatapp/config && git commit -m "feat: GET /users/me + /users/tags (M1a)"
```

---

### Task 6: `PATCH /users/me`(更新资料 + 18 岁门槛 + 违规词)

**Files:**
- Create: `chatapp/moderation/text_check.py`
- Modify: `chatapp/users/serializers.py`、`chatapp/users/views.py`、`chatapp/users/tests.py`、`chatapp/moderation/tests.py`

**Interfaces:**
- Consumes: Task 4 的 `calculate_age`、`Tag`;Task 5 的 `ProfileSerializer`、`_get_profile`。
- Produces:
  - `PATCH /api/v1/users/me`,body 可含 `nickname / gender / birthday / city / bio / tag_ids`,返回更新后的完整资料(同 GET 格式)
  - `moderation.text_check.find_blocked_word(text) -> str | None` 与 `BLOCKED_WORDS` —— M3 会把它换成腾讯云文本审核 API,调用点不变
  - `users.serializers.ProfileUpdateSerializer`

**为什么 18 岁门槛在这里:** 注册只有手机号,拿不到年龄;首次填生日是唯一的合规卡点(spec §6/§8)。拒绝后资料保持原样,用户改不了假生日蒙混(除非真的改年份,这是 MVP 的固有限制)。

- [x] **Step 1:写失败的测试**

新建 `chatapp/moderation/tests.py`(替换模板):

```python
from django.test import SimpleTestCase

from .text_check import find_blocked_word


class TextCheckTests(SimpleTestCase):
    def test_detects_blocked_word_even_with_spaces(self):
        self.assertEqual(find_blocked_word("专业代 开发票"), "代开发票")

    def test_normal_text_passes(self):
        self.assertIsNone(find_blocked_word("喜欢音乐和旅行的设计师"))

    def test_empty_text_passes(self):
        self.assertIsNone(find_blocked_word(""))
```

`chatapp/users/tests.py` 追加:

```python
from django.utils import timezone


class ProfileUpdateTests(AuthMixin, APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(phone="13800138000")
        self.login(self.user)
        self.url = "/api/v1/users/me"

    def _full_profile(self, **overrides):
        data = {
            "nickname": "小明",
            "gender": "male",
            "birthday": "2000-01-01",
            "city": "上海",
            "bio": "喜欢音乐",
        }
        data.update(overrides)
        return data

    def test_update_fields(self):
        tag = Tag.objects.first()
        resp = self.client.patch(self.url, {**self._full_profile(), "tag_ids": [tag.id]}, format="json")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["nickname"], "小明")
        self.assertEqual(data["age"], calculate_age(date(2000, 1, 1)))
        self.assertEqual([t["id"] for t in data["tags"]], [tag.id])
        self.assertEqual(data["status"], "incomplete")   # 还差照片

    def test_partial_update_keeps_other_fields(self):
        self.client.patch(self.url, {"nickname": "小明"}, format="json")
        resp = self.client.patch(self.url, {"city": "北京"}, format="json")
        self.assertEqual(resp.json()["nickname"], "小明")
        self.assertEqual(resp.json()["city"], "北京")

    def test_underage_rejected_and_not_saved(self):
        too_young = f"{timezone.localdate().year - 17}-01-01"
        resp = self.client.patch(self.url, {"birthday": too_young}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIsNone(Profile.objects.get(user=self.user).birthday)

    def test_blocked_word_in_nickname_rejected(self):
        resp = self.client.patch(self.url, {"nickname": "代开发票找我"}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("message", resp.json())

    def test_unknown_tag_rejected(self):
        resp = self.client.patch(self.url, {"tag_ids": [999999]}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_invalid_gender_rejected(self):
        resp = self.client.patch(self.url, {"gender": "alien"}, format="json")
        self.assertEqual(resp.status_code, 400)
```

- [x] **Step 2:运行确认失败**

```bash
python manage.py test moderation users
```

预期:FAIL(`No module named 'moderation.text_check'`、PATCH 405)。

- [x] **Step 3:写词库**

新建 `chatapp/moderation/text_check.py`:

```python
"""开发期最小违规词库。上线前替换为腾讯云文本审核 API(M3),调用点保持不变。"""

BLOCKED_WORDS = ("赌博", "色情", "代开发票", "刷单", "贷款", "毒品")


def find_blocked_word(text: str) -> str | None:
    if not text:
        return None
    normalized = "".join(text.lower().split())   # 去掉空格/换行,防 "代 开发票" 绕过
    for word in BLOCKED_WORDS:
        if word in normalized:
            return word
    return None
```

- [x] **Step 4:写更新序列化器**

`chatapp/users/serializers.py` 的 import 区改成下面两行(原来只有 `from .models import Photo, Preference, Profile, Tag`),然后文件末尾追加序列化器:

```python
from moderation.text_check import find_blocked_word

from .models import Gender, Photo, Preference, Profile, Tag, calculate_age
```

```python
class ProfileUpdateSerializer(serializers.Serializer):
    nickname = serializers.CharField(max_length=20, required=False)
    gender = serializers.ChoiceField(choices=Gender.choices, required=False)
    birthday = serializers.DateField(required=False)
    city = serializers.CharField(max_length=50, required=False)
    bio = serializers.CharField(max_length=200, required=False)
    tag_ids = serializers.ListField(child=serializers.IntegerField(), required=False, allow_empty=True)

    def validate_nickname(self, value):
        if find_blocked_word(value):
            raise serializers.ValidationError("昵称包含违规内容,请修改")
        return value.strip()

    def validate_bio(self, value):
        if find_blocked_word(value):
            raise serializers.ValidationError("简介包含违规内容,请修改")
        return value.strip()

    def validate_birthday(self, value):
        if calculate_age(value) < 18:
            raise serializers.ValidationError("未满 18 周岁,无法使用本应用")
        return value

    def validate_tag_ids(self, value):
        unique_ids = set(value)
        if Tag.objects.filter(id__in=unique_ids).count() != len(unique_ids):
            raise serializers.ValidationError("存在无效的标签")
        return value
```

- [x] **Step 5:视图支持 PATCH**

`chatapp/users/views.py` 的 `me` 整体替换为:

```python
@api_view(["GET", "PATCH"])
def me(request):
    profile = _get_profile(request.user)
    if request.method == "PATCH":
        serializer = ProfileUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        tag_ids = data.pop("tag_ids", None)
        for field, value in data.items():
            setattr(profile, field, value)
        profile.save()
        if tag_ids is not None:
            profile.tags.set(Tag.objects.filter(id__in=tag_ids))
        profile.refresh_status()
    return Response(ProfileSerializer(profile, context={"request": request}).data)
```

import 区补 `from .serializers import ProfileSerializer, ProfileUpdateSerializer, TagSerializer`。

- [x] **Step 6:运行测试确认通过**

```bash
python manage.py test moderation users
```

预期:3 + 13 个用例全部 OK。

- [x] **Step 7:提交**

```bash
cd "D:/pycharmproject/chat_app" && git add chatapp/moderation chatapp/users && git commit -m "feat: PATCH /users/me with age gate and text wordlist (M1a)"
```

**卡点速查:**
- `test_underage_rejected_and_not_saved` 失败 → 确认视图是先 `is_valid(raise_exception=True)` 再落库(本例里序列化器校验失败根本进不了视图的保存逻辑)

---

### Task 7: 照片上传/删除 + AUTO_APPROVE + 完成状态流转

**Files:**
- Modify: `chatapp/users/serializers.py`、`chatapp/users/views.py`、`chatapp/users/urls.py`、`chatapp/users/tests.py`、`chatapp/config/settings.py`、`chatapp/config/urls.py`、`chatapp/.env.example`

**Interfaces:**
- Consumes: Task 4 的 `Photo`/`PhotoStatus`、`Profile.refresh_status()`;Task 5 的 `_get_profile`。
- Produces:
  - `POST /api/v1/users/me/photos`(multipart,字段名 `file`)→ 201 + `{id, url, status, order}`
  - `DELETE /api/v1/users/me/photos/{id}` → 204;只能删自己的,删别人/不存在都是 404
  - 设置项:`AUTO_APPROVE`(env,默认 1)、`PHOTO_MAX_COUNT=6`、`PHOTO_MAX_BYTES=5MB`
  - 开发期图片直接可通过,访问地址 `/media/...`;M3 把 `AUTO_APPROVE=0` 即走"待审"

- [x] **Step 1:写失败的测试**

`chatapp/users/tests.py` 顶部补 import:

```python
import base64
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings   # 这里真的要用 override_settings(AUTO_APPROVE 是普通设置项)
```

追加:

```python
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


class PhotoTests(AuthMixin, APITestCase):
    def setUp(self):
        self.media_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media_dir, ignore_errors=True)
        override = self.settings(MEDIA_ROOT=self.media_dir)   # 别把测试图片写进真 media/
        override.enable()
        self.addCleanup(override.disable)
        self.user = User.objects.create_user(phone="13800138000")
        self.login(self.user)
        self.url = "/api/v1/users/me/photos"

    def upload(self, name="a.png", content=PNG_1PX, content_type="image/png"):
        return self.client.post(self.url, {"file": SimpleUploadedFile(name, content, content_type=content_type)},
                                format="multipart")

    def fill_profile(self):
        return self.client.patch("/api/v1/users/me", {
            "nickname": "小明", "gender": "male", "birthday": "2000-01-01",
            "city": "上海", "bio": "喜欢音乐",
        }, format="json")

    def test_upload_auto_approved_in_dev(self):
        resp = self.upload()
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertEqual(data["status"], "approved")
        self.assertTrue(data["url"].startswith("http://testserver/media/"))

    def test_upload_rejects_non_image(self):
        resp = self.upload(name="a.txt", content=b"not an image", content_type="text/plain")
        self.assertEqual(resp.status_code, 400)

    def test_upload_limit_six(self):
        for i in range(6):
            self.assertEqual(self.upload(name=f"{i}.png").status_code, 201)
        self.assertEqual(self.upload(name="7.png").status_code, 400)

    def test_delete_own_photo_removes_file(self):
        photo_id = self.upload().json()["id"]
        resp = self.client.delete(f"{self.url}/{photo_id}")
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(Photo.objects.filter(id=photo_id).exists())

    def test_cannot_delete_others_photo(self):
        other = User.objects.create_user(phone="13900139000")
        photo = Photo.objects.create(user=other, file="photos/x.png")
        resp = self.client.delete(f"{self.url}/{photo.id}")
        self.assertEqual(resp.status_code, 404)

    def test_status_becomes_complete_with_approved_photo(self):
        self.fill_profile()
        self.assertEqual(self.client.get("/api/v1/users/me").json()["status"], "incomplete")
        self.upload()
        self.assertEqual(self.client.get("/api/v1/users/me").json()["status"], "complete")

    def test_status_returns_to_incomplete_after_photo_delete(self):
        self.fill_profile()
        photo_id = self.upload().json()["id"]
        self.client.delete(f"{self.url}/{photo_id}")
        self.assertEqual(self.client.get("/api/v1/users/me").json()["status"], "incomplete")

    @override_settings(AUTO_APPROVE=False)
    def test_pending_photo_when_auto_approve_off(self):
        self.fill_profile()
        self.assertEqual(self.upload().json()["status"], "pending")
        self.assertEqual(self.client.get("/api/v1/users/me").json()["status"], "incomplete")
```

- [x] **Step 2:运行确认失败**

```bash
python manage.py test users
```

预期:8 个新用例 FAIL/ERROR(404)。

- [x] **Step 3:写设置(MEDIA + 照片规则)**

`chatapp/config/settings.py` 文件末尾追加:

```python
# --- 照片 ---
AUTO_APPROVE = os.getenv("AUTO_APPROVE", "1") == "1"   # 开发期自动过审;上线接内容安全 API 后置 0
PHOTO_MAX_COUNT = 6
PHOTO_MAX_BYTES = 5 * 1024 * 1024

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
```

`chatapp/config/urls.py` 整体替换(开发期由 Django 直接伺服用户上传的图片):

```python
"""URL configuration for config project."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("config.api_urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
```

`chatapp/.env.example` 末尾追加(占位;`.env` 里可不加,默认就是 1):

```env
AUTO_APPROVE=1
SMS_DEV_MODE=1
```

- [x] **Step 4:写上传/删除接口**

`chatapp/users/serializers.py` 追加(顶部补 `from django.conf import settings`):

```python
class PhotoUploadSerializer(serializers.Serializer):
    file = serializers.ImageField()

    def validate_file(self, value):
        if value.size > settings.PHOTO_MAX_BYTES:
            raise serializers.ValidationError("图片不能超过 5MB")
        return value
```

`chatapp/users/views.py` 的 import 区改成下面这样(顶部新增三行,`.models` 行补齐),然后追加两个视图:

```python
from django.conf import settings
from rest_framework.generics import get_object_or_404

from .models import Photo, PhotoStatus, Preference, Profile, Tag
from .serializers import (PhotoSerializer, PhotoUploadSerializer, ProfileSerializer,
                          ProfileUpdateSerializer, TagSerializer)
```

```python
@api_view(["POST"])
def upload_photo(request):
    serializer = PhotoUploadSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    count = request.user.photos.count()
    if count >= settings.PHOTO_MAX_COUNT:
        return Response({"code": 400, "message": f"最多上传 {settings.PHOTO_MAX_COUNT} 张照片"}, status=400)
    status = PhotoStatus.APPROVED if settings.AUTO_APPROVE else PhotoStatus.PENDING
    photo = Photo.objects.create(user=request.user, file=serializer.validated_data["file"],
                                 order=count, status=status)
    _get_profile(request.user).refresh_status()
    return Response(PhotoSerializer(photo, context={"request": request}).data, status=201)


@api_view(["DELETE"])
def delete_photo(request, photo_id):
    photo = get_object_or_404(request.user.photos, id=photo_id)
    photo.file.delete(save=False)   # 连磁盘文件一起删
    photo.delete()
    _get_profile(request.user).refresh_status()
    return Response(status=204)
```

注意:数量超限这里直接返回了 400 信封(没走异常路径),两种情况前端看到的响应完全一样。

`chatapp/users/urls.py` 整体替换:

```python
from django.urls import path

from . import views

urlpatterns = [
    path("me", views.me),
    path("me/photos", views.upload_photo),
    path("me/photos/<int:photo_id>", views.delete_photo),
    path("tags", views.tag_list),
]
```

- [x] **Step 5:运行测试确认通过**

```bash
python manage.py test users
```

预期:21 个用例全部 OK。

- [x] **Step 6:提交**

```bash
cd "D:/pycharmproject/chat_app" && git add chatapp/users chatapp/config chatapp/.env.example && git commit -m "feat: photo upload/delete with AUTO_APPROVE + profile completion (M1a)"
```

**卡点速查:**
- 上传返回 415/400 且提示 "Unsupported media type" → 测试里忘了 `format="multipart"`
- 图片 400 但文件明明是图片 → 检查 base64 常量是否被改动(Pillow 会真去解码它)
- 本地手动测试时图片 404 → `runserver` 需带 DEBUG=1(.env 里默认是),media 才由 Django 伺服

---

### Task 8: `GET/PATCH /users/me/preference`

**Files:**
- Modify: `chatapp/users/serializers.py`、`chatapp/users/views.py`、`chatapp/users/urls.py`、`chatapp/users/tests.py`

**Interfaces:**
- Consumes: Task 4 的 `Preference`、Task 5 的 `_get_profile`(已顺手创建 preference)、`PreferenceSerializer`。
- Produces: `GET/PATCH /api/v1/users/me/preference` → `{"target_gender": null|"male"|"female", "age_min": 18, "age_max": 99, "city": ""}`。M1b 的候选筛选读它;`target_gender=null` 表示不限。

- [x] **Step 1:写失败的测试**

`chatapp/users/tests.py` 追加:

```python
class PreferenceTests(AuthMixin, APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(phone="13800138000")
        self.login(self.user)
        self.url = "/api/v1/users/me/preference"

    def test_defaults(self):
        data = self.client.get(self.url).json()
        self.assertIsNone(data["target_gender"])
        self.assertEqual(data["age_min"], 18)
        self.assertEqual(data["age_max"], 99)
        self.assertEqual(data["city"], "")

    def test_update(self):
        resp = self.client.patch(self.url, {"target_gender": "female", "age_min": 22,
                                            "age_max": 30, "city": "上海"}, format="json")
        self.assertEqual(resp.status_code, 200)
        data = self.client.get(self.url).json()
        self.assertEqual(data["target_gender"], "female")
        self.assertEqual(data["age_min"], 22)
        self.assertEqual(data["age_max"], 30)
        self.assertEqual(data["city"], "上海")

    def test_invalid_range_rejected(self):
        resp = self.client.patch(self.url, {"age_min": 40, "age_max": 30}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_underage_range_rejected(self):
        resp = self.client.patch(self.url, {"age_min": 17}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_target_gender_null_means_any(self):
        self.client.patch(self.url, {"target_gender": "male"}, format="json")
        resp = self.client.patch(self.url, {"target_gender": None}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.json()["target_gender"])
```

- [x] **Step 2:运行确认失败**

```bash
python manage.py test users
```

预期:5 个新用例 FAIL(404)。

- [x] **Step 3:写校验与视图**

`chatapp/users/serializers.py` 的 `PreferenceSerializer` 整体替换为:

```python
class PreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Preference
        fields = ["target_gender", "age_min", "age_max", "city"]

    def validate_age_min(self, value):
        if value < 18:
            raise serializers.ValidationError("最小年龄不能小于 18")
        return value

    def validate(self, attrs):
        age_min = attrs.get("age_min", getattr(self.instance, "age_min", 18))
        age_max = attrs.get("age_max", getattr(self.instance, "age_max", 99))
        if age_min > age_max:
            raise serializers.ValidationError("最小年龄不能大于最大年龄")
        return attrs
```

`chatapp/users/views.py` 的 import 区把 `PreferenceSerializer` 加进 `.serializers` 那一行,然后追加:

```python
@api_view(["GET", "PATCH"])
def my_preference(request):
    profile = _get_profile(request.user)
    preference = profile.preference
    if request.method == "PATCH":
        serializer = PreferenceSerializer(preference, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
    return Response(PreferenceSerializer(preference).data)
```

`chatapp/users/urls.py` 在 `me/photos/<int:photo_id>` 之后加一行:

```python
    path("me/preference", views.my_preference),
```

- [x] **Step 4:运行测试确认通过**

```bash
python manage.py test users
```

预期:26 个用例全部 OK。

- [x] **Step 5:提交**

```bash
cd "D:/pycharmproject/chat_app" && git add chatapp/users && git commit -m "feat: preference endpoint (M1a)"
```

---

### Task 9: 全量验证 + curl 冒烟 + 文档收尾

**Files:**
- Modify: `chatapp/.env.example`(如有漏项)、`CLAUDE.md`
- 无新代码

**Interfaces:**
- Consumes: 前面全部 Task。
- Produces: 一份"照着敲就能复现"的冒烟记录;CLAUDE.md 更新到 M1a 状态;M1b 的交接说明。

- [x] **Step 1:全量测试 + 静态检查**

```bash
cd "D:/pycharmproject/chat_app/chatapp" && python manage.py check && python manage.py test
```

预期:`System check identified no issues`;全部用例 OK(accounts 13 + config 1 + users 26 + moderation 3 = 43 个)。

- [x] **Step 2:起服务,curl 冒烟**

终端 A:

```bash
cd "D:/pycharmproject/chat_app/chatapp" && python manage.py runserver
```

终端 B(Git Bash;`python` 用来解析 JSON):

```bash
cd "D:/pycharmproject/chat_app/chatapp"
curl -s -X POST http://127.0.0.1:8000/api/v1/auth/sms/send -H "Content-Type: application/json" -d '{"phone":"13800138000"}'
# 预期 {"status":"ok"};终端 A 的日志里能看到 [开发模式] 验证码

TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/v1/auth/sms/verify -H "Content-Type: application/json" \
  -d '{"phone":"13800138000","code":"123456"}' | python -c "import sys,json;print(json.load(sys.stdin)['access'])")
echo "$TOKEN"   # 应是一长串 JWT

curl -s -X PATCH http://127.0.0.1:8000/api/v1/users/me \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"nickname":"小明","gender":"male","birthday":"2000-01-01","city":"上海","bio":"喜欢音乐和旅行"}'
# 预期 status 仍是 incomplete,missing_fields 只剩 ["photos"]

python -c "import base64,pathlib;pathlib.Path('/tmp/smoke.png').write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='))"
curl -s -X POST http://127.0.0.1:8000/api/v1/users/me/photos \
  -H "Authorization: Bearer $TOKEN" -F "file=@/tmp/smoke.png"
# 预期 status=approved + url 形如 http://127.0.0.1:8000/media/photos/...

curl -s http://127.0.0.1:8000/api/v1/users/me -H "Authorization: Bearer $TOKEN"
# 预期 status 变成 complete

curl -s -X POST http://127.0.0.1:8000/api/v1/auth/sms/send -H "Content-Type: application/json" -d '{"phone":"12345"}'
# 预期 {"code":400,"message":"手机号格式不正确"}
```

冒烟完:Ctrl+C 停 runserver(⚠️ **确认没有残留的第二个 runserver 进程抢 8000**,排查命令见 CLAUDE.md);顺手删掉 `chatapp/media/photos/` 下这次上传的测试图(或整目录,反正 gitignore)。

⚠️ **实操踩坑(Git Bash + curl + 中文)**:`-d '{"nickname":"小明"}'` 里的中文会按本地 GBK 码页发出,服务端 UTF-8 解析失败 → `400 JSON parse error - 'utf-8' codec can't decode byte 0xc9`。这不是后端 bug。冒烟要么用纯 ASCII 值,要么把 JSON 写进 UTF-8 文件再 `--data-binary @body.json`:

```bash
python -c "import json,pathlib;pathlib.Path('body.json').write_text(json.dumps({'nickname':'小明','city':'上海'},ensure_ascii=False),encoding='utf-8')"
curl -s -X PATCH http://127.0.0.1:8001/api/v1/users/me -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json; charset=utf-8" --data-binary @body.json
```

**2026-09-10 实测记录**(8001 端口,避开用户占用的 8000):发码 → 登录(`is_new_user=true`)→ PATCH 资料(`status=incomplete`,`missing_fields=["photos"]`,`age=26`)→ 传照片(`status=approved`,url 为绝对地址)→ 再查资料(`status=complete`)→ 未满 18 生日 `{"code":400,"message":"未满 18 周岁,无法使用本应用"}`。全部符合预期;冒烟数据已从 dev 库清理(`Tag` 12 个种子保留)。

- [x] **Step 3:更新 CLAUDE.md**

在「当前进度」段落更新为 M1a 完成,并在「常用命令」附近补一小段接口清单(注册登录/资料/照片/偏好 + 错误格式约定),方便下个会话直接接手。注意 CLAUDE.md 里已有一句"下一步是 M1(后端业务全量)",改成"M1a 完成,M1b 待做(im + discovery)"。

- [x] **Step 4:提交**

```bash
cd "D:/pycharmproject/chat_app" && git add CLAUDE.md chatapp/.env.example && git commit -m "docs: M1a done — auth/profile APIs + error envelope (M1a)"
```

---

## M1a 验收清单(全部通过即进入 M1b 计划)

- [x] `python manage.py test` 全绿(43 个用例),`manage.py check` 无问题
- [x] `python manage.py migrate` 无待应用迁移;admin 里能看到 Tag 种子(12 个)
- [x] curl 冒烟:发码 → 登录拿 token → 改资料 → 传照片 → status=complete
- [x] 错误响应一律 `{"code": ..., "message": ...}`(401/400/429 各验一个)
- [x] `git status` 干净;`media/`、`.env` 未被提交
- [x] M1a 提交数:9 条左右,均在 `master` 上

## 留给 M1b 的接口约定(下一个计划直接用)

| 事项 | 约定 |
|---|---|
| IM 账号导入 | 注册成功后异步调 `im` 服务的 `account_import(f"u{user.id}")`,失败只记日志不阻塞 |
| userSig | `POST /api/v1/im/user_sig` → `{"user_sig": "..."}`;`banned_heavy` 用户 403 |
| 滑卡 | `POST /api/v1/discovery/swipe`,幂等;互喜同事务建 Match;命中时给双方发 `match_notice` 灰条 IM 消息 |
| 候选 | `GET /api/v1/discovery/candidates`;排除自己/划过/已配对/被拉黑;按 Preference 过滤,空则随机;只取 `status=complete` 且至少 1 张 approved 照片的人 |
| 会话预热 | `GET /api/v1/matches` 返回配对列表(userId→昵称/头像) |
| 封禁拦截 | `banned_light` 禁止滑卡;`banned_heavy` 业务接口 403 + 拒签 userSig(M1a 只存了状态,没做拦截) |
