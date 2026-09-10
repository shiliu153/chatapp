# M1b IM 与滑卡配对(后端)实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 后端补齐 MVP 闭环的最后一段:`im`(userSig 签发、账号导入、配对灰条消息)+ `discovery`(候选推荐、滑卡、互喜配对、配对列表),接口有测试、全绿,并用真实腾讯云 IM 跑通冒烟。

**Architecture:** `im` 是纯客户端模块(无模型):`signature.py` 生成 userSig(腾讯自定义 base64 变体,算法已在 M0 实测通过),`client.py` 封装 REST 调用(REST 一律以管理员 `administrator` 身份调用,消息发送方靠 body 的 `From_Account` 指定),失败只记日志不抛异常。`discovery` 承载业务:`Swipe` 记录划卡(唯一约束保证幂等),`Match` 用有序对 + 唯一约束 + CheckConstraint 保证并发互喜只配对一次;配对成功在事务提交后给双方各发一条 `TIMCustomElem`(M2 渲染成居中灰条,会话随之创建)。候选按 `Preference` 过滤,不设则全量随机。

**Tech Stack:** 承接 M1a(Django 5.2 + DRF + SimpleJWT + MySQL 8);新增 `requests`(腾讯云 IM REST 调用,环境里已有 2.32.5,只需写进 requirements)。

**本计划的范围边界:**
- 本计划**不做**(留给 M3):`Block`/`Report` 模型与拉黑举报接口、IM 黑名单同步、审核台、用户协议文本。因此候选查询暂不排除"被拉黑的人"(此时还不存在任何拉黑记录)。
- 本计划**不做**:IM 回调接收端点(spec §6 里标注为「预留」,等上线部署有公网地址、要走 HTTPS 时再补)。
- 本计划**只做后端**:Flutter 端 IM SDK 接入、聊天 UI、卡片 UI 全在 M2。
- 封禁拦截在 M1b 落地:`banned_light` 禁滑卡(403);`banned_heavy` 禁滑卡 + 拒签 userSig(403)。**没有后台封禁入口**(M3 的审核台才有),测试里直接改 `Profile.status` 造数据。

## Global Constraints

- 承接 M1a 全部约定:Windows Git Bash、`python` = anaconda 环境 `Django`、Django 命令 cwd = `D:\pycharmproject\chat_app\chatapp`、严禁改 `flutter/` 与 `app/`
- 每个 Task 结束必须 `git commit`,消息格式 `feat: ... (M1b)` / `chore: ... (M1b)`
- **接口约定不变**:成功 = HTTP 2xx + 资源 JSON;失败 = `{"code": <状态码>, "message": "<中文>"}`;鉴权 `Authorization: Bearer <access>`
- **测试里禁止真实网络**:IM REST 一律 mock(`requests.post` 或 `im.client._request` 层),只有 Task 9 的冒烟脚本打真接口
- IM 凭据只在 `.env`(`IM_SDKAPPID` / `IM_SECRETKEY` 已就位);代码只读 `settings`,永不硬编码
- IM userID 约定:`u{User.id}`(由 `User.im_user_id` 属性统一提供,**禁止**各处手拼)
- 时间/时区:一切"今天/年龄"计算走 `django.utils.timezone.localdate()`
- 用户是 Django 新手:每步给命令与预期输出,报错先看「卡点速查」

---

### Task 1: userSig 生成(`im/signature.py`)

**Files:**
- Create: `chatapp/im/signature.py`
- Modify: `chatapp/config/settings.py`(IM 配置块)、`chatapp/requirements.txt`(+requests)、`chatapp/im/tests.py`(覆盖模板)

**Interfaces:**
- Consumes: `.env` 里的 `IM_SDKAPPID` / `IM_SECRETKEY`。
- Produces:
  - `im.signature.gen_user_sig(identifier, expire=None, now=None) -> str`
  - `im.signature.decode_user_sig(sig) -> dict`(调试/测试用:还原成明文 JSON)
  - settings:`IM_SDKAPPID`、`IM_SECRETKEY`、`IM_ADMIN_IDENTIFIER`(默认 `administrator`)、`IM_REST_BASE`、`IM_SIG_EXPIRE`(7 天)、`IM_TIMEOUT`(5 秒)

**为什么单独一个模块:** userSig 是全网最容易踩坑的地方(腾讯用自家 base64 变体:**标准** base64 后再把 `+`→`*`、`/`→`-`、`=`→`_`),把它与网络调用分开,测试能直接断言"编码后能原样解回来、sig 字段等于官方 HMAC 公式"。

- [x] **Step 1:补依赖与设置**

`chatapp/requirements.txt` 末尾加一行:

```text
requests>=2.31
```

`chatapp/config/settings.py` 文件末尾追加:

```python
# --- 腾讯云 IM REST(凭据只在 .env) ---
IM_SDKAPPID = os.getenv("IM_SDKAPPID", "")
IM_SECRETKEY = os.getenv("IM_SECRETKEY", "")
IM_ADMIN_IDENTIFIER = os.getenv("IM_ADMIN_IDENTIFIER", "administrator")
IM_REST_BASE = "https://console.tim.qq.com/v4"
IM_SIG_EXPIRE = 7 * 24 * 3600   # userSig 有效期(秒),腾讯上限 180 天
IM_TIMEOUT = 5                  # REST 超时(秒)
```

- [x] **Step 2:写失败的测试**

`chatapp/im/tests.py` 整体替换:

```python
from django.test import SimpleTestCase, override_settings

from .signature import _hmac_sha256, decode_user_sig, gen_user_sig

IM_TEST_SETTINGS = dict(
    IM_SDKAPPID="1400000000",
    IM_SECRETKEY="k" * 32,
    IM_ADMIN_IDENTIFIER="administrator",
    IM_SIG_EXPIRE=604800,
    IM_REST_BASE="https://console.tim.qq.com/v4",
    IM_TIMEOUT=5,
)


@override_settings(**IM_TEST_SETTINGS)
class UserSigTests(SimpleTestCase):
    def test_encode_then_decode_keeps_fields(self):
        sig = gen_user_sig("u1", now=1700000000)
        doc = decode_user_sig(sig)
        self.assertEqual(doc["TLS.ver"], "2.0")
        self.assertEqual(doc["TLS.identifier"], "u1")
        self.assertEqual(doc["TLS.sdkappid"], 1400000000)
        self.assertEqual(doc["TLS.time"], 1700000000)
        self.assertEqual(doc["TLS.expire"], 604800)

    def test_sig_field_matches_official_hmac_formula(self):
        sig = gen_user_sig("u1", now=1700000000)
        doc = decode_user_sig(sig)
        expected = _hmac_sha256("u1", 1400000000, 1700000000, 604800, "k" * 32)
        self.assertEqual(doc["TLS.sig"], expected)

    def test_uses_tencent_base64_variant(self):
        sig = gen_user_sig("u1")
        for ch in "+/=":
            self.assertNotIn(ch, sig)
```

- [x] **Step 3:运行确认失败**

```bash
cd "D:/pycharmproject/chat_app/chatapp" && python manage.py test im
```

预期:ERROR(`No module named 'im.signature'`)。

- [x] **Step 4:实现**

新建 `chatapp/im/signature.py`:

```python
"""腾讯云 IM userSig 生成。

坑点:腾讯用自家 base64 变体 —— 整体流程是
JSON(ver/identifier/sdkappid/expire/time/sig) → json.dumps → zlib.compress
→ 标准 base64 → 把 + / = 分别替换成 * - _。
注意 sig 字段本身用的是**标准** base64 的 HMAC-SHA256,不要一起替换。
"""

import base64
import hashlib
import hmac
import json
import time
import zlib

from django.conf import settings


def _b64_variant(raw: bytes) -> str:
    return base64.b64encode(raw).decode().replace("+", "*").replace("/", "-").replace("=", "_")


def _b64_variant_decode(text: str) -> bytes:
    return base64.b64decode(text.replace("*", "+").replace("-", "/").replace("_", "="))


def _hmac_sha256(identifier: str, sdkappid: int, curr_time: int, expire: int, key: str) -> str:
    content = (
        f"TLS.identifier:{identifier}\n"
        f"TLS.sdkappid:{sdkappid}\n"
        f"TLS.time:{curr_time}\n"
        f"TLS.expire:{expire}\n"
    )
    digest = hmac.new(key.encode(), content.encode(), hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def gen_user_sig(identifier: str, expire: int | None = None, now: int | None = None) -> str:
    sdkappid = int(settings.IM_SDKAPPID)
    expire = expire or settings.IM_SIG_EXPIRE
    curr_time = now or int(time.time())
    sig_doc = {
        "TLS.ver": "2.0",
        "TLS.identifier": identifier,
        "TLS.sdkappid": sdkappid,
        "TLS.expire": expire,
        "TLS.time": curr_time,
    }
    sig_doc["TLS.sig"] = _hmac_sha256(identifier, sdkappid, curr_time, expire, settings.IM_SECRETKEY)
    return _b64_variant(zlib.compress(json.dumps(sig_doc).encode("utf-8")))


def decode_user_sig(sig: str) -> dict:
    """调试用:把 userSig 还原成明文,方便在日志/测试里核对内容与有效期。"""
    return json.loads(zlib.decompress(_b64_variant_decode(sig)).decode("utf-8"))
```

- [x] **Step 5:运行测试确认通过**

```bash
python manage.py test im
```

预期:3 个用例 OK。

- [x] **Step 6:提交**

```bash
cd "D:/pycharmproject/chat_app" && git add chatapp/im chatapp/config/settings.py chatapp/requirements.txt && git commit -m "feat: tencent im userSig generation (M1b)"
```

**卡点速查:**
- `KeyError` / `AttributeError: IM_SDKAPPID` → settings 没加配置块,或 `.env` 没重启加载(settings 只在启动时读一次)
- 想手工核对某个 userSig → `python manage.py shell -c "from im.signature import decode_user_sig; print(decode_user_sig('<sig>'))"`

---

### Task 2: IM REST 客户端(`im/client.py`)

**Files:**
- Create: `chatapp/im/client.py`
- Modify: `chatapp/im/tests.py`

**Interfaces:**
- Consumes: Task 1 的 `gen_user_sig`、settings 的 IM 配置。
- Produces:
  - `im.client._request(service, command, payload=None, identifier=None) -> dict`(失败抛异常)
  - `im.client.import_account(identifier, nickname="") -> bool`
  - `im.client.send_custom_elem(from_identifier, to_identifier, data: dict, desc="") -> bool`
  - `im.client.send_match_notice(identifier_a, identifier_b) -> bool`
  - `im.client.MATCH_NOTICE_TEXT = "你们已互相喜欢,开始聊天吧"`
  - **约定:三个业务函数对外永不抛异常**,失败记日志并返回 `False` —— 调用方(注册流程、滑卡配对)不因为 IM 抖动而失败。

**为什么要包一层:** 业务代码只关心"导入了/发出去了没有";REST 的 URL 拼装、`random`/`contenttype` 参数、腾讯的 `ErrorCode` 判定全部收在这里,将来换接口或加重试只改这一个文件。

- [x] **Step 1:写失败的测试**

`chatapp/im/tests.py` 顶部补 import(`import json`、`from unittest.mock import patch`、`from .client import import_account, send_custom_elem, send_match_notice, _request`),文件末尾追加:

```python
@override_settings(**IM_TEST_SETTINGS)
class ImClientTests(SimpleTestCase):
    def test_request_builds_tencent_params(self):
        with patch("im.client.requests.post") as post:
            post.return_value.json.return_value = {"ErrorCode": 0}
            _request("openim", "sendmsg", {"a": 1})
        args, kwargs = post.call_args
        self.assertTrue(args[0].endswith("/openim/sendmsg"))
        self.assertEqual(kwargs["params"]["sdkappid"], "1400000000")
        self.assertEqual(kwargs["params"]["identifier"], "administrator")
        self.assertEqual(kwargs["params"]["contenttype"], "json")
        self.assertIn("usersig", kwargs["params"])
        self.assertIn("random", kwargs["params"])
        self.assertEqual(kwargs["json"], {"a": 1})

    def test_import_account_payload(self):
        with patch("im.client._request", return_value={"ErrorCode": 0}) as req:
            self.assertTrue(import_account("u1", "小明"))
        args, _ = req.call_args
        self.assertEqual(args[0], "im_open_login_svc")
        self.assertEqual(args[1], "account_import")
        self.assertEqual(args[2]["Identifier"], "u1")
        self.assertEqual(args[2]["Nick"], "小明")

    def test_import_account_error_code_returns_false(self):
        with patch("im.client._request", return_value={"ErrorCode": 7015, "ErrorInfo": "exist"}):
            self.assertFalse(import_account("u1"))

    def test_import_account_network_error_returns_false(self):
        with patch("im.client._request", side_effect=Exception("boom")):
            self.assertFalse(import_account("u1"))

    def test_send_custom_elem_payload(self):
        with patch("im.client._request", return_value={"ErrorCode": 0}) as req:
            self.assertTrue(send_custom_elem("u1", "u2", {"type": "match_notice"}, "灰条"))
        args, kwargs = req.call_args
        self.assertEqual(args[0], "openim")
        self.assertEqual(args[1], "sendmsg")
        self.assertIsNone(kwargs.get("identifier"))   # 必须以管理员身份调(错误码 60010),发送方看 From_Account
        payload = args[2]
        self.assertEqual(payload["From_Account"], "u1")
        self.assertEqual(payload["To_Account"], "u2")
        body = payload["MsgBody"][0]
        self.assertEqual(body["MsgType"], "TIMCustomElem")
        self.assertEqual(json.loads(body["MsgContent"]["Data"]), {"type": "match_notice"})
        self.assertEqual(body["MsgContent"]["Desc"], "灰条")

    def test_send_match_notice_sends_both_directions(self):
        with patch("im.client.send_custom_elem", return_value=True) as send:
            self.assertTrue(send_match_notice("u1", "u2"))
        self.assertEqual(send.call_count, 2)
        self.assertEqual(send.call_args_list[0][0][:2], ("u1", "u2"))
        self.assertEqual(send.call_args_list[1][0][:2], ("u2", "u1"))
```

- [x] **Step 2:运行确认失败**

```bash
python manage.py test im
```

预期:ERROR(`No module named 'im.client'`)。

- [x] **Step 3:实现**

新建 `chatapp/im/client.py`:

```python
"""腾讯云 IM REST 客户端。

约定:业务函数(import_account / send_custom_elem / send_match_notice)对外
**永不抛异常**,失败只记日志并返回 False —— IM 抖动不应该拖垮注册/配对主流程。
上线前的改进方向是把这些调用丢进任务队列(Celery),开发期同步调用 + 短超时够用。
"""

import json
import logging
import random

import requests
from django.conf import settings

from .signature import gen_user_sig

logger = logging.getLogger(__name__)

MATCH_NOTICE_TEXT = "你们已互相喜欢,开始聊天吧"


def _random_int():
    return random.randint(1, 4294967295)


def _request(service: str, command: str, payload: dict | None = None, identifier: str | None = None) -> dict:
    identifier = identifier or settings.IM_ADMIN_IDENTIFIER
    url = f"{settings.IM_REST_BASE}/{service}/{command}"
    params = {
        "sdkappid": settings.IM_SDKAPPID,
        "identifier": identifier,
        "usersig": gen_user_sig(identifier),
        "random": _random_int(),
        "contenttype": "json",
    }
    resp = requests.post(url, params=params, json=payload or {}, timeout=settings.IM_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _check(result: dict, what: str) -> bool:
    if result.get("ErrorCode") != 0:
        logger.warning("IM %s 返回错误: %s", what, result)
        return False
    return True


def import_account(identifier: str, nickname: str = "") -> bool:
    payload = {"Identifier": identifier, "Nick": nickname, "FaceUrl": ""}
    try:
        result = _request("im_open_login_svc", "account_import", payload)
    except Exception:
        logger.exception("IM account_import 调用失败 identifier=%s", identifier)
        return False
    return _check(result, "account_import")


def send_custom_elem(from_identifier: str, to_identifier: str, data: dict, desc: str = "") -> bool:
    payload = {
        "SyncOtherMachine": 2,
        "From_Account": from_identifier,
        "To_Account": to_identifier,
        "MsgRandom": _random_int(),
        "MsgBody": [{
            "MsgType": "TIMCustomElem",
            "MsgContent": {"Data": json.dumps(data, ensure_ascii=False), "Desc": desc, "Ext": ""},
        }],
    }
    try:
        # REST 的 identifier 必须是本应用的管理员账号(否则腾讯报 60010);
        # 消息的发送方由 body 里的 From_Account 决定,所以对外仍是"双方各自发的"。
        result = _request("openim", "sendmsg", payload)
    except Exception:
        logger.exception("IM 发消息失败 %s -> %s", from_identifier, to_identifier)
        return False
    return _check(result, "sendmsg")


def send_match_notice(identifier_a: str, identifier_b: str) -> bool:
    """双方各发一条 TIMCustomElem:两个人的会话列表都会出现这个会话(M2 渲染成居中灰条)。"""
    data = {"type": "match_notice"}
    ok_a = send_custom_elem(identifier_a, identifier_b, data, MATCH_NOTICE_TEXT)
    ok_b = send_custom_elem(identifier_b, identifier_a, data, MATCH_NOTICE_TEXT)
    return ok_a and ok_b
```

- [x] **Step 4:运行测试确认通过**

```bash
python manage.py test im
```

预期:9 个用例(3 + 6)全部 OK。

- [x] **Step 5:提交**

```bash
cd "D:/pycharmproject/chat_app" && git add chatapp/im && git commit -m "feat: tencent im rest client (import/custom message/match notice) (M1b)"
```

**卡点速查(2026-09-10 真机实测后更新):**
- ✅ 已实测:`account_import` 与 `openim/sendmsg` 用**管理员身份**调用 + `From_Account` 指定发送方 → `ErrorCode 0`,返回 `MsgKey`/`MsgId`
- ❌ `sendmsg` 若把 REST 的 `identifier` 设为消息发送方,腾讯报 `60010 set the identifier field of the RESTful API request to the admin account` —— 必须用管理员
- 报 `70003`(userSig 校验失败)→ 时钟偏差或密钥不对;先 `decode_user_sig` 看内容
- 报 `7015`/账号不存在 → 先用 `import_account` 把账号导进去(腾讯要求发消息前账号已存在)
- ⚠️ **别用 `im_open_login_svc/account_check` 做冒烟**:2026-09-10 实测该接口在本应用下对任何参数组合都返回 `70402 Invalid parameters`(不是 userSig 的问题 —— 同一签名调 `account_import` 返回 `ErrorCode 0/OK`)。验签一律用 `account_import`。

---

### Task 3: `POST /im/user_sig` + `User.im_user_id` + `users.services.get_profile`

**Files:**
- Create: `chatapp/im/views.py`、`chatapp/im/urls.py`、`chatapp/users/services.py`
- Modify: `chatapp/accounts/models.py`、`chatapp/users/views.py`、`chatapp/config/api_urls.py`、`chatapp/accounts/tests.py`、`chatapp/im/tests.py`

**Interfaces:**
- Consumes: Task 1 的 `gen_user_sig`;M1a 的 `Profile` / `ProfileStatus`。
- Produces:
  - `accounts.User.im_user_id` 属性 → `"u{id}"`(全项目唯一的 IM ID 来源)
  - `users.services.get_profile(user) -> Profile`(懒建 Profile + Preference;把 M1a 里 `users/views.py` 的私有 `_get_profile` 提出来,供 discovery/im 复用)
  - `POST /api/v1/im/user_sig` → `{"user_sig", "sdkappid", "im_user_id", "expire"}`;`banned_heavy` → 403

- [x] **Step 1:写失败的测试**

`chatapp/accounts/tests.py` 的文件末尾追加:

```python
class ImUserIdTests(TestCase):
    def test_im_user_id_is_u_prefixed_id(self):
        user = User.objects.create_user(phone="13800138000")
        self.assertEqual(user.im_user_id, f"u{user.id}")
```

`chatapp/im/tests.py` 顶部补 import(`from django.contrib.auth import get_user_model`、`from rest_framework.test import APITestCase`、`from rest_framework_simplejwt.tokens import RefreshToken`、`from users.models import Profile, ProfileStatus`),文件末尾追加:

```python
User = get_user_model()


@override_settings(**IM_TEST_SETTINGS)
class UserSigApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(phone="13800138000")
        token = RefreshToken.for_user(self.user).access_token
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def test_returns_sig_for_current_user(self):
        resp = self.client.post("/api/v1/im/user_sig")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["im_user_id"], f"u{self.user.id}")
        self.assertEqual(data["sdkappid"], "1400000000")
        self.assertEqual(data["expire"], 604800)
        self.assertEqual(decode_user_sig(data["user_sig"])["TLS.identifier"], f"u{self.user.id}")

    def test_requires_auth(self):
        self.client.credentials()
        resp = self.client.post("/api/v1/im/user_sig")
        self.assertEqual(resp.status_code, 401)

    def test_heavy_banned_rejected(self):
        Profile.objects.create(user=self.user, status=ProfileStatus.BANNED_HEAVY)
        resp = self.client.post("/api/v1/im/user_sig")
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["code"], 403)
```

- [x] **Step 2:运行确认失败**

```bash
python manage.py test accounts im
```

预期:新用例 FAIL/ERROR(404、`AttributeError: im_user_id`)。

- [x] **Step 3:实现**

`chatapp/accounts/models.py` 的 `User` 类里(`__str__` 上方)加:

```python
    @property
    def im_user_id(self):
        """腾讯云 IM 的账号标识;全项目只在这里拼,别处一律用这个属性。"""
        return f"u{self.id}"
```

新建 `chatapp/users/services.py`:

```python
from .models import Preference, Profile


def get_profile(user):
    """取当前用户资料;没有就建空 Profile + 空 Preference(资料是懒创建的)。"""
    profile, _ = Profile.objects.get_or_create(user=user)
    Preference.objects.get_or_create(profile=profile)
    return profile
```

`chatapp/users/views.py`:删掉本文件里的 `_get_profile` 定义,改成从 services 导入 —— 顶部加 `from .services import get_profile`,并把文件里 4 处 `_get_profile(` 换成 `get_profile(`(me、upload_photo、delete_photo、my_preference 各一处)。

新建 `chatapp/im/views.py`:

```python
from django.conf import settings
from rest_framework.decorators import api_view
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from users.models import ProfileStatus
from users.services import get_profile

from .signature import gen_user_sig


@api_view(["POST"])
def user_sig(request):
    profile = get_profile(request.user)
    if profile.status == ProfileStatus.BANNED_HEAVY:
        raise PermissionDenied("账号已被封禁")
    return Response({
        "user_sig": gen_user_sig(request.user.im_user_id),
        "sdkappid": settings.IM_SDKAPPID,
        "im_user_id": request.user.im_user_id,
        "expire": settings.IM_SIG_EXPIRE,
    })
```

新建 `chatapp/im/urls.py`:

```python
from django.urls import path

from . import views

urlpatterns = [
    path("user_sig", views.user_sig),
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
    path("im/", include("im.urls")),
]
```

(`discovery/` 路由等 Task 6 建好 `discovery/urls.py` 再加 —— 现在写了会因为模块不存在直接报错。)

- [x] **Step 4:运行测试确认通过**

```bash
python manage.py test accounts im users
```

预期:全绿(M1a 的 users 测试要一并确认没被 `get_profile` 重构弄坏)。

- [x] **Step 5:提交**

```bash
cd "D:/pycharmproject/chat_app" && git add chatapp/accounts chatapp/users chatapp/im chatapp/config && git commit -m "feat: POST /im/user_sig + User.im_user_id + users.services.get_profile (M1b)"
```

---

### Task 4: 注册成功后导入 IM 账号

**Files:**
- Modify: `chatapp/accounts/views.py`、`chatapp/accounts/tests.py`、`chatapp/config/settings.py`(LOGGING 增加 im logger)

**Interfaces:**
- Consumes: Task 2 的 `im.client.import_account`;Task 3 的 `User.im_user_id`。
- Produces: 新用户注册成功(且事务提交)后自动调用 `account_import`;老用户登录不调用;IM 失败不影响注册返回。

**为什么用 `transaction.on_commit`:** 数据库事务还没提交就调外部接口,一旦事务回滚,IM 里就留下一个"幽灵账号"。`on_commit` 保证只在数据真正落库后才发请求。

- [x] **Step 1:写失败的测试**

`chatapp/accounts/tests.py` 顶部补 import(`from unittest.mock import patch` 已在;补 `from django.db import transaction` 不需要),文件末尾追加:

```python
class ImImportOnRegisterTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.phone = "13800138000"

    def issue_code(self):
        cache.delete(f"sms:sent:{self.phone}")
        return services.send_code(self.phone)

    def verify(self):
        return self.client.post("/api/v1/auth/sms/verify",
                                {"phone": self.phone, "code": self.issue_code()}, format="json")

    def test_new_user_triggers_im_import(self):
        with patch("accounts.views.im_client.import_account") as imp:
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.verify()
        self.assertEqual(resp.status_code, 200)
        user = User.objects.get(phone=self.phone)
        imp.assert_called_once_with(user.im_user_id)

    def test_existing_user_does_not_trigger_import(self):
        self.verify()
        with patch("accounts.views.im_client.import_account") as imp:
            with self.captureOnCommitCallbacks(execute=True):
                self.verify()
        imp.assert_not_called()

    def test_im_failure_does_not_break_register(self):
        with patch("im.client._request", side_effect=Exception("im down")):
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.verify()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(User.objects.filter(phone=self.phone).exists())
```

- [x] **Step 2:运行确认失败**

```bash
python manage.py test accounts
```

预期:3 个新用例 FAIL(`import_account` 从未被调用)。

- [x] **Step 3:实现**

`chatapp/accounts/views.py` 顶部加 import:

```python
from django.db import transaction

from im import client as im_client
```

`sms_verify` 里 `user, created = User.objects.get_or_create(phone=phone)` 之后加:

```python
    if created:
        transaction.on_commit(lambda: im_client.import_account(user.im_user_id))
```

`chatapp/config/settings.py` 的 `LOGGING` 字典里,`loggers` 改成:

```python
    "loggers": {
        "accounts": {"handlers": ["console"], "level": "INFO"},
        "im": {"handlers": ["console"], "level": "INFO"},
    },
```

- [x] **Step 4:运行测试确认通过**

```bash
python manage.py test accounts
```

预期:16 个用例全部 OK(13 + 3)。

- [x] **Step 5:提交**

```bash
cd "D:/pycharmproject/chat_app" && git add chatapp/accounts chatapp/config/settings.py && git commit -m "feat: import im account on register (M1b)"
```

---

### Task 5: discovery 模型(`Swipe` / `Match`)+ 年龄区间助手

**Files:**
- Create: `chatapp/discovery/models.py`(覆盖模板)、`chatapp/discovery/admin.py`(覆盖模板)、`chatapp/discovery/migrations/0001_initial.py`(生成)、`chatapp/discovery/tests.py`(覆盖模板)
- Modify: `chatapp/users/models.py`(加 `shift_years` / `birthday_bounds` / `Profile.is_banned`)、`chatapp/users/tests.py`

**Interfaces:**
- Consumes: M1a 的 `User`。
- Produces:
  - `discovery.models.SwipeAction`(like/pass)、`Swipe`(FK swiper/target + 唯一约束 `(swiper, target)`)、`Match`(FK user_a/user_b + 唯一约束 + CheckConstraint `user_a < user_b`)、`Match.pair_kwargs(u1, u2)`(自动排序)、`Match.other_user(me)`
  - `users.models.shift_years(day, years) -> date`(处理 2 月 29 日)
  - `users.models.birthday_bounds(age_min, age_max, today=None) -> (upper, lower)`:年龄过滤条件 = `birthday__lte=upper, birthday__gt=lower`
  - `Profile.is_banned` 属性(轻/重封禁都算)

**为什么 Match 要"有序对 + CheckConstraint":** 唯一约束是"并发互喜只配对一次"的最终保证 —— 两个人同时点喜欢时,数据库只让一条 `(user_a, user_b)` 插进去,另一条撞唯一约束。强制 `user_a.id < user_b.id` 让 `(1,2)` 与 `(2,1)` 在数据库层面是同一条记录,否则唯一约束形同虚设。

- [x] **Step 1:写失败的测试**

`chatapp/users/tests.py` 追加:

```python
class BirthdayBoundsTests(SimpleTestCase):
    def test_bounds(self):
        upper, lower = birthday_bounds(18, 30, today=date(2026, 9, 10))
        self.assertEqual(upper, date(2008, 9, 10))   # 生在这天 = 刚好 18 岁
        self.assertEqual(lower, date(1995, 9, 10))   # 生在更早 = 31 岁,排除

    def test_leap_day(self):
        upper, _ = birthday_bounds(1, 30, today=date(2024, 2, 29))
        self.assertEqual(upper, date(2023, 2, 28))
```

`chatapp/users/tests.py` 顶部 import 行补 `birthday_bounds`(改成 `from .models import Photo, Profile, ProfileStatus, Tag, birthday_bounds, calculate_age`)。

`chatapp/discovery/tests.py` 整体替换:

```python
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from .models import Match, Swipe, SwipeAction

User = get_user_model()


class SwipeModelTests(TestCase):
    def setUp(self):
        self.a = User.objects.create_user(phone="13800138000")
        self.b = User.objects.create_user(phone="13900139000")

    def test_same_pair_can_only_swipe_once(self):
        Swipe.objects.create(swiper=self.a, target=self.b, action=SwipeAction.LIKE)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Swipe.objects.create(swiper=self.a, target=self.b, action=SwipeAction.PASS)

    def test_reverse_direction_is_a_different_swipe(self):
        Swipe.objects.create(swiper=self.a, target=self.b, action=SwipeAction.LIKE)
        Swipe.objects.create(swiper=self.b, target=self.a, action=SwipeAction.LIKE)
        self.assertEqual(Swipe.objects.count(), 2)


class MatchModelTests(TestCase):
    def setUp(self):
        self.a = User.objects.create_user(phone="13800138000")
        self.b = User.objects.create_user(phone="13900139000")

    def test_pair_kwargs_orders_by_id(self):
        self.assertEqual(Match.pair_kwargs(self.b, self.a), {"user_a": self.a, "user_b": self.b})
        self.assertEqual(Match.pair_kwargs(self.a, self.b), {"user_a": self.a, "user_b": self.b})

    def test_duplicate_pair_rejected(self):
        Match.objects.create(**Match.pair_kwargs(self.a, self.b))
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Match.objects.create(**Match.pair_kwargs(self.b, self.a))

    def test_reversed_order_rejected_by_check_constraint(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Match.objects.create(user_a=self.b, user_b=self.a)

    def test_other_user(self):
        match = Match.objects.create(**Match.pair_kwargs(self.a, self.b))
        self.assertEqual(match.other_user(self.a), self.b)
        self.assertEqual(match.other_user(self.b), self.a)
```

- [x] **Step 2:运行确认失败**

```bash
python manage.py test discovery users
```

预期:ERROR(`No module named 'discovery.models'` 的模型部分 / `birthday_bounds` 不存在)。

- [x] **Step 3:实现用户侧助手**

`chatapp/users/models.py` 在 `calculate_age` 之后加:

```python
def shift_years(day, years):
    """把日期往前推 N 年;2 月 29 日退化成 2 月 28 日。"""
    try:
        return day.replace(year=day.year - years)
    except ValueError:
        return day.replace(year=day.year - years, day=28)


def birthday_bounds(age_min, age_max, today=None):
    """把年龄区间换算成生日区间:birthday <= upper 且 birthday > lower。

    推导:age >= age_min ⇔ 生日不晚于"今天减 age_min 年";
         age <= age_max ⇔ 生日晚于"今天减 (age_max+1) 年"。
    """
    today = today or timezone.localdate()
    return shift_years(today, age_min), shift_years(today, age_max + 1)
```

`Profile` 类里(`refresh_status` 上方)加:

```python
    @property
    def is_banned(self):
        return self.status in self.BANNED_STATUSES
```

- [x] **Step 4:实现 discovery 模型与 admin**

`chatapp/discovery/models.py` 整体替换:

```python
from django.conf import settings
from django.db import models
from django.db.models import F, Q


class SwipeAction(models.TextChoices):
    LIKE = "like", "喜欢"
    PASS = "pass", "跳过"


class Swipe(models.Model):
    swiper = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="swipes_made")
    target = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="swipes_received")
    action = models.CharField("动作", max_length=10, choices=SwipeAction.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["swiper", "target"], name="uniq_swipe_swiper_target"),
        ]

    def __str__(self):
        return f"{self.swiper_id}->{self.target_id}:{self.action}"


class Match(models.Model):
    user_a = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="matches_as_a")
    user_b = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="matches_as_b")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["user_a", "user_b"], name="uniq_match_pair"),
            models.CheckConstraint(condition=Q(user_a__lt=F("user_b")), name="match_user_a_before_b"),
        ]

    @classmethod
    def pair_kwargs(cls, user1, user2):
        """配对一律按 id 排序存储,保证 (1,2) 与 (2,1) 是同一行。"""
        a, b = (user1, user2) if user1.id < user2.id else (user2, user1)
        return {"user_a": a, "user_b": b}

    def other_user(self, user):
        return self.user_b if self.user_a_id == user.id else self.user_a

    def __str__(self):
        return f"match({self.user_a_id},{self.user_b_id})"
```

`chatapp/discovery/admin.py` 整体替换:

```python
from django.contrib import admin

from .models import Match, Swipe


@admin.register(Swipe)
class SwipeAdmin(admin.ModelAdmin):
    list_display = ("id", "swiper", "target", "action", "created_at")
    list_filter = ("action",)


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = ("id", "user_a", "user_b", "created_at")
```

- [x] **Step 5:生成迁移并 migrate**

```bash
python manage.py makemigrations discovery
python manage.py migrate
```

- [x] **Step 6:运行测试确认通过**

```bash
python manage.py test discovery users
```

预期:discovery 6 个 + users 28 个全部 OK。

- [x] **Step 7:提交**

```bash
cd "D:/pycharmproject/chat_app" && git add chatapp/discovery chatapp/users && git commit -m "feat: Swipe/Match models + age range helper (M1b)"
```

**卡点速查:**
- `TypeError: CheckConstraint.__init__() got an unexpected keyword argument 'check'` → Django 5.2 用 `condition=`(旧版才是 `check=`)
- MySQL 建约束报错 → 确认 `makemigrations discovery` 有输出且 `migrate` 跑过

---

### Task 6: `GET /discovery/candidates`

**Files:**
- Create: `chatapp/discovery/serializers.py`、`chatapp/discovery/views.py`(覆盖模板)、`chatapp/discovery/urls.py`
- Modify: `chatapp/discovery/tests.py`、`chatapp/config/api_urls.py`(打开 discovery 路由)

**Interfaces:**
- Consumes: Task 5 的模型与 `birthday_bounds`;Task 3 的 `get_profile`。
- Produces:
  - `GET /api/v1/discovery/candidates?limit=10` → 候选数组,元素:`{user_id, nickname, gender, age, city, bio, tags[], photos[]}`
  - `discovery.serializers.CandidateSerializer`
  - 排除规则:自己 / 资料非 `complete` / 已划过 / 已配对;过滤规则:目标性别、城市、年龄区间(来自 `Preference`,空则不筛);顺序:随机;默认 10 条、上限 20 条

- [x] **Step 1:写失败的测试**

`chatapp/discovery/tests.py` 顶部补 import,文件末尾追加:

```python
import base64

from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from users.models import Photo, PhotoStatus, Preference, Profile, ProfileStatus, Tag

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


class CandidateTests(APITestCase):
    URL = "/api/v1/discovery/candidates"

    def setUp(self):
        self.me = self._make_user("13800138000", gender="male", birthday="2000-01-01", city="上海")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.me).access_token}")

    def _make_user(self, phone, gender="female", birthday="2000-01-01", city="上海", complete=True):
        user = User.objects.create_user(phone=phone)
        Profile.objects.create(
            user=user, nickname=phone, gender=gender, birthday=birthday, city=city, bio="你好",
            status=ProfileStatus.COMPLETE if complete else ProfileStatus.INCOMPLETE,
        )
        if complete:
            Photo.objects.create(user=user, file="photos/x.png", status=PhotoStatus.APPROVED)
        return user

    def _ids(self, resp):
        return [item["user_id"] for item in resp.json()]

    def test_excludes_self_incomplete_and_no_photo(self):
        other = self._make_user("13900139000")
        self._make_user("13900139001", complete=False)
        self._make_user("13900139002")   # 有照片
        Photo.objects.filter(user__phone="13900139002").delete()   # 抽掉照片 → 资料不该算完整
        Profile.objects.filter(user__phone="13900139002").update(status=ProfileStatus.COMPLETE)
        resp = self.client.get(self.URL)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._ids(resp), [other.id])

    def test_excludes_swiped_and_matched(self):
        swiped = self._make_user("13900139000")
        matched = self._make_user("13900139001")
        fresh = self._make_user("13900139002")
        Swipe.objects.create(swiper=self.me, target=swiped, action=SwipeAction.PASS)
        Match.objects.create(**Match.pair_kwargs(self.me, matched))
        self.assertEqual(self._ids(self.client.get(self.URL)), [fresh.id])

    def test_filters_by_preference(self):
        Preference.objects.create(profile=self.me.profile, target_gender="female",
                                  age_min=25, age_max=30, city="上海")
        ok = self._make_user("13900139000", gender="female", birthday="1998-01-01", city="上海")   # 28 岁
        self._make_user("13900139001", gender="male", birthday="1998-01-01")        # 性别不符
        self._make_user("13900139002", gender="female", birthday="2005-01-01")      # 太年轻
        self._make_user("13900139003", gender="female", birthday="1990-01-01")      # 太大
        self._make_user("13900139004", gender="female", birthday="1998-01-01", city="北京")  # 城市不符
        self.assertEqual(self._ids(self.client.get(self.URL)), [ok.id])

    def test_age_boundaries_are_inclusive(self):
        today = timezone.localdate()
        Preference.objects.create(profile=self.me.profile, age_min=18, age_max=30)
        exactly_18 = self._make_user("13900139000", birthday=date(today.year - 18, today.month, today.day))
        exactly_30 = self._make_user("13900139001", birthday=date(today.year - 30, today.month, today.day))
        self._make_user("13900139002", birthday=date(today.year - 31, today.month, today.day))   # 31 岁
        self._make_user("13900139003", birthday=date(today.year - 17, today.month, today.day))   # 17 岁
        self.assertEqual(sorted(self._ids(self.client.get(self.URL))), sorted([exactly_18.id, exactly_30.id]))

    def test_without_preference_returns_everyone_eligible(self):
        Preference.objects.filter(profile=self.me.profile).delete()
        a = self._make_user("13900139000", gender="female", birthday="2005-01-01", city="北京")
        b = self._make_user("13900139001", gender="male", birthday="1980-01-01", city="广州")
        self.assertEqual(sorted(self._ids(self.client.get(self.URL))), sorted([a.id, b.id]))

    def test_only_approved_photos_returned(self):
        ghost = self._make_user("13900139000")
        Photo.objects.create(user=ghost, file="photos/pending.png", status=PhotoStatus.PENDING)
        data = self.client.get(self.URL).json()
        self.assertEqual(len(data), 1)
        self.assertTrue(all(p["status"] == "approved" for p in data[0]["photos"]))

    def test_limit_default_and_cap(self):
        for i in range(12):
            self._make_user(f"1390013{i:04d}")
        self.assertEqual(len(self.client.get(self.URL).json()), 10)
        self.assertEqual(len(self.client.get(f"{self.URL}?limit=3").json()), 3)
        self.assertEqual(len(self.client.get(f"{self.URL}?limit=99").json()), 12)   # 上限 20,但只有 12 个人

    def test_requires_auth(self):
        self.client.credentials()
        self.assertEqual(self.client.get(self.URL).status_code, 401)
```

`chatapp/discovery/tests.py` 顶部 import 区补齐(放在文件最上方,与 Task 5 的 import 合并):

```python
from datetime import date

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from users.models import Photo, PhotoStatus, Preference, Profile, ProfileStatus

from .models import Match, Swipe, SwipeAction
```

- [x] **Step 2:运行确认失败**

```bash
python manage.py test discovery
```

预期:新用例 FAIL/ERROR(404)。

- [x] **Step 3:实现序列化器**

新建 `chatapp/discovery/serializers.py`:

```python
from rest_framework import serializers

from users.models import PhotoStatus, Profile
from users.serializers import PhotoSerializer, TagSerializer


class CandidateSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(source="user.id", read_only=True)
    age = serializers.IntegerField(read_only=True)
    tags = TagSerializer(many=True, read_only=True)
    photos = serializers.SerializerMethodField()

    class Meta:
        model = Profile
        fields = ["user_id", "nickname", "gender", "age", "city", "bio", "tags", "photos"]

    def get_photos(self, profile):
        approved = [p for p in profile.user.photos.all() if p.status == PhotoStatus.APPROVED]
        return PhotoSerializer(approved, many=True, context=self.context).data
```

- [x] **Step 4:实现视图与路由**

`chatapp/discovery/views.py` 整体替换:

```python
from django.db.models import Q
from rest_framework.decorators import api_view
from rest_framework.response import Response

from users.models import Photo, PhotoStatus, Profile, ProfileStatus, birthday_bounds
from users.services import get_profile

from .models import Match, Swipe
from .serializers import CandidateSerializer

DEFAULT_LIMIT = 10
MAX_LIMIT = 20


@api_view(["GET"])
def candidates(request):
    me = request.user
    preference = get_profile(me).preference

    swiped_ids = Swipe.objects.filter(swiper=me).values_list("target_id", flat=True)
    my_matches = Match.objects.filter(Q(user_a=me) | Q(user_b=me))
    matched_ids = [
        other_id
        for other_id in list(my_matches.values_list("user_a_id", flat=True))
        + list(my_matches.values_list("user_b_id", flat=True))
        if other_id != me.id
    ]

    # 有过审照片的人才进候选(用子查询而不是 JOIN,避免出重复行、也避免 distinct + 随机排序的坑)
    with_photos = Photo.objects.filter(status=PhotoStatus.APPROVED).values("user_id")
    qs = (Profile.objects.filter(status=ProfileStatus.COMPLETE, user_id__in=with_photos)
          .exclude(user_id=me.id)
          .exclude(user_id__in=list(swiped_ids))
          .exclude(user_id__in=matched_ids))

    if preference.target_gender:
        qs = qs.filter(gender=preference.target_gender)
    if preference.city:
        qs = qs.filter(city=preference.city)
    upper, lower = birthday_bounds(preference.age_min, preference.age_max)
    qs = qs.filter(birthday__lte=upper, birthday__gt=lower)

    try:
        limit = min(int(request.query_params.get("limit", DEFAULT_LIMIT)), MAX_LIMIT)
    except ValueError:
        limit = DEFAULT_LIMIT

    # order_by("?") 在数据量大时会慢,MVP 阶段(几百人)够用,将来换成预计算随机列
    qs = qs.prefetch_related("tags", "user__photos").order_by("?")[:limit]
    return Response(CandidateSerializer(qs, many=True, context={"request": request}).data)
```

新建 `chatapp/discovery/urls.py`:

```python
from django.urls import path

from . import views

urlpatterns = [
    path("candidates", views.candidates),
]
```

`chatapp/config/api_urls.py` 的 `im/` 那行下面补一行:

```python
    path("discovery/", include("discovery.urls")),
```

- [x] **Step 5:运行测试确认通过**

```bash
python manage.py test discovery
```

预期:14 个用例(6 + 8)全部 OK。

- [x] **Step 6:提交**

```bash
cd "D:/pycharmproject/chat_app" && git add chatapp/discovery chatapp/config && git commit -m "feat: GET /discovery/candidates (M1b)"
```

**卡点速查:**
- 返回空数组 → 候选要求对方 `status=complete` **且有 approved 照片**;测试数据用 `_make_user` 造才不会漏
- `test_age_boundaries_are_inclusive` 在 2 月 29 日跑会挂 → 那是 `shift_years` 的已知退化行为(生日 2/29 的人年龄边界按 2/28 算),可接受

---

### Task 7: `POST /discovery/swipe`(幂等 + 互喜配对 + 灰条消息 + 限流)

**Files:**
- Create: `chatapp/discovery/services.py`、`chatapp/discovery/throttles.py`
- Modify: `chatapp/discovery/views.py`、`chatapp/discovery/serializers.py`、`chatapp/discovery/tests.py`、`chatapp/config/settings.py`(加 swipe 限流额度)

**Interfaces:**
- Consumes: Task 5 的 `Swipe`/`Match`;Task 2 的 `im.client.send_match_notice`;Task 3 的 `get_profile`。
- Produces:
  - `POST /api/v1/discovery/swipe`,body `{"target_user_id": 5, "action": "like"|"pass"}` → `{"matched": bool}`
  - `discovery.serializers.SwipeSerializer`
  - `discovery.throttles.SwipeThrottle`(按用户限流,额度 `swipe` = 300/小时)
  - `discovery.services.notify_match(match)`:在事务提交后给双方各发一条灰条消息,失败只记日志

**为什么配对要放在 `transaction.atomic()` 里 + `get_or_create`:** 两个人几乎同时互相点喜欢时,两个请求都会走到建 Match;唯一约束让第二条插不进去,`get_or_create` 把它变成"拿到已有那条"。事务保证"记录 Swipe"和"建 Match"要么都成、要么都不成。

- [x] **Step 1:写失败的测试**

`chatapp/discovery/tests.py` 顶部补 `from unittest.mock import patch`,文件末尾追加:

```python
class SwipeApiTests(APITestCase):
    URL = "/api/v1/discovery/swipe"

    def setUp(self):
        cache.clear()               # 限流计数存在缓存里,测试之间必须清
        self.addCleanup(cache.clear)
        self.me = self._make_user("13800138000", gender="male")
        self.target = self._make_user("13900139000", gender="female")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.me).access_token}")

    def _make_user(self, phone, gender="female"):
        user = User.objects.create_user(phone=phone)
        Profile.objects.create(user=user, nickname=phone, gender=gender, birthday="2000-01-01",
                               city="上海", bio="你好", status=ProfileStatus.COMPLETE)
        Photo.objects.create(user=user, file="photos/x.png", status=PhotoStatus.APPROVED)
        return user

    def swipe(self, target_id, action="like"):
        return self.client.post(self.URL, {"target_user_id": target_id, "action": action}, format="json")

    def test_like_creates_swipe(self):
        resp = self.swipe(self.target.id)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"matched": False})
        self.assertTrue(Swipe.objects.filter(swiper=self.me, target=self.target,
                                             action=SwipeAction.LIKE).exists())

    def test_repeat_swipe_is_idempotent(self):
        self.swipe(self.target.id)
        resp = self.swipe(self.target.id)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Swipe.objects.count(), 1)

    def test_mutual_like_creates_one_match(self):
        Swipe.objects.create(swiper=self.target, target=self.me, action=SwipeAction.LIKE)
        with patch("discovery.services.im_client.send_match_notice"):   # 别真打腾讯云
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.swipe(self.target.id)
        self.assertEqual(resp.json(), {"matched": True})
        self.assertEqual(Match.objects.count(), 1)
        self.assertEqual(Match.objects.first().user_a, self.me)

    def test_mutual_like_after_match_does_not_resend_notice(self):
        Swipe.objects.create(swiper=self.target, target=self.me, action=SwipeAction.LIKE)
        with patch("discovery.services.im_client.send_match_notice") as notice:
            with self.captureOnCommitCallbacks(execute=True):
                self.swipe(self.target.id)
                again = self.swipe(self.target.id)
        self.assertEqual(again.json(), {"matched": True})
        self.assertEqual(notice.call_count, 1)
        self.assertEqual(notice.call_args[0], (self.me.im_user_id, self.target.im_user_id))

    def test_pass_never_matches(self):
        Swipe.objects.create(swiper=self.target, target=self.me, action=SwipeAction.LIKE)
        resp = self.swipe(self.target.id, action="pass")
        self.assertEqual(resp.json(), {"matched": False})
        self.assertEqual(Match.objects.count(), 0)

    def test_im_failure_does_not_break_swipe(self):
        Swipe.objects.create(swiper=self.target, target=self.me, action=SwipeAction.LIKE)
        with patch("im.client._request", side_effect=Exception("im down")):
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.swipe(self.target.id)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"matched": True})

    def test_cannot_swipe_self(self):
        self.assertEqual(self.swipe(self.me.id).status_code, 400)

    def test_unknown_target_returns_404(self):
        self.assertEqual(self.swipe(999999).status_code, 404)

    def test_incomplete_target_rejected(self):
        loner = User.objects.create_user(phone="13900139001")
        Profile.objects.create(user=loner, status=ProfileStatus.INCOMPLETE)
        self.assertEqual(self.swipe(loner.id).status_code, 400)

    def test_banned_light_cannot_swipe(self):
        Profile.objects.filter(user=self.me).update(status=ProfileStatus.BANNED_LIGHT)
        resp = self.swipe(self.target.id)
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(Swipe.objects.exists())

    def test_invalid_action_rejected(self):
        self.assertEqual(self.swipe(self.target.id, action="hug").status_code, 400)

    def test_swipe_throttled(self):
        from discovery.throttles import SwipeThrottle
        with patch.object(SwipeThrottle, "rate", "2/hour", create=True):
            self.assertEqual(self.swipe(self.target.id).status_code, 200)
            self.assertEqual(self.swipe(self.target.id).status_code, 200)
            self.assertEqual(self.swipe(self.target.id).status_code, 429)
```

- [x] **Step 2:运行确认失败**

```bash
python manage.py test discovery
```

预期:12 个新用例 FAIL/ERROR。

- [x] **Step 3:实现**

`chatapp/config/settings.py` 的 `DEFAULT_THROTTLE_RATES` 改成:

```python
    "DEFAULT_THROTTLE_RATES": {"sms_send": "20/hour", "swipe": "300/hour"},
```

新建 `chatapp/discovery/throttles.py`:

```python
from rest_framework.throttling import SimpleRateThrottle


class SwipeThrottle(SimpleRateThrottle):
    """按用户限流滑卡;额度在 settings.DEFAULT_THROTTLE_RATES["swipe"]。"""

    scope = "swipe"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": request.user.id}
```

新建 `chatapp/discovery/services.py`:

```python
import logging

from django.db import transaction

from im import client as im_client

logger = logging.getLogger(__name__)


def notify_match(match):
    """配对成功后给双方各发一条 IM 灰条消息。

    用 on_commit:消息只在配对真正落库后才发;发送失败只记日志,不影响配对结果。
    """
    a_id, b_id = match.user_a.im_user_id, match.user_b.im_user_id
    transaction.on_commit(lambda: im_client.send_match_notice(a_id, b_id))
```

`chatapp/discovery/serializers.py` 追加:

```python
class SwipeSerializer(serializers.Serializer):
    target_user_id = serializers.IntegerField()
    action = serializers.ChoiceField(choices=SwipeAction.choices)
```

(顶部 import 补 `from .models import SwipeAction`。)

`chatapp/discovery/views.py` 顶部 import 补:

```python
from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.generics import get_object_or_404

from .models import Match, Swipe, SwipeAction
from .serializers import CandidateSerializer, SwipeSerializer
from .services import notify_match
from .throttles import SwipeThrottle
```

(注意 `User = get_user_model()` 也要加在 import 之后。)

`chatapp/discovery/views.py` 追加视图:

```python
@api_view(["POST"])
@throttle_classes([SwipeThrottle])
def swipe(request):
    me = request.user
    serializer = SwipeSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    target_id = serializer.validated_data["target_user_id"]
    action = serializer.validated_data["action"]

    if get_profile(me).is_banned:
        raise PermissionDenied("账号已被限制,暂时无法滑卡")
    if target_id == me.id:
        raise ValidationError("不能划自己")

    target = get_object_or_404(User, id=target_id)
    if not Profile.objects.filter(user=target, status=ProfileStatus.COMPLETE).exists():
        raise ValidationError("对方资料不完整,无法操作")

    # 幂等:重复提交保留第一次的动作与结果
    swipe_obj, _ = Swipe.objects.get_or_create(swiper=me, target=target, defaults={"action": action})

    matched = False
    if swipe_obj.action == SwipeAction.LIKE and Swipe.objects.filter(
            swiper=target, target=me, action=SwipeAction.LIKE).exists():
        with transaction.atomic():
            match, created = Match.objects.get_or_create(**Match.pair_kwargs(me, target))
            if created:
                notify_match(match)
        matched = True

    return Response({"matched": matched})
```

`chatapp/discovery/urls.py` 整体替换:

```python
from django.urls import path

from . import views

urlpatterns = [
    path("candidates", views.candidates),
    path("swipe", views.swipe),
]
```

- [x] **Step 4:运行测试确认通过**

```bash
python manage.py test discovery
```

预期:26 个用例(14 + 12)全部 OK。

- [x] **Step 5:提交**

```bash
cd "D:/pycharmproject/chat_app" && git add chatapp/discovery chatapp/config && git commit -m "feat: POST /discovery/swipe with match + im notice + throttle (M1b)"
```

**卡点速查:**
- 灰条消息没发出去 → 检查 `notify_match` 是否**在 `transaction.atomic()` 块内**调用(on_commit 必须在事务里注册)
- 测试里 `notice.assert_called_once()` 失败 → 忘了 `self.captureOnCommitCallbacks(execute=True)`(测试事务里 on_commit 默认不执行)
- 429 出现在不相干的用例 → `cache.clear()` 没加(限流状态存在缓存里)
- ⚠️ **每个执行 on_commit 回调的用例都要 mock 掉 IM**:漏 mock 会**真的**打腾讯云(2026-09-10 实测:漏掉一个,日志里出现 `20003 Invalid sender or receiver identifier`,因为测试用户的 `u{id}` 在 IM 里并不存在)。用例仍然是绿的(业务函数吞异常),但测试变慢且依赖网络 —— 靠"跑测试时日志里有没有 IM 报错"来发现。

---

### Task 8: `GET /matches`(会话列表预热)

**Files:**
- Modify: `chatapp/discovery/views.py`、`chatapp/discovery/urls.py`、`chatapp/discovery/tests.py`

**Interfaces:**
- Consumes: Task 5 的 `Match.other_user`;M1a 的 `Profile` / `Photo`。
- Produces: `GET /api/v1/matches` → `[{"user_id", "im_user_id", "nickname", "avatar_url", "matched_at"}]`;`avatar_url` 取对方第一张过审照片的绝对地址,没有则 `null`。M2 启动时拉这个接口把 `userId → 昵称/头像` 缓存到本地,用于渲染 IM 会话列表。

**为什么单独这个接口:** 会话列表数据源是腾讯云 IM(不经过我们服务器),App 拿到会话里的 userId 后必须靠本地缓存翻译成昵称/头像 —— 这份缓存就来自这里。

- [x] **Step 1:写失败的测试**

`chatapp/discovery/tests.py` 末尾追加:

```python
class MatchListTests(APITestCase):
    URL = "/api/v1/matches"

    def setUp(self):
        self.me = self._make_user("13800138000")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.me).access_token}")

    def _make_user(self, phone, nickname=None, with_photo=True):
        user = User.objects.create_user(phone=phone)
        Profile.objects.create(user=user, nickname=nickname or phone, gender="female",
                               birthday="2000-01-01", city="上海", bio="你好",
                               status=ProfileStatus.COMPLETE)
        if with_photo:
            Photo.objects.create(user=user, file="photos/x.png", status=PhotoStatus.APPROVED)
        return user

    def test_lists_both_sides(self):
        other = self._make_user("13900139000", nickname="小红")
        Match.objects.create(**Match.pair_kwargs(self.me, other))
        data = self.client.get(self.URL).json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["user_id"], other.id)
        self.assertEqual(data[0]["im_user_id"], other.im_user_id)
        self.assertEqual(data[0]["nickname"], "小红")
        self.assertTrue(data[0]["avatar_url"].startswith("http://testserver/media/"))

    def test_avatar_null_without_approved_photo(self):
        other = self._make_user("13900139000", with_photo=False)
        Match.objects.create(**Match.pair_kwargs(self.me, other))
        self.assertIsNone(self.client.get(self.URL).json()[0]["avatar_url"])

    def test_only_my_matches(self):
        other = self._make_user("13900139000")
        stranger_a = self._make_user("13900139001")
        stranger_b = self._make_user("13900139002")
        Match.objects.create(**Match.pair_kwargs(self.me, other))
        Match.objects.create(**Match.pair_kwargs(stranger_a, stranger_b))
        data = self.client.get(self.URL).json()
        self.assertEqual([item["user_id"] for item in data], [other.id])

    def test_requires_auth(self):
        self.client.credentials()
        self.assertEqual(self.client.get(self.URL).status_code, 401)
```

- [x] **Step 2:运行确认失败**

```bash
python manage.py test discovery
```

预期:4 个新用例 FAIL/ERROR(404)。

- [x] **Step 3:实现**

`chatapp/discovery/views.py` 的 import 区补 `from users.models import PhotoStatus`(与已有的 `Profile, ProfileStatus, birthday_bounds` 合并),追加视图:

```python
@api_view(["GET"])
def match_list(request):
    me = request.user
    matches = (Match.objects.filter(Q(user_a=me) | Q(user_b=me))
               .select_related("user_a__profile", "user_b__profile")
               .prefetch_related("user_a__photos", "user_b__photos"))
    return Response([_match_entry(match, me, request) for match in matches])


def _match_entry(match, me, request):
    other = match.other_user(me)
    profile = getattr(other, "profile", None)
    approved = [p for p in other.photos.all() if p.status == PhotoStatus.APPROVED]
    return {
        "user_id": other.id,
        "im_user_id": other.im_user_id,
        "nickname": profile.nickname if profile else "",
        "avatar_url": request.build_absolute_uri(approved[0].file.url) if approved else None,
        "matched_at": match.created_at,
    }
```

`chatapp/discovery/urls.py` 不动(它挂在 `/api/v1/discovery/`),`matches` 要挂在 `/api/v1/` 下面 —— 在 `chatapp/config/api_urls.py` 的 `discovery/` 行**下面**加:

```python
    path("matches", discovery_views.match_list),
```

并把 `api_urls.py` 顶部改成:

```python
from django.urls import include, path

from accounts.views import health
from discovery import views as discovery_views
```

- [x] **Step 4:运行测试确认通过**

```bash
python manage.py test discovery
```

预期:30 个用例(26 + 4)全部 OK。

- [x] **Step 5:提交**

```bash
cd "D:/pycharmproject/chat_app" && git add chatapp/discovery chatapp/config && git commit -m "feat: GET /matches for conversation warm-up (M1b)"
```

---

### Task 9: 全量验证 + 真实 IM 冒烟 + 文档收尾

**Files:**
- Modify: `CLAUDE.md`
- 无新代码

**Interfaces:**
- Consumes: 前面全部 Task。
- Produces: 一份真实腾讯云 IM 的冒烟记录(证明 userSig/账号导入/自定义消息三个环节在真环境可用);CLAUDE.md 更新到 M1b 状态;M2 的交接说明。

- [x] **Step 1:全量测试**

```bash
cd "D:/pycharmproject/chat_app/chatapp" && python manage.py check && python manage.py test
```

预期:全绿(约 75+ 个用例)。

- [x] **Step 2:真实 IM 冒烟(会打到腾讯云,消耗少量体验版额度)**

```bash
python manage.py shell -c "
from im import client
print('导入 A:', client.import_account('u9001', '冒烟A'))
print('导入 B:', client.import_account('u9002', '冒烟B'))
print('互发灰条:', client.send_match_notice('u9001', 'u9002'))
"
```

预期:三行都是 `True`(内部 `ErrorCode == 0`)。可去 IM 控制台「账号管理」看 `u9001`/`u9002` 是否已存在。

⚠️ 若 `send_match_notice` 返回 False:先看日志里的 `ErrorCode` —— `7015`=账号不存在(先导入)、`70003`=userSig 无效(检查密钥/时钟)。字段名若被拒,以腾讯云官方文档「单发单聊消息」为准核对后调整 `im/client.py` 的 `send_custom_elem`(这是本计划唯一预留了"按文档微调"的地方)。

- [x] **Step 3:本地接口冒烟(可选,验证 REST 与业务串起来)**

起服务后(⚠️ 先确认 8000 端口没有残留 runserver):

```bash
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/v1/auth/sms/verify -H "Content-Type: application/json" -d '{"phone":"13800138000","code":"123456"}' | python -c "import sys,json;print(json.load(sys.stdin)['access'])")
curl -s http://127.0.0.1:8000/api/v1/discovery/candidates -H "Authorization: Bearer $TOKEN"
curl -s -X POST http://127.0.0.1:8000/api/v1/discovery/swipe -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"target_user_id":2,"action":"like"}'
curl -s -X POST http://127.0.0.1:8000/api/v1/im/user_sig -H "Authorization: Bearer $TOKEN"
curl -s http://127.0.0.1:8000/api/v1/matches -H "Authorization: Bearer $TOKEN"
```

(需要先在 dev 库造两个资料完整的用户;中文一律别走 `-d`,见 CLAUDE.md 的 Git Bash 编码提醒。)

- [x] **Step 4:更新 CLAUDE.md**

- 「当前进度」改成:**M1 后端全量完成**(M1a 认证/资料 + M1b IM/滑卡配对),下一步 M2 前端全量
- 接口表补四行:`POST /im/user_sig`、`GET /discovery/candidates`、`POST /discovery/swipe`、`GET /matches`
- 「腾讯云 IM 集成要点」补:代码位置 `chatapp/im/signature.py` + `chatapp/im/client.py`、`SyncOtherMachine=2`、灰条消息格式 `TIMCustomElem{type:"match_notice"}`、Desc 文案、配对时双方互发
- 记一条踩坑:测试里 on_commit 要用 `captureOnCommitCallbacks(execute=True)`

- [x] **Step 5:勾计划 + 提交**

```bash
cd "D:/pycharmproject/chat_app" && git add CLAUDE.md docs/superpowers/plans/2026-09-10-m1b-im-discovery.md && git commit -m "docs: M1b done — im + discovery APIs (M1b)"
```

---

## M1b 验收清单(全部通过即进入 M2 前端计划)

- [x] `python manage.py test` 全绿;`manage.py check` 无问题
- [x] 真实 IM 冒烟:账号导入 ×2 + 互发灰条 均为 True
- [x] `POST /im/user_sig` 能拿到 userSig(可 `decode_user_sig` 核对 identifier = `u{id}`)
- [x] 互喜配对:第二次划卡返回 `matched: true` 且 `Match` 只有一条、灰条只发一次
- [x] `banned_light` 滑卡 403;`banned_heavy` 取 userSig 403
- [x] `git status` 干净;`docs/superpowers/plans/2026-09-10-m1b-im-discovery.md` 已提交

## 留给 M2 的接口约定(前端直接用)

| 事项 | 约定 |
|---|---|
| IM 初始化 | `sdkappid` 来自 `POST /im/user_sig` 响应(或 `--dart-define`);登录用响应里的 `user_sig` |
| IM 账号 ID | 一律 `u{user_id}`;`JWT.user_id` 是字符串,拼之前先 `int()` |
| 灰条消息 | `TIMCustomElem`,`Data` = `{"type":"match_notice"}`,`Desc` = "你们已互相喜欢,开始聊天吧";客户端拦截该类型渲染成居中灰条,不进普通消息流 |
| 卡片数据 | `GET /discovery/candidates`(字段:`user_id/nickname/gender/age/city/bio/tags/photos`) |
| 滑卡 | `POST /discovery/swipe`,命中 `{"matched": true}` 播配对动效;重复提交安全(幂等) |
| 会话列表 | 数据源 = IM 会话;昵称/头像用 `GET /matches` 预热到本地缓存 |
| 错误处理 | 403 = 封禁/未完善;429 = 划太快(前端可静默退避) |
