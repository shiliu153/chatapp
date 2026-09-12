# 登录鉴权与接口标准化(第 1 期:基建 + 登录链路) 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 引入 Redis + Celery 基建,把短信登录链路改成「响应路径零外部调用 + 验证码 Redis 状态机 + 60 秒幂等重放窗口 + IM 副作用任务化」,消灭多机手测中 Broken pipe / 验证码后登录失败这一类问题。

**Architecture:** Redis 一份基建三用(Django 缓存、Celery broker、验证码/限流状态);验证码/HMAC 与原子校验走 Redis Lua 脚本;登录成功后经 `transaction.on_commit(..., robust=True)` 入队 `im.tasks.sync_login`,接口不再等待腾讯 REST;前端 verify 网络级失败自动重试一次(有重放窗口兜底)。

**Tech Stack:** Django 5.2 + DRF + MySQL + **新增:Redis 7(Docker)、django-redis、celery**;前端 Flutter 3.47.2(仅改 auth 两文件)。

**Spec:** `docs/superpowers/specs/2026-09-12-backend-standardization-design.md`

**期次说明:** 本计划覆盖 spec §4(基建)、§5(登录链路)、§6 错误码目录、§7(前端配套)、§8 测试基建(第 1、2 步落地)。spec §9 第 3 步(其余 IM 任务迁移 / request_id / 请求日志 / 限流维度 / 分页)、第 4 步(部署形态)、第 5 步(收尾)在本计划完成后另起计划。

## Global Constraints

- 后端 cwd = `chatapp/`,Python 用 anaconda 环境 `Django`(直接 `python`/`python manage.py`);前端 cwd = `app/`,命令一律 `../flutter/bin/flutter.bat`,**`flutter analyze` 必须零告警**
- **跑后端测试前置**:本机 Redis 已启动(`docker compose -f docker-compose.dev.yml up -d`);测试自动使用 Redis DB15(缓存)/DB14(broker),不碰开发数据
- **测试里任务永不真执行**:测试环境任务只入队(`.delay` 被 patch 或入队到 DB14,无 worker 消费);要测任务体就调 `.run(...)`;任何真实腾讯 REST 调用都必须 mock(`im.client.*`)
- `im/client.py` 的函数对外**永不抛异常**(失败返回 False 只记日志);要让 Celery 重试生效,由 `im/tasks.py` 把 False 转成异常
- **响应路径禁止外部调用**:`accounts/views.py` 的 send/verify 里不得出现任何 `requests`/IM REST 调用
- 提交信息用中文,沿用现有风格(`feat(chatapp):` / `test:` / `chore(chatapp):` / `docs:`);每步全绿再进下一步
- **不动 `flutter/`**(SDK 源码,独立 git);不动消息页/聊天页 UI;本计划**无数据库迁移**

---

### Task 1: Redis 基建(容器 + 缓存后端切换 + 测试隔离)

**Files:**
- Create: `chatapp/docker-compose.dev.yml`
- Modify: `chatapp/requirements.txt`
- Modify: `chatapp/config/settings.py`(顶部 `import sys`;`DATABASES` 块后追加「Redis / 缓存 / Celery」节)
- Modify: `chatapp/.env.example`
- Test: `chatapp/config/tests.py`(追加 `CacheBackendTests`)

**Interfaces:**
- Produces: `settings.REDIS_URL`、`settings.CELERY_BROKER_URL`、`settings.TESTING`;`CACHES["default"]` = django-redis(后续任务全部依赖)

- [x] **Step 1: 写失败测试**(`chatapp/config/tests.py` 末尾追加)

```python
from django.conf import settings
from django.core.cache import cache
from django.test import TestCase
from django_redis import get_redis_connection


class CacheBackendTests(TestCase):
    def test_default_cache_is_redis_and_roundtrips(self):
        self.assertIn("django_redis", settings.CACHES["default"]["BACKEND"])
        cache.set("cache:smoke", "ok", 10)
        self.assertEqual(cache.get("cache:smoke"), "ok")

    def test_testing_uses_isolated_redis_db(self):
        db = get_redis_connection("default").connection_pool.connection_kwargs["db"]
        self.assertEqual(db, 15)   # 测试绝不写开发库(DB0)
```

- [x] **Step 2: 跑测试确认失败**

Run: `cd chatapp && python manage.py test config`
Expected: FAIL — `ModuleNotFoundError: No module named 'django_redis'`

- [x] **Step 3: 装依赖 + 基建文件**

`chatapp/docker-compose.dev.yml`(新建):

```yaml
services:
  redis:
    image: redis:7-alpine
    container_name: chatapp-redis
    ports:
      - "6379:6379"
    command: ["redis-server", "--appendonly", "yes"]
    volumes:
      - redis-data:/data

volumes:
  redis-data:
```

`chatapp/requirements.txt` 追加:

```
celery>=5.4
redis>=5.0
django-redis>=5.4
```

安装:`pip install -r requirements.txt`(anaconda `Django` 环境);启动:`docker compose -f docker-compose.dev.yml up -d`。

`chatapp/config/settings.py` 改动:

1. 文件顶部(`from dotenv import load_dotenv` 之后)加 `import sys`(与现有 `import os` 同区)。
2. `DATABASES = {...}` 块之后追加:

```python
# --- Redis / 缓存 / Celery(2026-09-12 标准化:共享状态不许再用 LocMem) ---
TESTING = sys.argv[1:2] == ["test"]

REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://127.0.0.1:6379/1")
if TESTING:
    # 测试用独立 DB 序号:清库不误伤开发数据;任务只入队不执行(无 worker)
    REDIS_URL = "redis://127.0.0.1:6379/15"
    CELERY_BROKER_URL = "redis://127.0.0.1:6379/14"

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
```

`chatapp/.env.example` 追加(真 `.env` 也同步加,值可留默认):

```
REDIS_URL=redis://127.0.0.1:6379/0
CELERY_BROKER_URL=redis://127.0.0.1:6379/1
```

- [x] **Step 4: 跑测试确认通过**

Run: `cd chatapp && python manage.py test config`
Expected: PASS(2 个新用例)

- [x] **Step 5: 全量回归**

Run: `python manage.py test`
Expected: 全绿(此时业务逻辑未动,只是缓存后端换成了 Redis;DB15 与 MySQL 测试库同理隔离)

- [x] **Step 6: Commit**

```bash
git add chatapp/docker-compose.dev.yml chatapp/requirements.txt chatapp/config/settings.py chatapp/config/tests.py chatapp/.env.example
git commit -m "chore(chatapp): 引入 Redis 基建:缓存换 django-redis + Celery env + 测试独立 DB 隔离"
```

---

### Task 2: Celery 骨架 + ping 任务

**Files:**
- Create: `chatapp/config/celery.py`
- Modify: `chatapp/config/__init__.py`(现有内容是 pymysql shim,追加)
- Test: `chatapp/config/tests.py`(追加 `CelerySkeletonTests`)

**Interfaces:**
- Produces: `config.celery.app`(Celery 实例,autodiscover 各 app 的 `tasks.py`);后续任务 `@shared_task` 都挂在它上面

- [x] **Step 1: 写失败测试**(`chatapp/config/tests.py` 追加)

```python
from config.celery import ping


class CelerySkeletonTests(TestCase):
    def test_ping_task_returns_pong(self):
        self.assertEqual(ping.apply().get(), "pong")
```

- [x] **Step 2: 跑测试确认失败**

Run: `cd chatapp && python manage.py test config`
Expected: FAIL — `ModuleNotFoundError: No module named 'config.celery'`

- [x] **Step 3: 实现**

`chatapp/config/celery.py`(新建):

```python
"""Celery 应用:broker/配置全部从 Django settings(namespace=CELERY)读。"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("chatapp")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@app.task
def ping():
    return "pong"
```

`chatapp/config/__init__.py`(在现有 pymysql 两行之后追加):

```python
from .celery import app as celery_app

__all__ = ("celery_app",)
```

- [x] **Step 4: 跑测试确认通过**

Run: `cd chatapp && python manage.py test config`
Expected: PASS

- [x] **Step 5: 手动验证 worker 能起、能收任务**

```bash
cd chatapp
python -m celery -A config worker -l info --pool=solo   # 终端 A(Windows 必须 solo 池)
python manage.py shell -c "from config.celery import ping; ping.delay(); print('sent')"  # 终端 B
```

Expected: 终端 A 出现 `Task config.celery.ping[...] received` 与 `succeeded`;终端 B 打印 `sent`。

- [x] **Step 6: Commit**

```bash
git add chatapp/config/celery.py chatapp/config/__init__.py chatapp/config/tests.py
git commit -m "chore(chatapp): Celery 骨架(config/celery.py + ping 冒烟任务)"
```

---

### Task 3: 验证码状态机 `accounts/sms_codes.py`(HMAC + Redis Lua)

**Files:**
- Create: `chatapp/accounts/sms_codes.py`
- Modify: `chatapp/config/settings.py`(SMS 配置块加 `SMS_REPLAY_TTL`)
- Test: `chatapp/accounts/tests.py`(追加 `SmsCodeStateTests`)

**Interfaces:**
- Produces:`store(phone: str, code: str) -> None`、`verify(phone: str, code: str) -> CodeResult`、`delete(phone: str) -> None`、`CodeResult` 枚举(`OK/EXPIRED/WRONG/JUST_LOCKED/LOCKED`);Task 5 的 services 依赖这四个名字
- Consumes:Task 1 的 `CACHES`(经 `get_redis_connection("default")` 拿裸 redis 客户端)

- [x] **Step 1: 写失败测试**(`chatapp/accounts/tests.py` 追加;顶部 import 区补 `from django.conf import settings`、`from django_redis import get_redis_connection`、`from accounts import sms_codes`)

```python
class SmsCodeStateTests(TestCase):
    """验证码状态机:HMAC 存储 + Lua 原子校验 + 重放窗口。"""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.phone = "13800138000"

    def test_store_then_verify_ok(self):
        sms_codes.store(self.phone, "123456")
        self.assertIs(sms_codes.verify(self.phone, "123456"), sms_codes.CodeResult.OK)

    def test_verify_wrong_code(self):
        sms_codes.store(self.phone, "123456")
        self.assertIs(sms_codes.verify(self.phone, "000000"), sms_codes.CodeResult.WRONG)

    def test_verify_without_code_is_expired(self):
        self.assertIs(sms_codes.verify(self.phone, "123456"), sms_codes.CodeResult.EXPIRED)

    def test_five_wrong_attempts_lock(self):
        sms_codes.store(self.phone, "123456")
        for _ in range(settings.SMS_MAX_ATTEMPTS - 1):
            self.assertIs(sms_codes.verify(self.phone, "000000"), sms_codes.CodeResult.WRONG)
        self.assertIs(sms_codes.verify(self.phone, "000000"), sms_codes.CodeResult.JUST_LOCKED)
        self.assertIs(sms_codes.verify(self.phone, "123456"), sms_codes.CodeResult.LOCKED)

    def test_success_shrinks_ttl_to_replay_window_and_allows_replay(self):
        sms_codes.store(self.phone, "123456")
        sms_codes.verify(self.phone, "123456")
        ttl = get_redis_connection("default").ttl(f"sms:code:{self.phone}")
        self.assertLessEqual(ttl, settings.SMS_REPLAY_TTL)
        self.assertIs(sms_codes.verify(self.phone, "123456"), sms_codes.CodeResult.OK)

    def test_code_is_not_stored_in_plaintext(self):
        sms_codes.store(self.phone, "123456")
        stored = get_redis_connection("default").hgetall(f"sms:code:{self.phone}")
        self.assertNotIn(b"123456", stored.values())
```

- [x] **Step 2: 跑测试确认失败**

Run: `cd chatapp && python manage.py test accounts.tests.SmsCodeStateTests`
Expected: FAIL — `ModuleNotFoundError` / `AttributeError: module 'accounts.sms_codes' has no attribute ...`

- [x] **Step 3: 实现**

`chatapp/config/settings.py` SMS 配置块追加一行:

```python
SMS_REPLAY_TTL = 60         # 校验成功后的幂等重放窗口(秒):响应丢失时同码可再换令牌
```

`chatapp/accounts/sms_codes.py`(新建):

```python
"""验证码状态机:HMAC 存储 + Redis Lua 原子校验。

一个脚本内完成「锁检查 → 取码比对 → 失败计数 → 成功标记消费」,
并发 verify 只有一个能"首次消费",其余走重放分支(幂等窗口)。
"""

import hashlib
import hmac
from enum import Enum

from django.conf import settings
from django_redis import get_redis_connection

_SCRIPT_SOURCE = """
local code_key = KEYS[1]
local lock_key = KEYS[2]
if redis.call('EXISTS', lock_key) == 1 then
  return 4
end
if redis.call('EXISTS', code_key) == 0 then
  return 1
end
local saved = redis.call('HGET', code_key, 'h')
if saved ~= ARGV[1] then
  local n = redis.call('HINCRBY', code_key, 'n', 1)
  if n >= tonumber(ARGV[2]) then
    redis.call('SET', lock_key, '1', 'EX', tonumber(ARGV[3]))
    redis.call('DEL', code_key)
    return 3
  end
  return 2
end
redis.call('HSET', code_key, 'c', '1')
redis.call('EXPIRE', code_key, tonumber(ARGV[4]))
return 0
"""

_RESULTS = {
    0: "OK",
    1: "EXPIRED",
    2: "WRONG",
    3: "JUST_LOCKED",
    4: "LOCKED",
}

CodeResult = Enum("CodeResult", "OK EXPIRED WRONG JUST_LOCKED LOCKED")

_script = None


def _client():
    return get_redis_connection("default")


def _get_script():
    global _script
    if _script is None:
        _script = _client().register_script(_SCRIPT_SOURCE)   # EVALSHA,失败自动回退 EVAL
    return _script


def _keys(phone: str):
    return f"sms:code:{phone}", f"sms:lock:{phone}"


def digest(code: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), code.encode(), hashlib.sha256).hexdigest()


def store(phone: str, code: str) -> None:
    client = _client()
    key, _ = _keys(phone)
    client.hset(key, mapping={"h": digest(code), "n": 0, "c": 0})
    client.expire(key, settings.SMS_CODE_TTL)


def delete(phone: str) -> None:
    key, _ = _keys(phone)
    _client().delete(key)


def verify(phone: str, code: str) -> CodeResult:
    key, lock_key = _keys(phone)
    raw = _get_script()(
        keys=[key, lock_key],
        args=[digest(code), settings.SMS_MAX_ATTEMPTS,
              settings.SMS_LOCK_TTL, settings.SMS_REPLAY_TTL],
    )
    return CodeResult[_RESULTS[int(raw)]]
```

- [x] **Step 4: 跑测试确认通过**

Run: `cd chatapp && python manage.py test accounts.tests.SmsCodeStateTests`
Expected: PASS(6 个用例)

- [x] **Step 5: Commit**

```bash
git add chatapp/accounts/sms_codes.py chatapp/accounts/tests.py chatapp/config/settings.py
git commit -m "feat(chatapp): 验证码状态机(HMAC 存储 + Redis Lua 原子校验 + 60s 重放窗口)"
```

---

### Task 4: notifications app + 短信发送任务

**Files:**
- Create: `chatapp/notifications/__init__.py`、`apps.py`、`backends.py`、`tasks.py`
- Modify: `chatapp/config/settings.py`(`INSTALLED_APPS` 加 `"notifications"`)
- Test: `chatapp/notifications/tests.py`

**Interfaces:**
- Produces:`notifications.tasks.send_sms_code(phone, code)`(Celery 任务,重试 5 次指数退避)、`notifications.backends.get_sms_backend()`、`ConsoleSmsBackend.send_code(phone, code)`;Task 5 的 send 视图依赖它们
- Consumes:Task 2 的 Celery app(autodiscover)

- [x] **Step 1: 写失败测试**(`chatapp/notifications/tests.py` 新建)

```python
from unittest.mock import patch

from django.test import TestCase

from notifications.backends import ConsoleSmsBackend
from notifications.tasks import send_sms_code


class SmsBackendTests(TestCase):
    def test_console_backend_logs_code(self):
        with self.assertLogs("notifications", level="INFO") as captured:
            ConsoleSmsBackend().send_code("13800138000", "123456")
        self.assertIn("123456", captured.output[0])


class SendSmsCodeTaskTests(TestCase):
    def test_task_delegates_to_backend(self):
        with patch("notifications.tasks.get_sms_backend") as backend:
            send_sms_code.run("13800138000", "123456")
        backend.return_value.send_code.assert_called_once_with("13800138000", "123456")
```

- [x] **Step 2: 跑测试确认失败**

Run: `cd chatapp && python manage.py test notifications`
Expected: FAIL — `ModuleNotFoundError: No module named 'notifications'`

- [x] **Step 3: 实现**

`chatapp/notifications/__init__.py`:空文件。
`chatapp/notifications/apps.py`:

```python
from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "notifications"
```

`chatapp/notifications/backends.py`:

```python
"""短信后端:开发期只打日志;生产短信商(M4 接入)在这里加实现并由 settings 选择。"""

import logging
from django.conf import settings

logger = logging.getLogger(__name__)


class ConsoleSmsBackend:
    def send_code(self, phone: str, code: str) -> None:
        logger.info("[短信-控制台] phone=%s code=%s", phone, code)


def get_sms_backend():
    if settings.SMS_DEV_MODE:
        return ConsoleSmsBackend()
    return ConsoleSmsBackend()   # M4:按 settings.SMS_BACKEND 选生产实现
```

`chatapp/notifications/tasks.py`:

```python
from celery import shared_task

from .backends import get_sms_backend


@shared_task(autoretry_for=(Exception,), retry_backoff=True, retry_jitter=True, max_retries=5)
def send_sms_code(phone: str, code: str) -> None:
    get_sms_backend().send_code(phone, code)
```

`chatapp/config/settings.py` 的 `INSTALLED_APPS` 业务 app 区追加 `"notifications",`。

- [x] **Step 4: 跑测试确认通过**

Run: `cd chatapp && python manage.py test notifications`
Expected: PASS(2 个用例)

- [x] **Step 5: Commit**

```bash
git add chatapp/notifications chatapp/config/settings.py
git commit -m "feat(chatapp): notifications app + 短信发送任务(控制台后端,入队即回)"
```

---

### Task 5: IM 副作用任务 `im/tasks.py`

**Files:**
- Create: `chatapp/im/tasks.py`
- Test: `chatapp/im/tests.py`(追加 `ImTaskTests`)

**Interfaces:**
- Produces:`im.tasks.sync_login(user_id: int, created: bool)`、`im.tasks.import_account(user_id)`、`im.tasks.kick_user(user_id)`(均带重试:失败经 `_require` 抛异常触发 Celery 重试,max_retries=5 指数退避+抖动);Task 6 的登录视图依赖 `sync_login`
- Consumes:Task 2 的 Celery app(`shared_task` 自动发现);`im/client.py` 现成的 `import_account/kick_user`(参数是 `u{id}` 标识符,经 `User.im_user_id` 取)

- [x] **Step 1: 写失败测试**(`chatapp/im/tests.py` 追加;顶部 import 区补 `from django.contrib.auth import get_user_model` 与 `from im.tasks import kick_user, sync_login`)

```python
class ImTaskTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(phone="13800138000")

    def test_sync_login_imports_for_new_user(self):
        with patch("im.client.import_account", return_value=True) as imp:
            sync_login.run(self.user.id, True)
        imp.assert_called_once_with(self.user.im_user_id)

    def test_sync_login_kicks_for_existing_user(self):
        with patch("im.client.kick_user", return_value=True) as kick:
            sync_login.run(self.user.id, False)
        kick.assert_called_once_with(self.user.im_user_id)

    def test_failure_raises_so_celery_retries(self):
        with patch("im.client.kick_user", return_value=False):
            with self.assertRaises(RuntimeError):
                sync_login.run(self.user.id, False)

    def test_missing_user_is_noop(self):
        kick_user.run(999999)   # 不抛异常
```

- [x] **Step 2: 跑测试确认失败**

Run: `cd chatapp && python manage.py test im`
Expected: FAIL — `ModuleNotFoundError: No module named 'im.tasks'`

- [x] **Step 3: 实现**

`chatapp/im/tasks.py`(新建):

```python
"""IM 副作用任务:所有腾讯 REST 调用统一走这里,响应路径禁止直接调用。

im/client.py 的函数对外永不抛异常(失败返回 False 只记日志);
这里把 False 转成异常,让 Celery 的重试策略真正生效。
"""

import logging

from celery import shared_task
from django.contrib.auth import get_user_model

from . import client as im_client

logger = logging.getLogger(__name__)

RETRY_POLICY = dict(autoretry_for=(Exception,), retry_backoff=True,
                    retry_jitter=True, max_retries=5)


def _require(ok: bool, what: str) -> None:
    if not ok:
        raise RuntimeError(f"IM {what} 失败")


@shared_task(**RETRY_POLICY)
def import_account(user_id: int) -> None:
    user = get_user_model().objects.filter(id=user_id).first()
    if user is None:
        return
    _require(im_client.import_account(user.im_user_id), "account_import")


@shared_task(**RETRY_POLICY)
def kick_user(user_id: int) -> None:
    user = get_user_model().objects.filter(id=user_id).first()
    if user is None:
        return
    _require(im_client.kick_user(user.im_user_id), "kick")


@shared_task(**RETRY_POLICY)
def sync_login(user_id: int, created: bool) -> None:
    """登录后的 IM 侧整理:新号建号;老号踢掉旧 IM 会话(单设备登录)。"""
    if created:
        import_account(user_id)
    else:
        kick_user(user_id)
```

- [x] **Step 4: 跑测试确认通过**

Run: `cd chatapp && python manage.py test im`
Expected: PASS(新增 4 个用例 + 原有 im 用例全绿)

- [x] **Step 5: Commit**

```bash
git add chatapp/im/tasks.py chatapp/im/tests.py
git commit -m "feat(chatapp): IM 副作用任务层(im/tasks.py:建号/踢旧会话,失败可重试)"
```

---

### Task 6: accounts 服务/接口重构(send 入队 + verify 状态机 + 错误码)

**Files:**
- Create: `chatapp/config/error_codes.py`
- Modify: `chatapp/accounts/exceptions.py`
- Modify: `chatapp/accounts/services.py`(整体重写)
- Modify: `chatapp/accounts/views.py`(`sms_send`/`sms_verify`)
- Modify: `chatapp/im/views.py`(`user_sig` 加 IM 账号存在性保障)
- Test: `chatapp/accounts/tests.py`(改 `SmsSendTests`/`SmsVerifyTests`/`ImImportOnRegisterTests`/`SingleDeviceSessionTests`)

**Interfaces:**
- Produces:`services.issue_code(phone) -> str`、`services.rollback_send(phone) -> None`、`services.check_code(phone, code) -> None`(失败抛业务异常);异常类 `SmsCodeExpired/SmsCodeWrong/SmsLocked/SmsSendTooFrequent/SmsServiceUnavailable`
- Consumes:Task 3 的 `sms_codes`、Task 4 的 `send_sms_code` 任务、Task 5 的 `im.tasks.sync_login`

- [x] **Step 1: 改测试(先红)**

`chatapp/accounts/tests.py`:

1. `SmsSendTests` 顶部 import 区补 `from accounts import sms_codes`、`from unittest.mock import patch`(已有)。改写/新增:

```python
    def test_send_stores_code_and_returns_ok(self):
        with patch("notifications.tasks.send_sms_code.delay") as delay:
            resp = self.client.post("/api/v1/auth/sms/send", {"phone": "13800138000"}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok"})
        self.assertIs(sms_codes.verify("13800138000", "123456"), sms_codes.CodeResult.OK)
        delay.assert_called_once_with("13800138000", "123456")

    def test_send_twice_within_interval_is_throttled(self):
        with patch("notifications.tasks.send_sms_code.delay"):
            self.client.post("/api/v1/auth/sms/send", {"phone": "13800138000"}, format="json")
            resp = self.client.post("/api/v1/auth/sms/send", {"phone": "13800138000"}, format="json")
        self.assertEqual(resp.status_code, 429)
        self.assertEqual(resp.json()["code"], 42901)
        self.assertIn("Retry-After", resp.headers)

    def test_enqueue_failure_rolls_back_and_returns_503(self):
        with patch("notifications.tasks.send_sms_code.delay", side_effect=Exception("broker down")):
            resp = self.client.post("/api/v1/auth/sms/send", {"phone": "13800138000"}, format="json")
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json()["code"], 50301)
        # 已回滚:立刻重发应成功(而不是被 60 秒间隔卡住)
        with patch("notifications.tasks.send_sms_code.delay"):
            resp = self.client.post("/api/v1/auth/sms/send", {"phone": "13800138000"}, format="json")
        self.assertEqual(resp.status_code, 200)
```

2. `SmsVerifyTests` 的 `issue_code` 辅助改为 `sms_codes.store`(不再调 `services.send_code`):

```python
    def issue_code(self, phone=None):
        phone = phone or self.phone
        cache.delete(f"sms:send:{phone}")   # 测试里绕过 60 秒重发间隔的服务端占位
        sms_codes.store(phone, settings.SMS_DEV_CODE)
        return settings.SMS_DEV_CODE
```

3. `SmsVerifyTests` 断言错误码并新增重放用例:

```python
    def test_verify_wrong_code(self):
        self.issue_code()
        resp = self.verify("000000")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["code"], 40002)

    def test_verify_expired_code(self):
        resp = self.verify("123456")   # 从没发过码
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["code"], 40001)

    def test_lock_after_five_failures(self):
        code = self.issue_code()
        for _ in range(5):
            self.verify("000000")
        resp = self.verify("000000")
        self.assertEqual(resp.status_code, 429)
        self.assertEqual(resp.json()["code"], 42902)
        resp = self.verify(code)       # 锁定期间即使码对也不行
        self.assertEqual(resp.status_code, 429)

    def test_replay_within_window_issues_new_tokens(self):
        code = self.issue_code()
        first = self.verify(code)
        self.assertEqual(first.status_code, 200)
        second = self.verify(code)     # 60 秒重放窗口内:同码可再换令牌
        self.assertEqual(second.status_code, 200)
        self.assertNotEqual(first.json()["access"], second.json()["access"])
```

4. `ImImportOnRegisterTests` 的 `issue_code` 同样改为 `sms_codes.store` 版本(保持两处一致);三个用例改写为断言「入队」:

```python
    def test_new_user_triggers_sync_login(self):
        with patch("im.tasks.sync_login.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.verify()
        self.assertEqual(resp.status_code, 200)
        user = User.objects.get(phone=self.phone)
        delay.assert_called_once_with(user.id, True)

    def test_existing_login_triggers_sync_login(self):
        self.verify()
        with patch("im.tasks.sync_login.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                self.verify()
        user = User.objects.get(phone=self.phone)
        delay.assert_called_once_with(user.id, False)

    def test_enqueue_failure_does_not_break_login(self):
        with patch("im.tasks.sync_login.delay", side_effect=Exception("broker down")):
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.verify()
        self.assertEqual(resp.status_code, 200)   # on_commit(robust=True)兜住
```

5. `SingleDeviceSessionTests`:删除 `test_relogin_kicks_old_im_session` 与 `test_first_login_does_not_kick`(语义已被上面两个入队用例覆盖,`created` 参数即区分建号/踢会话)。

- [x] **Step 2: 跑测试确认失败**

Run: `cd chatapp && python manage.py test accounts`
Expected: 多个 FAIL(42901/50301/40001/40002 未实现、`sms:send` 键名变化等)

- [x] **Step 3: 实现**

`chatapp/config/error_codes.py`(新建):

```python
"""全局业务码目录:前 3 位与 HTTP 状态码一致,后 2 位为序号。"""

SESSION_CONFLICT = 40101          # 单设备登录冲突
SMS_CODE_EXPIRED = 40001          # 验证码过期/不存在
SMS_CODE_WRONG = 40002            # 验证码错误
SMS_SEND_TOO_FREQUENT = 42901     # 重发间隔未到
SMS_TOO_MANY_ATTEMPTS = 42902     # 错误次数过多被锁
SMS_SERVICE_UNAVAILABLE = 50301   # 短信任务入队失败
```

`chatapp/accounts/exceptions.py`(追加新异常;`SingleDeviceSessionConflict` 行为不变,仅把 `detail_code = 40101` 改为 `detail_code = error_codes.SESSION_CONFLICT`):

```python
from rest_framework.exceptions import Throttled

from config import error_codes


class SmsCodeExpired(APIException):
    status_code = 400
    default_detail = "验证码已过期,请重新获取"
    detail_code = error_codes.SMS_CODE_EXPIRED


class SmsCodeWrong(APIException):
    status_code = 400
    default_detail = "验证码错误"
    detail_code = error_codes.SMS_CODE_WRONG


class SmsLocked(APIException):
    status_code = 429
    default_detail = "错误次数过多,请稍后再试"
    detail_code = error_codes.SMS_TOO_MANY_ATTEMPTS


class SmsSendTooFrequent(Throttled):
    default_detail = "发送太频繁,请稍后再试"
    detail_code = error_codes.SMS_SEND_TOO_FREQUENT


class SmsServiceUnavailable(APIException):
    status_code = 503
    default_detail = "短信服务暂时不可用,请稍后重试"
    detail_code = error_codes.SMS_SERVICE_UNAVAILABLE
```

> 说明:全局处理器(`config/exceptions.py:28`)已支持 `detail_code` 透传;`Throttled` 子类由 DRF 自动附 `Retry-After`。

`chatapp/accounts/services.py`(整体重写):

```python
import logging
import random

from django.conf import settings
from django.core.cache import cache

from . import sms_codes
from .exceptions import SmsCodeExpired, SmsCodeWrong, SmsLocked, SmsSendTooFrequent

logger = logging.getLogger(__name__)


def _sent_key(phone):
    return f"sms:send:{phone}"


def issue_code(phone: str) -> str:
    """生成并存储验证码;入队由调用方负责(见 views.sms_send)。"""
    if not cache.add(_sent_key(phone), 1, settings.SMS_RESEND_INTERVAL):
        raise SmsSendTooFrequent(wait=settings.SMS_RESEND_INTERVAL)
    code = settings.SMS_DEV_CODE if settings.SMS_DEV_MODE else f"{random.randint(0, 999999):06d}"
    sms_codes.store(phone, code)
    logger.info("[开发模式] 验证码 phone=%s code=%s", phone, code)
    return code


def rollback_send(phone: str) -> None:
    """短信任务入队失败时回滚:删占位与码,让用户能立刻重试。"""
    cache.delete(_sent_key(phone))
    sms_codes.delete(phone)


def check_code(phone: str, code: str) -> None:
    """校验验证码;成功即通过(含 60 秒重放窗口内的重复校验)。"""
    result = sms_codes.verify(phone, code)
    if result is sms_codes.CodeResult.EXPIRED:
        raise SmsCodeExpired()
    if result is sms_codes.CodeResult.WRONG:
        raise SmsCodeWrong()
    if result in (sms_codes.CodeResult.LOCKED, sms_codes.CodeResult.JUST_LOCKED):
        raise SmsLocked()
```

`chatapp/accounts/views.py` 的 `sms_send`/`sms_verify` 改为:

```python
@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([SmsSendThrottle])
def sms_send(request):
    serializer = PhoneSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    phone = serializer.validated_data["phone"]
    code = services.issue_code(phone)
    try:
        send_sms_code.delay(phone, code)
    except Exception:
        # 入队失败用户拿不到码:回滚占位与码并 fail-closed,否则用户被 60 秒间隔卡死
        services.rollback_send(phone)
        logger.exception("短信任务入队失败 phone=%s", phone)
        raise SmsServiceUnavailable()
    return Response({"status": "ok"})


@api_view(["POST"])
@permission_classes([AllowAny])
def sms_verify(request):
    serializer = SmsVerifySerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    phone = serializer.validated_data["phone"]
    services.check_code(phone, serializer.validated_data["code"])

    user, created = User.objects.get_or_create(phone=phone)
    previous_version = user.session_version
    user.session_version = previous_version + 1
    user.save(update_fields=["session_version"])

    def _after_commit():
        # 响应路径不做外部调用:IM 建号/踢旧会话交给队列(robust=True:broker 抖动不 500)
        im_tasks.sync_login.delay(user.id, created)

    transaction.on_commit(_after_commit, robust=True)

    refresh = SessionRefreshToken.for_user(user)
    return Response({
        "access": str(refresh.access_token),
        "refresh": str(refresh),
        "is_new_user": created,
        "user_id": user.id,
    })
```

`chatapp/accounts/views.py` 顶部 import 区调整:删掉 `from im.client import import_account, kick_and_logout`,加

```python
import logging

from notifications.tasks import send_sms_code
from im import tasks as im_tasks

from .exceptions import SingleDeviceSessionConflict, SmsServiceUnavailable

logger = logging.getLogger(__name__)
```

`chatapp/im/views.py`(`user_sig` 加存在性保障;这是 IM 域自己的端点,首次同步建号幂等、失败不置标记):

```python
from django.conf import settings
from django.core.cache import cache
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .client import ensure_account
from .signature import gen_user_sig

IMPORTED_FLAG_TTL = 30 * 24 * 3600   # 30 天;Redis 清空后下次调用会幂等重建


@api_view(["POST"])
def user_sig(request):
    # 重封禁由全局权限类 IsNotHeavyBanned 拦下,这里不再重复检查
    user = request.user
    flag = f"im:imported:{user.id}"
    if not cache.get(flag) and ensure_account(user.im_user_id):
        cache.set(flag, 1, IMPORTED_FLAG_TTL)
    return Response({
        "user_sig": gen_user_sig(user.im_user_id),
        "sdkappid": settings.IM_SDKAPPID,
        "im_user_id": user.im_user_id,
        "expire": settings.IM_SIG_EXPIRE,
    })
```

- [x] **Step 4: 跑测试确认通过**

Run: `cd chatapp && python manage.py test accounts`
Expected: PASS(注意 `test_send_ip_throttle` 仍绿:IP 限流键走 Redis,`cache.clear()` 已隔离)

- [x] **Step 5: Commit**

```bash
git add chatapp/config/error_codes.py chatapp/accounts chatapp/im/views.py
git commit -m "feat(chatapp): 登录接口标准化(发送入队+回滚、verify 状态机与错误码、重放窗口、user_sig 保障)"
```

---


### Task 7: 前端 — verify 网络级失败自动重试一次 + 错误文案区分

**Files:**
- Modify: `app/lib/features/auth/auth_repository.dart`
- Modify: `app/lib/features/auth/login_page.dart`
- Test: `app/test/features/auth/login_page_test.dart`

**Interfaces:**
- Consumes:后端 60 秒重放窗口(同码可重试);`ApiException.statusCode == null` 即网络级失败(现有 `api_exception.dart` 语义)

- [x] **Step 1: 写失败测试**(`app/test/features/auth/login_page_test.dart` 追加;用文件内已有的 `pumpApp/ok/offline/profileJson` 辅助)

```dart
  testWidgets('verify 网络级失败 → 自动重试一次后成功进入主框架', (tester) async {
    var calls = 0;
    final adapter = ScriptedAdapter({
      'POST /auth/sms/verify': (options) {
        calls++;
        if (calls == 1) return offline(options);   // 第一次断网
        return ok({'access': 'a', 'refresh': 'r', 'is_new_user': false, 'user_id': 7});
      },
      'GET /users/me': (options) => ok(profileJson()),
    });
    await pumpApp(tester, adapter);
    await tester.pumpAndSettle();

    await tester.enterText(find.byKey(const Key('login.phone')), '13800138000');
    await tester.enterText(find.byKey(const Key('login.code')), '123456');
    await tester.tap(find.byKey(const Key('login.submit')));
    await tester.pumpAndSettle();

    expect(calls, 2);                                    // 重试了一次
    expect(find.byType(NavigationBar), findsOneWidget);  // 进主框架
  });

  testWidgets('verify 网络两次都失败 → 提示可直接再点登录', (tester) async {
    final adapter = ScriptedAdapter({'POST /auth/sms/verify': (options) => offline(options)});
    await pumpApp(tester, adapter);
    await tester.pumpAndSettle();

    await tester.enterText(find.byKey(const Key('login.phone')), '13800138000');
    await tester.enterText(find.byKey(const Key('login.code')), '123456');
    await tester.tap(find.byKey(const Key('login.submit')));
    await tester.pumpAndSettle();

    expect(find.text('网络超时,可直接再次点击「登录」重试'), findsOneWidget);
  });

  testWidgets('verify 业务错误(码过期)不重试', (tester) async {
    var calls = 0;
    final adapter = ScriptedAdapter({
      'POST /auth/sms/verify': (options) {
        calls++;
        return jsonError(400, '验证码已过期,请重新获取');
      },
    });
    await pumpApp(tester, adapter);
    await tester.pumpAndSettle();

    await tester.enterText(find.byKey(const Key('login.phone')), '13800138000');
    await tester.enterText(find.byKey(const Key('login.code')), '123456');
    await tester.tap(find.byKey(const Key('login.submit')));
    await tester.pumpAndSettle();

    expect(calls, 1);
    expect(find.text('验证码已过期,请重新获取'), findsOneWidget);
  });
```

- [x] **Step 2: 跑测试确认失败**

Run: `cd app && ../flutter/bin/flutter.bat test test/features/auth/login_page_test.dart`
Expected: FAIL — 第一个用例 `calls` 为 1;第二个用例找不到新文案

- [x] **Step 3: 实现**

`app/lib/features/auth/auth_repository.dart`:

```dart
  Future<LoginResult> verifySms(String phone, String code) async {
    try {
      return await _verify(phone, code);
    } on ApiException catch (error) {
      // 网络级失败(无 HTTP 状态码)自动重试一次:服务端有 60 秒幂等重放窗口,同码安全
      if (error.statusCode != null) rethrow;
      return _verify(phone, code);
    }
  }

  Future<LoginResult> _verify(String phone, String code) async {
    final data = await _api.post('/auth/sms/verify', data: {'phone': phone, 'code': code});
    return LoginResult.fromJson(data as Map<String, dynamic>);
  }
```

(文件顶部 import 补 `import '../../core/api_exception.dart';`)

`app/lib/features/auth/login_page.dart` 的 `_submit` 错误分支改为:

```dart
    } on ApiException catch (error) {
      if (mounted) {
        _show(error.statusCode == null ? '网络超时,可直接再次点击「登录」重试' : error.message);
      }
    }
```

- [x] **Step 4: 跑测试确认通过**

Run: `cd app && ../flutter/bin/flutter.bat test test/features/auth/`
Expected: PASS(新增 3 个用例 + 原有全绿)

- [x] **Step 5: 全量前端测试 + analyze**

Run: `cd app && ../flutter/bin/flutter.bat test && ../flutter/bin/flutter.bat analyze`
Expected: 全绿、零告警

- [x] **Step 6: Commit**

```bash
git add app/lib/features/auth/auth_repository.dart app/lib/features/auth/login_page.dart app/test/features/auth/login_page_test.dart
git commit -m "feat(app): 登录 verify 网络级失败自动重试一次 + 超时文案区分(配合服务端重放窗口)"
```

---

### Task 8: 收尾(双端全量回归 + 双模拟器手测 + 文档)

**Files:**
- Modify: `CLAUDE.md`(常用命令 + 新机制/坑)
- Test: 手工清单(见下)

- [x] **Step 1: 后端全量回归**

Run: `cd chatapp && python manage.py test`
Expected: 全绿(含新增:缓存隔离 2、状态机 6、短信任务 2、IM 任务 4、accounts 改造用例)

- [x] **Step 2: 双模拟器手测(需 Redis 容器 + worker + runserver 三者同跑)**

```bash
cd chatapp
docker compose -f docker-compose.dev.yml up -d
python manage.py runserver 0.0.0.0:8000 --noreload        # 终端 A(手测期避免 autoreload 自污染)
python -m celery -A config worker -l info --pool=solo     # 终端 B
```

手测清单:
1. 5554 请求验证码 → 终端 B 出现 `[短信-控制台] phone=... code=123456`;登录成功(响应应明显变快,无 0.5s 级等待);
2. 5556 同号登录 → 5554 被顶下线(既有链路不回退);
3. 关掉终端 B(worker 停)→ 接口**不受影响**(任务只是堆在 broker);重启 worker 后队列里的短信任务被消费、终端 B 补打验证码(验证「入队」与「执行」已解耦);
4. 5556 杀进程重启 App 再登录 → 不出现「验证码已过期」死循环;
5. 新号注册登录 → 终端 B 出现 `im.tasks.sync_login` 执行(建号)。

- [x] **Step 3: 更新 CLAUDE.md**

至少加三处:
- 「常用命令」后端块:`docker compose -f docker-compose.dev.yml up -d`(Redis)、`python -m celery -A config worker -l info --pool=solo`(worker,Windows 必须 solo)、测试前置 Redis 一句;
- 新节「接口标准化(2026-09-12)」:响应路径禁外部调用、`transaction.on_commit(fn, robust=True)` 只用于入队、验证码状态机与 60s 重放窗口、错误码目录(`config/error_codes.py`,前 3 位=HTTP 状态)、`im/tasks.py` 是唯一 IM 副作用入口、测试里任务只入队不执行(`.run()` 测任务体);
- 「验证码/限流计数存在 LocMem」旧坑改为:已迁 Redis(DB0),测试用 DB15。

- [x] **Step 4: 全量前端回归 + analyze**

Run: `cd app && ../flutter/bin/flutter.bat test && ../flutter/bin/flutter.bat analyze`
Expected: 全绿、零告警

- [x] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: 登录鉴权标准化落地(Redis+Celery 基建/验证码状态机/IM 任务化)写入 CLAUDE.md"
```

---

## 执行记录(2026-09-12)

- Task 1–7 全部完成:后端 224 / 前端 154 测试全绿,`flutter analyze` 零告警;8 个提交在分支 `backend-standardization`。
- Task 8 Step 1/3/4/5 完成(回归 + CLAUDE.md 文档)。
- **Task 8 Step 2(双模拟器手测)待用户执行**。此前已用 curl 做过端到端验证:
  - 发码 `POST /auth/sms/send` 200 / 107ms,`notifications.tasks.send_sms_code` 在 worker 侧执行;
  - 登录 200 且响应路径不等腾讯;worker 侧 `im.tasks.sync_login`(踢旧 IM 会话)0.75s 完成;
  - **60 秒窗口内同码重放 200 / 40ms**(旧版本此时会回「验证码已过期」)。

### 手测补记(2026-09-12 晚)

- 双模拟器手测通过(登录变快 / 新号注册 / 顶号 / 踢下线链路);期间发现并修复两个真 bug:
  1. **测试任务漏进开发 broker**(`8020cd2`):`.env` 里用 `CELERY_BROKER_URL` 会被 Celery 的
     「环境变量优先」压过 settings 的 TESTING 覆盖 → 环境变量改名 `BROKER_URL` + 回归用例;
  2. **自我踢下线回归**(`8c30e1b`):踢旧 IM 会话做成「响应后异步」会踢掉新设备刚建的会话,
     客户端误报「账号已在其他设备登录」→ 改为 verify 写 `im:kick_pending` 标记、
     `/im/user_sig` 同步踢后再发签名 + 20s 延迟兜底任务。
- 用户在模拟器复测确认正常;日志核对:kick 标记被 user_sig 消费、兜底任务空转、
  全程无 40101、429 后用同一验证码重放登录成功(60s 幂等窗口生效)。
