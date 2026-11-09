# 多端同时在线(一个 App + 一个网页)实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: 本仓库**不使用** subagent-driven-development / executing-plans 派子 agent ——
> 实现按 [`~/.dsh/AGENTS.md`](../../../../AGENTS.md) 走**工单**:每张工单开成 issue 评论 `@agent` 交给 WSL 的 superagent worker,
> 本会话只做设计与验收。步骤用 checkbox(`- [ ]`)跟踪,worker 在 issue 里勾。

**Spec:** [2026-11-08-multi-device-session-design.md](../specs/2026-11-08-multi-device-session-design.md)

**Goal:** 一个账号可同时在线 1 个 App + 1 个网页,同类(两个 App / 两个网页)仍互顶;任一端读了,另一端未读跟着清零。

**Architecture:** 把「会话版本」从 `User` 单列下沉成 `(user, client_type)` 的端会话行(Django `accounts.DeviceSession` + imserver `im_device_session`),
JWT 与 IM token 都带 `ct` claim 自证端类型;imserver `SessionRegistry` 从 `uid → 单连接` 改为 `uid → {端 → 连接}` 并扇出;
跨端已读新增下行帧 `self_read`(不能复用 `read` 帧 —— 那帧语义是「**对端**读到 seq」)。

**Tech Stack:** Django 5.2 + DRF + SimpleJWT;imserver C++20(MySQL + Redis);Flutter 3.47;Vue 3 + TypeScript。

## Global Constraints

- **一单一条栈**:backend / imserver / app / web 各自独立工单;唯一例外是**契约联动**(WS 帧改动必须 fixture + imserver + App + Web 同一次 PR)。
- **验证唯一入口** `scripts/verify.sh <stack>`(backend / imserver / app / web);推之前必须绿,末尾输出贴进 PR 正文。
- **新增/改 `.py` 必须补模块与函数 docstring,公开函数带 `Args:`**(`test_*`、`setUp`、`Meta`、函数内闭包豁免),否则 `CommentCoverageTests` 红。
- **改 `/api/v1` 接口必须同改 `docs/api/` 分册**,并重新生成 `docs/api/openapi.yml`(禁止手改):
  `cd chatapp && python manage.py spectacular --file ../docs/api/openapi.yml --validate`。
- **改 WS 帧必须四处同改**:`imserver/tests/fixtures/ws/*.json` + imserver(`frames.h`/`ws_server.cpp`)+ App(`self_im_client.dart` + `protocol_fixture_test.dart`)+ Web(`web/src/im/self/*` + `im-protocol-fixture.spec.ts`)。
- **不要自己合并、不开 auto-merge**;碰 `app/` 的 UI 可见改动 PR 开成 draft 并写「等待模拟器验收」。
- **绝对不要**:改 `flutter/`、`.remember/`、`.env`、密钥文件;升版本号 / 打 tag / 建 Release(发版单独一轮)。
- **回滚点**:后端 SHA + imserver 镜像 tag 必须**成对**回退(单回一端会因 `sv` 语义不一致互相拒绝)。

## 工单映射

| 工单 | Task | 栈 | 依赖 |
|---|---|---|---|
| **K-1** | Task 1 + Task 2 | backend | — |
| **K-2** | Task 3 | imserver | 与 K-1 同窗口上线 |
| **K-3** | Task 4 | imserver(主)+ App + Web | K-2 |
| **K-4** | Task 5 | App + Web | 不阻塞发布 |

**发版节奏**:K-1 + K-2 纯服务端,先上线**不升版本**(R4 有先例);K-3 + K-4 含 App/Web 源码改动,随 **1.0.11** 一起发。

## 文件结构

**backend(K-1)**
| 文件 | 职责 |
|---|---|
| `chatapp/accounts/models.py`(改) | 新增 `DeviceSession` 模型;`User.session_version` 标 deprecated |
| `chatapp/accounts/device_session.py`(新) | 端类型判定、版本递增、版本查询 —— 鉴权/登录/刷新三处共用的唯一入口 |
| `chatapp/accounts/migrations/0006_devicesession.py`(新) | 建表 + **桥接数据迁移**(给现有用户按 `session_version` 补两行) |
| `chatapp/accounts/tokens.py`(改) | JWT 加 `ct` claim |
| `chatapp/accounts/authentication.py`(改) | 按 `(user, ct)` 校验 |
| `chatapp/accounts/views.py`(改) | `sms_verify` 只递增本端;`refresh` 按端校验;新增 `logout/all` |
| `chatapp/im/token.py`(改) | `mint_im_token` 加 `client_type` → `ct` claim |
| `chatapp/im/client.py`、`self_client.py`(改) | `kick_user` / `set_session_version` 带 `client_type` |
| `chatapp/im/tasks.py`(改) | `kick_pending_key` 加端维度;`sync_session_version` 同步两端 |
| `chatapp/im/views.py`(改) | `user_sig` 只踢本端、按端取版本签发 |
| `chatapp/accounts/test_device_session.py`(新) | K-1 的全部后端用例 |

**imserver(K-2 / K-3)**
| 文件 | 职责 |
|---|---|
| `imserver/migrations/005_device_session.sql`(新) | `im_device_session` 表 + 从 `im_user.session_version` 回填 |
| `imserver/src/auth/token.h` / `token.cpp`(改) | `TokenClaims.ct`;`mint_token` 加 `ct` |
| `imserver/src/store/user_repo.h` / `user_repo.cpp`(改) | `session_version(uid, ct)` / `set_session_version(uid, ct, v)` |
| `imserver/src/service/session_registry.h` / `session_registry.cpp`(改) | 多连接 + 扇出 + 按端踢 |
| `imserver/src/net/ws_server.cpp`(改) | 鉴权传 `ct`;注册按端;`read` 扇出 `self_read` |
| `imserver/src/net/http_api.cpp`(改) | `/internal/kick`、`/internal/session_version` 带 `client_type` |
| `imserver/src/net/frames.h`(改) | 新增 `self_read_frame` |
| `imserver/tests/*`(改/新) | 多端 unit + integration 用例 |

**App / Web(K-3 / K-4)**
| 文件 | 职责 |
|---|---|
| `app/lib/im/self_im_client.dart`(改) | 解析 `self_read` → `ImSelfRead` 事件 |
| `app/lib/core/api_client.dart` 或等价(改) | 全量请求带 `X-Client: app` |
| `app/test/im/protocol_fixture_test.dart`(改) | 吃新 fixture 帧 |
| `web/src/im/self/client.ts`、`types.ts`(改) | 解析 `self_read`;`selfRead` 事件 |
| `web/src/stores/chat.ts`(改) | `self_read` → 未读清零;复核 `multiAccount` |
| `web/tests/unit/im-protocol-fixture.spec.ts`(改) | 吃新 fixture 帧 |

---

### Task 1: 端会话表 + 按端鉴权(backend)

**Files:**
- Modify: `chatapp/accounts/models.py:78-92`
- Create: `chatapp/accounts/device_session.py`
- Create: `chatapp/accounts/migrations/0006_devicesession.py`(用 `makemigrations` 生成后手工加 `RunPython`)
- Modify: `chatapp/accounts/tokens.py`
- Modify: `chatapp/accounts/authentication.py:20-42`
- Modify: `chatapp/accounts/views.py:205-232`(verify)、`:288-300`(`_reuse_within_grace`)、`:340-346`(refresh)
- Test: `chatapp/accounts/test_device_session.py`(新建)

**Interfaces:**
- Produces:
  - `accounts.device_session.CLIENT_APP: str = "app"`、`CLIENT_WEB: str = "web"`
  - `accounts.device_session.client_type_of(request) -> str`(缺省 `"app"`)
  - `accounts.device_session.bump(user, client_type: str) -> int`(返回新版本)
  - `accounts.device_session.version_of(user_id: int, client_type: str) -> int | None`
  - `DeviceSession(user, client_type, version, created_at)`,`UniqueConstraint(user, client_type)`
  - JWT claim `ct: "app" | "web"`

- [ ] **Step 1: 写失败用例**

```python
"""多端在线的端会话表与按端鉴权(批次 K / K-1)。"""

from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APITestCase

from accounts.models import User
from accounts.device_session import CLIENT_APP, CLIENT_WEB, version_of


class DeviceSessionAuthTests(APITestCase):
    """一个 App + 一个网页可同时在线;同类互顶。"""

    def setUp(self):
        with patch("im.tasks.import_account.delay"), \
                patch("im.tasks.sync_session_version.delay"), \
                patch("im.tasks.kick_pending.apply_async"):
            self.user = User.objects.create_user(phone="13800000001")

    def _login(self, client_type="app"):
        """走真实短信登录链路(开发期固定码 123456)。"""
        self.client.post("/api/v1/auth/sms/send", {"phone": self.user.phone}, format="json")
        headers = {"HTTP_X_CLIENT": client_type} if client_type else {}
        return self.client.post(
            "/api/v1/auth/sms/verify",
            {"phone": self.user.phone, "code": "123456"},
            format="json", **headers,
        )

    def test_app_and_web_coexist(self):
        """App 登录后 Web 登录,App 的 access 仍然可用。"""
        access_app = self._login(CLIENT_APP).data["access"]
        access_web = self._login(CLIENT_WEB).data["access"]
        for token in (access_app, access_web):
            response = self.client.get(
                "/api/v1/users/me", HTTP_AUTHORIZATION=f"Bearer {token}")
            self.assertEqual(response.status_code, 200)

    def test_same_client_kicks_previous(self):
        """同端第二次登录顶掉前一个(401 + 40101)。"""
        first = self._login(CLIENT_APP).data["access"]
        self._login(CLIENT_APP)
        response = self.client.get(
            "/api/v1/users/me", HTTP_AUTHORIZATION=f"Bearer {first}")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data["code"], 40101)

    def test_version_is_per_client(self):
        """两端各有一行,互不覆盖。"""
        self._login(CLIENT_APP)
        app_version = version_of(self.user.id, CLIENT_APP)
        self._login(CLIENT_WEB)
        self.assertEqual(version_of(self.user.id, CLIENT_APP), app_version)
        self.assertEqual(version_of(self.user.id, CLIENT_WEB), app_version + 1)
```

- [ ] **Step 2: 跑一遍确认失败**

Run: `cd chatapp && python manage.py test accounts.test_device_session -v 2`
Expected: FAIL —— `ModuleNotFoundError: No module named 'accounts.device_session'`

- [ ] **Step 3: 建模型**

`chatapp/accounts/models.py`(放在 `User` 类之后):

```python
CLIENT_TYPE_CHOICES = [("app", "App"), ("web", "网页端")]


class DeviceSession(models.Model):
    """一个账号在某一类端上的会话(多端在线,批次 K)。

    设计要点:
        ``unique(user, client_type)`` 就是「同类互顶」的全部实现 —— 同端第二次
        登录把该行 ``version + 1``,旧令牌随即对不上。一个 App + 一个网页各一行,
        互不影响。

    Attributes:
        user: 所属账号。
        client_type: ``app`` 或 ``web``。
        version: 该端的会话版本;JWT 与 IM token 都带这个值。
        created_at: 首次在该端登录的时间。
    """

    user = models.ForeignKey("accounts.User", on_delete=models.CASCADE,
                             related_name="device_sessions", verbose_name="账号")
    client_type = models.CharField("端类型", max_length=8, choices=CLIENT_TYPE_CHOICES)
    version = models.PositiveIntegerField("会话版本", default=1)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        """约束:一个账号每类端只有一行。"""

        constraints = [
            models.UniqueConstraint(fields=["user", "client_type"],
                                    name="uniq_device_session_user_client"),
        ]
```

同时把 `User.session_version` 的 docstring 改成 deprecated(字段保留,不再参与鉴权):

```python
    # DEPRECATED(批次 K):多端在线后鉴权改看 accounts.DeviceSession.version;
    # 本列只作为迁移桥接的历史值保留,不再读写。删除是独立清理项。
    session_version = models.PositiveIntegerField("会话版本(已弃用)", default=SESSION_VERSION_DEFAULT)
```

- [ ] **Step 4: 建服务层**

`chatapp/accounts/device_session.py`:

```python
"""端会话:客户端类型判定与「按端」的会话版本读写。

设计要点:
    1. **判端只看请求头,鉴权只看令牌** —— 签发时用 ``X-Client`` 决定写哪一端,
       之后一律用令牌里的 ``ct`` claim 回查,避免某个请求漏带头就把另一端顶掉;
    2. 缺省一律 ``app``:线上 1.0.10 及更早的 APK 不带 ``X-Client``,不能因此掉线;
    3. 版本递增用 ``F()`` 在数据库内自增,并发登录不会两个请求都拿到同一个旧版本。
"""

from django.db.models import F

from .models import DeviceSession

CLIENT_APP = "app"
CLIENT_WEB = "web"
CLIENT_TYPES = (CLIENT_APP, CLIENT_WEB)


def client_type_of(request) -> str:
    """按请求头判定客户端类型。

    Args:
        request: DRF 请求对象。

    Returns:
        ``"web"`` 或 ``"app"``;头缺失、为空或取值未知时返回 ``"app"``。
    """
    value = (request.headers.get("X-Client") or "").strip().lower()
    return CLIENT_WEB if value == CLIENT_WEB else CLIENT_APP


def bump(user, client_type: str) -> int:
    """把账号在某一端上的会话版本 +1。

    Args:
        user: 目标账号。
        client_type: ``"app"`` 或 ``"web"``。

    Returns:
        递增后的新版本号;该端首次登录时建行并返回 2(初始行版本 1 再加一)。
    """
    session, _ = DeviceSession.objects.get_or_create(
        user=user, client_type=client_type)
    DeviceSession.objects.filter(pk=session.pk).update(version=F("version") + 1)
    session.refresh_from_db(fields=["version"])
    return session.version


def version_of(user_id: int, client_type: str):
    """取账号在某一端上的当前会话版本。

    Args:
        user_id: 账号 id。
        client_type: ``"app"`` 或 ``"web"``。

    Returns:
        当前版本号;该端从未登录过(没有行)返回 ``None`` —— 调用方应据此拒绝。
    """
    return (DeviceSession.objects
            .filter(user_id=user_id, client_type=client_type)
            .values_list("version", flat=True)
            .first())
```

- [ ] **Step 5: 迁移(建表 + 桥接数据)**

Run: `cd chatapp && python manage.py makemigrations accounts`
然后手工在生成的迁移里追加数据迁移(否则线上老令牌会集体失效):

```python
def bridge_existing_users(apps, schema_editor):
    """给每个已有账号按历史 session_version 补两行端会话。

    线上老令牌没有 ``ct`` claim,按 ``app`` 兜底;它的 ``session_version`` 等于
    ``User.session_version``,所以这里必须用同一个值建行,否则升级瞬间所有 App 掉线。
    """
    User = apps.get_model("accounts", "User")
    DeviceSession = apps.get_model("accounts", "DeviceSession")
    rows = [
        DeviceSession(user_id=user.id, client_type=client_type,
                      version=user.session_version)
        for user in User.objects.all()
        for client_type in ("app", "web")
    ]
    DeviceSession.objects.bulk_create(rows, ignore_conflicts=True)


def noop(apps, schema_editor):
    """回滚:端会话表会被整表删除,无需单独反做。"""
```

`migrations.RunPython(bridge_existing_users, noop)` 挂在建表之后。

- [ ] **Step 6: 令牌带 `ct`**

`chatapp/accounts/tokens.py` —— 两个 `for_user` 都加一行:

```python
        token["session_version"] = user.session_version
        token["ct"] = client_type      # 新增参数,见下
```
把 `for_user(cls, user)` 改成 `for_user(cls, user, client_type=CLIENT_APP)`,并在模块 docstring 里补一句「``ct`` 是端类型,鉴权按它回查端会话」。

- [ ] **Step 7: 鉴权按端**

`chatapp/accounts/authentication.py` 的 `get_user` 换成:

```python
        user = super().get_user(validated_token)
        client_type = validated_token.get("ct", CLIENT_APP)   # 老令牌按 app 兜底
        token_version = validated_token.get("session_version", SESSION_VERSION_DEFAULT)
        if token_version != version_of(user.id, client_type):
            raise SingleDeviceSessionConflict()
        touch(user.id)
        return user
```

- [ ] **Step 8: 登录与刷新按端**

`chatapp/accounts/views.py`:

```python
    # 多端:只递增本端版本(同类互顶),另一端不受影响
    client_type = client_type_of(request)
    device_session.bump(user, client_type)
```
替换原来的 `User.objects.filter(pk=user.pk).update(session_version=F("session_version") + 1)` 与 `user.refresh_from_db(...)`;
签发处 `SessionRefreshToken.for_user(user, client_type)`。

刷新路径的三处版本比对(宽限期复用、`post` 主体)统一改成:

```python
    client_type = token.get("ct", CLIENT_APP)
    if user is None or token.get("session_version") != version_of(user.id, client_type):
        raise SingleDeviceSessionConflict()
```
`_respond` 里换发 access 时同样用 `token.get("ct", CLIENT_APP)` 传给 `SessionRefreshToken`(轮换后的 refresh 必须带同一个 `ct`,否则下一次刷新会掉到 app 分支)。

> **别手工补 claim**:simplejwt 的 `refresh.access_token` 会从 refresh 复制全部 claim(`ct` / `session_version` 自动带过去)。
> 要补的是**一条用例**钉住它:`web` 的 refresh 换出来的 access 拿去请求仍是 `web` 端、不会把 App 顶掉。

- [ ] **Step 9: 跑测试**

Run: `cd chatapp && python manage.py test accounts -v 2`
Expected: 全绿(既有用例里直接改 `session_version` 的两处 —— `tests.py:650`、`:1090` —— 要改成改 `DeviceSession.version`,否则会红)

- [ ] **Step 10: 提交**

```bash
git add chatapp/accounts
git commit -m "feat(accounts): 端会话表 + 按端鉴权(多端在线 K-1)"
```

---

### Task 2: IM 踢人链路按端 + 退出所有设备 + 文档(backend)

**Files:**
- Modify: `chatapp/im/token.py:10-33`
- Modify: `chatapp/im/client.py:139-162`
- Modify: `chatapp/im/self_client.py:135-147`
- Modify: `chatapp/im/tasks.py:30-43`、`:287-309`、`:347-363`
- Modify: `chatapp/im/views.py:79-99`
- Modify: `chatapp/accounts/views.py`(新增 `logout_all`)
- Modify: `chatapp/config/urls.py`(或 `accounts/urls.py`,按现有 logout 注册位置)
- Modify: `docs/api/auth.md`、`docs/api/im.md`、`docs/pitfalls/backend.md`、`CLAUDE.md`
- Test: `chatapp/accounts/test_device_session.py`(追加)、`chatapp/im/tests.py`(追加)

**Interfaces:**
- Consumes:`device_session.client_type_of / bump / version_of`(Task 1)
- Produces:
  - `mint_im_token(user_id: int, ttl: int, session_version: int = 0, client_type: str = "app") -> str`(payload 多 `ct`)
  - `im_client.kick_user(identifier: str, block: bool = False, client_type: str | None = None) -> bool`(`None` = 踢全部)
  - `im_client.set_session_version(identifier: str, version: int, client_type: str = "app") -> bool`
  - `im_tasks.kick_pending_key(user_id: int, client_type: str) -> str` → `im:kick_pending:{uid}:{ct}`
  - `POST /api/v1/auth/logout/all` → 204

- [ ] **Step 1: 写失败用例**

```python
class KickChainTests(TestCase):
    """登录只标记本端待踢;user_sig 只踢本端;退出所有设备两端都失效。"""

    def test_kick_pending_key_is_per_client(self):
        """两端各自一个标记,互不覆盖。"""
        from im.tasks import kick_pending_key
        self.assertNotEqual(kick_pending_key(7, "app"), kick_pending_key(7, "web"))

    def test_user_sig_kicks_only_own_client(self):
        with patch("im.tasks.import_account.delay"), \
                patch("im.tasks.sync_session_version.delay"), \
                patch("im.views.kick_user") as kick, \
                patch("im.views.ensure_account", return_value=True), \
                patch("im.views.set_session_version", return_value=True):
            cache.set(kick_pending_key(self.user.id, "web"), 1, 300)
            self.client.get("/api/v1/users/me", HTTP_AUTHORIZATION=f"Bearer {access_app}")
            response = self.client.post("/api/v1/im/user_sig", HTTP_X_CLIENT="app")
        self.assertEqual(response.status_code, 200)
        kick.assert_called_once_with(self.user.im_user_id, client_type="app")
        self.assertIsNotNone(cache.get(kick_pending_key(self.user.id, "web")))
```

- [ ] **Step 2: 跑一遍确认失败** → Run: `cd chatapp && python manage.py test accounts.test_device_session -v 2`;Expected: FAIL(TypeError: 参数个数不对)

- [ ] **Step 3: token / client / tasks / views 按端改造**

`chatapp/im/token.py`:

```python
def mint_im_token(user_id: int, ttl: int, session_version: int = 0,
                  client_type: str = "app") -> str:
    """签发一个 IM token。

    Args:
        user_id: 账号 id。
        ttl: 有效期(秒)。
        session_version: 签发时**该端**的会话版本;imserver 用它拒绝被顶下线的旧 token。
        client_type: ``app`` 或 ``web``;imserver 按它查端会话行。

    Returns:
        HS256 JWT 字符串(payload 含 ``sv`` 与 ``ct``)。
    """
```
payload 里加 `"ct": client_type`。

`chatapp/im/tasks.py`:

```python
def kick_pending_key(user_id: int, client_type: str) -> str:
    """拼出「待踢旧会话」标记的缓存键(按端)。

    Args:
        user_id: 账号 id。
        client_type: ``app`` 或 ``web``。

    Returns:
        Redis 键名 ``im:kick_pending:{user_id}:{client_type}``。
    """
    return f"im:kick_pending:{user_id}:{client_type}"
```
`kick_pending(user_id, client_type="app")` 任务加参数、内部 `im_client.kick_user(user.im_user_id, client_type=client_type)`;
`sync_session_version(user_id)` 改成循环两端:

```python
    for client_type in CLIENT_TYPES:
        version = device_session.version_of(user.id, client_type)
        if version is None:
            continue
        _require(im_client.set_session_version(user.im_user_id, version,
                                               client_type=client_type),
                 "set_session_version")
```

`chatapp/im/views.py` 的 `user_sig`:取 `client_type = client_type_of(request)`;`kick_pending_key(user.id, client_type)`;
`kick_user(user.im_user_id, client_type=client_type)`;`version = version_of(user.id, client_type)`(为 `None` 返回 503,不签旧版本);
`mint_im_token(user.id, settings.IM_SELF_TOKEN_TTL, version, client_type)`。

- [ ] **Step 4: 新增「退出所有设备」**

`chatapp/accounts/views.py`:

```python
@extend_schema(responses={204: None})
@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([LogoutThrottle])
def logout_all(request):
    """退出所有设备:两端会话版本各 +1,并踢掉在线 IM 会话。

    Args:
        request: DRF 请求对象(必须已认证)。

    Returns:
        204 空响应;之后两端的 access 与 refresh 全部失效。
    """
    user = request.user
    for client_type in CLIENT_TYPES:
        device_session.bump(user, client_type)
    im_tasks.kick_all_devices.delay(user.id)   # 响应路径不做外部调用
    response = Response(status=204)
    clear_refresh_cookie(response)
    return response
```

`chatapp/im/tasks.py` 新增:

```python
@shared_task(**RETRY_POLICY)
def kick_all_devices(user_id: int) -> None:
    """把账号所有端的在线 IM 会话踢下线(退出所有设备)。

    Args:
        user_id: 账号 id。

    Raises:
        RuntimeError: 踢下线失败,交给 ``RETRY_POLICY`` 重试。
    """
    user = _user(user_id)
    if user is None:
        return
    _require(im_client.kick_user(user.im_user_id), "kick_user")
```

- [ ] **Step 5: 文档**

- `docs/api/auth.md`:`POST /auth/logout/all` 一整节(用途 / 鉴权 / 请求头 / 响应 / 错误码 / 示例);`sms/verify` 与 `token/refresh` 的说明补「`X-Client` 决定端类型,缺省 `app`」;
- `docs/api/im.md`:`user_sig` 说明「只踢本端旧会话」;
- `CLAUDE.md`「单设备登录」那条契约改写成「**多端**:一个 App + 一个网页;同类互顶」;
- `docs/pitfalls/backend.md` 加一条:踢人顺序不能反(老坑)+ 多端后标记必须带端维度;
- **审计结论作废声明**(spec §8):在 `docs/security/` 最近那份报告的「单设备登录」条目加状态注记
  ——「2026-11-08 起改为多端:一个 App + 一个网页,同类互顶;单设备作为防共享手段**已作废**,替代措施见
  `docs/superpowers/specs/2026-11-08-multi-device-session-design.md` §8」。**不加这条,下一个人会把它当成回归。**

- [ ] **Step 6: 重生成 openapi 并跑门禁**

```bash
cd chatapp && python manage.py spectacular --file ../docs/api/openapi.yml --validate
python manage.py test
```
Expected:全绿(含 `ApiDocsCoverageTests`、`test_schema_contract.py`、`CommentCoverageTests`)

- [ ] **Step 7: 提交**

```bash
git add chatapp docs CLAUDE.md
git commit -m "feat(accounts): 按端踢人与退出所有设备(K-1)"
```

---

### Task 3: imserver 多连接 + 按端版本(imserver)

**Files:**
- Create: `imserver/migrations/005_device_session.sql`
- Modify: `imserver/src/migrate.cpp:68-75`(迁移表加一行)
- Modify: `imserver/src/auth/token.h`、`token.cpp`
- Modify: `imserver/src/store/user_repo.h`、`user_repo.cpp:110-150`
- Modify: `imserver/src/service/session_registry.h`、`session_registry.cpp`
- Modify: `imserver/src/net/ws_server.cpp:390-400`(鉴权)、注册/注销、`:682-690`(`kick`)
- Modify: `imserver/src/net/http_api.cpp:255-270`、`:400-440`
- Test: `imserver/tests/integration/test_multi_device.py`(新)

**Interfaces:**
- Consumes:token payload `ct`(Task 2)
- Produces:
  - `struct TokenClaims` 原有字段不变,新增 `std::string ct = "app";`(缺省 `app` 兼容老 token)
  - `std::string mint_token(uint64_t uid, std::string_view secret, int64_t now_ms, int64_t ttl_seconds, std::string_view ct = "app")`
  - `std::optional<int64_t> UserRepo::session_version(uint64_t uid, std::string_view ct)`
  - `void UserRepo::set_session_version(uint64_t uid, std::string_view ct, int64_t version)`
  - `void SessionRegistry::register_session(uint64_t uid, std::string_view ct, std::shared_ptr<WsSession>)`
  - `bool SessionRegistry::send_to(uint64_t uid, const std::string& frame)` —— **扇出到本人所有端**
  - `void SessionRegistry::kick(uint64_t uid, const std::string& reason)` —— 踢全部
  - `void SessionRegistry::kick_client(uint64_t uid, std::string_view ct, const std::string& reason)`
  - `bool SessionRegistry::unregister(uint64_t uid, std::string_view ct, WsSession* session)`

- [ ] **Step 0: 先核实两个闸门(spec §4.5),核实结果写进 issue 评论**

```bash
git grep -n 'conversation_delete\|handle_revoke\|send_to(' -- imserver/src/net/ws_server.cpp
git grep -n 'im:online' -- imserver/src
```

回答两个问题,再决定改动范围:

1. **本人操作要不要扇出到自己的其他设备** —— 已读(本批要做)、**删除会话**、**撤回消息**。
   撤回如果已经向「双方」广播,自己另一端是否已覆盖?删除会话如果只在本地连接上处理,另一台设备的会话列表就会留着这条,要纳入本批。
   把结论写成一句「X 已覆盖 / Y 需要扇出」,不要重复做已覆盖的。
2. **`im:online:{uid}` 在多端下是否仍成立** —— 现在按 uid 写、任一端活跃即在线,应当天然成立;
   但要补一条测试钉住「app 断开、web 还在 → 仍算在线」。

- [ ] **Step 1: 写失败用例(集成层,不是 C++ 单测)**

`WsSession` 是 websocketpp 的会话对象,单测里造不出来;连接级行为按仓库既有做法写在 Python 集成测试里
(参照 `imserver/tests/integration/test_read.py` 的 `token/auth/recv_until` 写法)。新建
`imserver/tests/integration/test_multi_device.py`:

```python
"""多端在线的集成测试:同账号两端并存、扇出、同类互顶、按端踢人。

覆盖批次 K 的四条验收:
    1. 同一账号 `app` 与 `web` 两条连接**并存**,一条发消息另一条也能收到下行;
    2. 同端第二条连接会把第一条踢掉(`kicked` reason=`multi_device`);
    3. 按端版本:把 `web` 的版本 +1 后,`web` 旧 token 连不上,`app` 不受影响;
    4. `/internal/kick` 带 `client_type` 时只踢该端。
"""

import asyncio
import json
import os
import time
import urllib.request

import jwt
import websockets

from _support import ensure, pair

SECRET = os.environ["IM_JWT_SECRET"]
WS = os.environ.get("IM_TEST_WS", "ws://127.0.0.1:19100/im/ws")


def token(uid: int, client_type: str, sv: int = 0) -> str:
    """签一个带端类型的测试 JWT(与 Django 侧 `mint_im_token` 同口径)。"""
    now = int(time.time())
    payload = {"sub": f"u{uid}", "uid": uid, "iat": now, "exp": now + 3600,
               "jti": "test", "ct": client_type}
    if sv:
        payload["sv"] = sv
    return jwt.encode(payload, SECRET, algorithm="HS256")


async def auth(uid: int, client_type: str, sv: int = 0):
    """连 WS 并完成握手。"""
    ws = await websockets.connect(WS)
    await ws.send(json.dumps({"v": 1, "type": "auth",
                              "data": {"token": token(uid, client_type, sv)}}))
    while True:
        message = json.loads(await asyncio.wait_for(ws.recv(), 3))
        if message["type"] == "auth_ok":
            return ws


async def test_two_clients_coexist_and_fan_out():
    """app 与 web 同时在线;对端发给我的消息,两端都收到。"""
    pair(1, 2)
    app_ws = await auth(1, "app")
    web_ws = await auth(1, "web")
    sender = await auth(2, "app")
    await sender.send(json.dumps({"v": 1, "type": "send",
                                  "id": "m1", "data": {"to": "u1", "kind": "text",
                                                       "text": "hi"}}))
    for ws in (app_ws, web_ws):
        frame = json.loads(await asyncio.wait_for(ws.recv(), 3))
        assert frame["type"] == "message", frame
    await app_ws.close()
    await web_ws.close()
    await sender.close()


async def test_same_client_type_kicks_previous():
    """同端第二条连接踢掉第一条。"""
    first = await auth(1, "app")
    second = await auth(1, "app")
    frame = json.loads(await asyncio.wait_for(first.recv(), 3))
    assert frame["type"] == "kicked", frame
    assert frame["data"]["reason"] == "multi_device", frame
    await first.close()
    await second.close()
```

- [ ] **Step 2: 跑一遍确认失败**

```bash
docker compose -f imserver/docker-compose.test.yml run --rm test bash /src/scripts/test_http.sh
```
Expected: FAIL —— `test_same_client_type_kicks_previous` 拿不到 `kicked`(现在两个端被当成同一个 `uid`,第二条会踢掉第一条,
但第一条的连接被踢后 `app_ws` 与 `web_ws` 无法并存,`test_two_clients_coexist_and_fan_out` 直接失败)

> **注意**:既有集成测试用 `token()` 签的 JWT **不带 `sv`**(= 0),`session_version_matches` 对 `sv=0` 一律放行
> (`imserver/src/auth/token.cpp` 末尾),所以本批改动**不需要**批量改这些测试;新用例要显式测版本时才传 `sv`。

- [ ] **Step 3: 迁移**

`imserver/migrations/005_device_session.sql`:

```sql
-- 多端在线:会话版本从 im_user 单列下沉到 (user_id, client_type)
CREATE TABLE IF NOT EXISTS im_device_session (
  user_id BIGINT NOT NULL,
  client_type VARCHAR(8) NOT NULL,
  session_version BIGINT NOT NULL,
  PRIMARY KEY (user_id, client_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 桥接:老账号两行都用 im_user.session_version,保证老 token(sv 相同、无 ct)继续可用
INSERT IGNORE INTO im_device_session (user_id, client_type, session_version)
SELECT user_id, 'app', session_version FROM im_user WHERE session_version > 0;
INSERT IGNORE INTO im_device_session (user_id, client_type, session_version)
SELECT user_id, 'web', session_version FROM im_user WHERE session_version > 0;
```

`migrate.cpp` 的 `kMigrations` 加 `{5, "005_device_session.sql"},`。

- [ ] **Step 4: token 与 user_repo**

`token.h`:`TokenClaims` 加 `std::string ct = "app";`;`mint_token` 加 `std::string_view ct = "app"` 参数;
`token.cpp` 里 `payload["ct"] = std::string(ct);`,`verify_token` 里 `claims.ct = payload.value("ct", "app");`。

`user_repo` 的两个方法改成带 `client_type`,数据源从 `im_user` 换成 `im_device_session`:

```cpp
std::optional<int64_t> UserRepo::session_version(MysqlPool::Lease& lease, uint64_t uid,
                                                 std::string_view ct) {
  // client_type 只可能是 "app" / "web"(由 token 的 ct claim 归一化而来,见 token.cpp),
  // 但仍按仓库既有写法走转义,不直接拼用户可控字符串
  auto* result = lease.query(
      "SELECT session_version FROM im_device_session WHERE user_id=" +
      std::to_string(uid) + " AND client_type='" + escape_sql(ct) + "'");
  if (result == nullptr) {
    return std::nullopt;
  }
  std::optional<int64_t> version;
  if (MYSQL_ROW values = mysql_fetch_row(result)) {
    version = values[0] == nullptr ? 0 : std::stoll(values[0]);
  }
  mysql_free_result(result);
  return version;
}

void UserRepo::set_session_version(uint64_t uid, std::string_view ct, int64_t version) {
  // upsert:同步任务可能早于端会话行存在,补一行(与 im_user 那版同理)
  auto lease = pool_.acquire();
  Stmt stmt(lease.get(),
            "INSERT INTO im_device_session (user_id,client_type,session_version) "
            "VALUES (?,?,?) ON DUPLICATE KEY UPDATE session_version=VALUES(session_version)");
  stmt.bind_uint(0, uid);
  stmt.bind_string(1, std::string(ct));
  stmt.bind_uint(2, static_cast<uint64_t>(version));
  stmt.execute();
}
```

> 读版本沿用现有 `session_version(MysqlPool::Lease&, uint64_t)` 的 `lease.query` + `mysql_fetch_row` 写法
> (`Stmt` 没有查询接口,见 `imserver/src/store/stmt.h`)。若仓库里没有现成的 `escape_sql` 辅助,
> 就按既有代码里处理字符串参数的同一种方式做(先 `git grep -n 'escape' -- imserver/src` 确认),**不要**自己发明第三套写法。

- [ ] **Step 5: SessionRegistry 多连接**

```cpp
using ClientSessions = std::unordered_map<std::string, std::weak_ptr<WsSession>>;
std::unordered_map<uint64_t, ClientSessions> sessions_;
```

```cpp
void SessionRegistry::register_session(uint64_t uid, std::string_view ct,
                                      std::shared_ptr<WsSession> session) {
  std::shared_ptr<WsSession> old;
  {
    const std::lock_guard<std::mutex> lock(mutex_);
    auto& per_client = sessions_[uid];
    auto it = per_client.find(std::string(ct));
    if (it != per_client.end()) {
      old = it->second.lock();
    }
    per_client[std::string(ct)] = session;
  }
  if (old != nullptr && old.get() != session.get()) {
    old->kick("multi_device");          // 同类互顶:只踢同端
  }
  touch_online(uid);
}

bool SessionRegistry::send_to(uint64_t uid, const std::string& frame) {
  std::vector<std::shared_ptr<WsSession>> targets;
  {
    const std::lock_guard<std::mutex> lock(mutex_);
    const auto it = sessions_.find(uid);
    if (it == sessions_.end()) {
      return false;
    }
    for (const auto& [ct, weak] : it->second) {
      if (auto session = weak.lock()) {
        targets.push_back(std::move(session));
      }
    }
  }
  for (const auto& session : targets) {
    session->send_raw(frame);           // 扇出:本人所有端都收到
  }
  return !targets.empty();
}

void SessionRegistry::kick(uint64_t uid, const std::string& reason) {
  // 踢全部:封禁 / 注销用,语义与改动前一致
  std::vector<std::shared_ptr<WsSession>> targets;
  {
    const std::lock_guard<std::mutex> lock(mutex_);
    const auto it = sessions_.find(uid);
    if (it != sessions_.end()) {
      for (const auto& [ct, weak] : it->second) {
        if (auto session = weak.lock()) {
          targets.push_back(std::move(session));
        }
      }
    }
  }
  for (const auto& session : targets) {
    session->kick(reason);
  }
}

void SessionRegistry::kick_client(uint64_t uid, std::string_view ct,
                                  const std::string& reason) {
  // 踢单端:同类互顶 / 按端下线
  std::shared_ptr<WsSession> target;
  {
    const std::lock_guard<std::mutex> lock(mutex_);
    const auto it = sessions_.find(uid);
    if (it != sessions_.end()) {
      const auto client_it = it->second.find(std::string(ct));
      if (client_it != it->second.end()) {
        target = client_it->second.lock();
      }
    }
  }
  if (target != nullptr) {
    target->kick(reason);
  }
}
```
`is_online` / `online_count` 按 uid 计,语义不变。

- [ ] **Step 6: 调用点改造**

- `ws_server.cpp` 鉴权处:`session_version_matches(claims->sv, messages_.users().session_version(claims->uid, claims->ct))`;注册传 `claims->ct`;`unregister(uid, ct, session)`。
- `http_api.cpp:261` 同样按 `claims->ct` 查版本;`/internal/session_version` 收 `{"uid","client_type","version"}` 调 `set_session_version(uid, ct, version)`;`/internal/kick` 收可选 `client_type`(缺省踢全部,保持封禁/注销语义)。
- `push_notifier` 的「目标不在线」判定仍用 `is_online(uid)`,不变。

- [ ] **Step 7: 跑 imserver 全套**

```bash
docker compose -f imserver/docker-compose.test.yml run --rm test bash /src/scripts/test_unit.sh
docker compose -f imserver/docker-compose.test.yml run --rm test bash /src/scripts/test_http.sh
```
Expected:unit 全绿 + HTTP/集成 `e2e ok`

- [ ] **Step 8: 提交**

```bash
git add imserver
git commit -m "feat(imserver): 按端注册与扇出(多端在线 K-2)"
```

---

### Task 4: 跨端已读 `self_read` 帧(imserver + App + Web,**同一个 PR**)

**Files:**
- Modify: `imserver/src/net/frames.h`(加 `self_read_frame`)
- Modify: `imserver/src/service/session_registry.h`、`session_registry.cpp`(加 `send_to_other_clients`)
- Modify: `imserver/src/net/ws_server.cpp`(`handle_read` 里向本人其他端扇出)
- Modify: `imserver/tests/fixtures/ws/server_to_client.json`
- Modify: `imserver/tests/frames_fixture_test.cpp`
- Create: `imserver/tests/integration/test_self_read.py`
- Modify: `app/lib/im/self_im_client.dart`、`app/test/im/protocol_fixture_test.dart`
- Modify: `web/src/im/self/types.ts`、`web/src/im/self/client.ts`、`web/src/stores/chat.ts`、`web/tests/unit/im-protocol-fixture.spec.ts`

**Interfaces:**
- Produces:
  - C++ `std::string self_read_frame(const std::string& peer, uint64_t seq)`
  - 下行帧 `{"v":1,"type":"self_read","data":{"peer":"u12","seq":42}}`
  - App:`ImSelfRead(peer, seq)` 事件 `selfRead`
  - Web:`selfRead` 事件,payload `{ peer: string; seq: number }`

- [ ] **Step 1: fixture 先行**

`imserver/tests/fixtures/ws/server_to_client.json` 追加一帧(与既有帧同样的字段顺序与占位约定):

```json
{
  "name": "self_read",
  "frame": {"v": 1, "type": "self_read", "data": {"peer": "u8", "seq": 42}}
}
```

- [ ] **Step 2: 三端各写一条失败用例**

App(`app/test/im/protocol_fixture_test.dart`):

```dart
test('self_read 帧解析成 ImSelfRead 事件', () async {
  final client = buildFixtureClient();
  final events = <ImEvent>[];
  client.events.listen(events.add);
  client.receiveForTest(fixtureFrame('self_read'));
  await pumpEventQueue();
  expect(events.whereType<ImSelfRead>().single.peer, 'u8');
  expect(events.whereType<ImSelfRead>().single.seq, 42);
});
```

Web(`web/tests/unit/im-protocol-fixture.spec.ts`):

```ts
it('self_read 帧解析成 selfRead 事件', () => {
  const client = makeFixtureClient()
  const seen: Array<{ peer: string; seq: number }> = []
  client.on('selfRead', (p) => seen.push(p))
  client.receiveForTest(fixtureFrame('self_read'))
  expect(seen).toEqual([{ peer: 'u8', seq: 42 }])
})
```

imserver(`imserver/tests/frames_fixture_test.cpp`):断言 `self_read_frame("u8", 42)` 与 fixture 逐字段一致。

- [ ] **Step 3: 跑三端确认失败**

```bash
docker compose -f imserver/docker-compose.test.yml run --rm test bash /src/scripts/test_unit.sh   # 编译失败
cd app && ../flutter/bin/flutter.bat test test/im/protocol_fixture_test.dart                      # ImSelfRead 未定义
cd web && npm run test:run -- im-protocol-fixture                                                 # 事件未触发
```

- [ ] **Step 4: 实现**

`frames.h`:

```cpp
/// 跨端已读:告诉**我自己的其他设备**「我在这一端把与 `peer` 的会话读到了 seq」。
/// 不能复用下行 `read` 帧 —— 那帧的语义是「**对端**读到 seq」,发给自己的另一台
/// 设备会被读成「对方已读」,是错的。
inline std::string self_read_frame(const std::string& peer, uint64_t seq) {
  return nlohmann::json{{"v", 1}, {"type", "self_read"},
                        {"data", {{"peer", peer}, {"seq", seq}}}}.dump();
}
```

`ws_server.cpp` 的 `handle_read`:落库并回读 `read_seq` 之后,除了向对端发 `read_frame`,再向**本人除本连接外的其他端**发 `self_read_frame`。
实现上给 `SessionRegistry` 加(声明进 `.h`,实现进 `.cpp`):

```cpp
/// 发给本人除 `except` 之外的所有端(跨端已读同步用)。
void SessionRegistry::send_to_other_clients(uint64_t uid, const WsSession* except,
                                            const std::string& frame) {
  std::vector<std::shared_ptr<WsSession>> targets;
  {
    const std::lock_guard<std::mutex> lock(mutex_);
    const auto it = sessions_.find(uid);
    if (it == sessions_.end()) {
      return;
    }
    for (const auto& [ct, weak] : it->second) {
      auto session = weak.lock();
      if (session != nullptr && session.get() != except) {
        targets.push_back(std::move(session));
      }
    }
  }
  for (const auto& session : targets) {
    session->send_raw(frame);
  }
}
```

调用点(`handle_read` 内,`peer` 是会话对端、`seq` 是回读后的真实值):

```cpp
  registry_.send_to(uid, read_frame(peer, seq));                 // 对端:你读了我的消息
  registry_.send_to_other_clients(uid, this, self_read_frame(peer, seq));  // 我自己的其他端
```

App:`self_im_client.dart` 的帧分发加 `case 'self_read'` → `emit(ImSelfRead(peer, seq))`;`ImSelfRead` 类与 `readReceipt` 能力位并列。
Web:`types.ts` 加 `SelfReadFrame`;`client.ts` 分发 `self_read` → `emit('selfRead', {peer, seq})`;`stores/chat.ts` 收到后把该会话 `unread` 置 0、`peerReadSeq` 不动(**那是对方读我**,别搞混 —— 见 `docs/pitfalls/im.md`)。

- [ ] **Step 5: 三端全绿 + 契约自测**

故意把 fixture 里 `seq` 改成 `sequence` → 三端应同时红;还原后全绿。

- [ ] **Step 6: 文档 + 提交**

`docs/ops/imserver.md` 加一节(帧语义 / 与 `read` 帧的区别 / 排查),`docs/pitfalls/im.md` 补「别把 self_read 当成对端已读」。

```bash
git add imserver app/lib/im app/test/im web/src/im web/src/stores/chat.ts web/tests docs
git commit -m "feat(im): 跨端已读 self_read 帧(多端在线 K-3)"
```

---

### Task 5: App 显式带 `X-Client` + Web 多标签复核(App + Web)

**Files:**
- Modify: `app/lib/core/api_client.dart`(或实际的 Dio 拦截器所在文件)
- Modify: `app/test/core/…`(对应用例)
- Modify: `web/src/stores/chat.ts`(仅注释/复核,除非发现缺陷)
- Modify: `web/tests/unit/chat-multi-account.spec.ts`(补断言)

**Interfaces:**
- Consumes:后端「缺 `X-Client` 按 app」兜底(Task 1)
- Produces:App 全量请求头 `X-Client: app`

- [ ] **Step 1: 写失败用例**

```dart
test('所有 API 请求都带 X-Client: app', () async {
  final adapter = RecordingAdapter();
  await apiClient.get('/users/me');
  expect(adapter.lastRequest!.headers['X-Client'], 'app');
});
```

- [ ] **Step 2: 跑确认失败** → `cd app && ../flutter/bin/flutter.bat test test/core/api_client_test.dart`;Expected: FAIL(`null != 'app'`)

- [ ] **Step 3: 实现** —— 在 Dio 拦截器里统一加头(与 `error_reporting.dart:121` 的写法保持一致,不要每处手写)。

- [ ] **Step 4: Web 复核**

在 `web/tests/unit/chat-multi-account.spec.ts` 补一条断言:同浏览器第二个标签登录后,第一个标签收到 `kicked` **不自动重连**(多端后两个标签仍属同类,应继续互顶)。若现有实现已满足,只补断言与注释;**发现缺陷才改实现**,并在 PR 正文「遗留」段写明。

- [ ] **Step 5: 跑双端**

```bash
cd app && ../flutter/bin/flutter.bat analyze && ../flutter/bin/flutter.bat test
cd web && npm run type-check && npm run lint && npm run test:run
```

- [ ] **Step 6: 提交**

```bash
git add app web
git commit -m "feat(app): 显式上报端类型 X-Client(K-4)"
```

---

## 验收(整批 K)

**自动化(各 PR 内)**:`scripts/verify.sh backend`、`imserver`、`app`、`web` 全绿;契约自测(改 fixture 字段 → 三端同时红)做过并还原。

**留给人验(合并/发布后才发生,不写进 worker 验收项)**:

1. 模拟器(App)+ 浏览器(Web)同时登录同一账号:互发消息两端都到;一端读完另一端红点消失;App 再登一次被顶的提示文案不变;
2. 生产发布后老 APK(1.0.10)仍能登录与收发(无 `ct` / 无 `X-Client` 兜底真的生效);
3. `POST /auth/logout/all` 后两端都被踢到登录页。

## 上线顺序(发布那一轮)

```
① backend(K-1)部署 + migrate(accounts.0006)
② imserver 镜像(K-2)同步上线 + docker compose run --rm imserver --migrate(应用 005)
③ 观察:im_sends_total / im_calls_total / 40101 计数无异常
④ 随 1.0.11 发 App/Web(K-3 + K-4)
```

**回滚**:后端 SHA 与 imserver 镜像 tag **成对回退**;两个迁移都是新建表,留着不影响旧代码。

---

## 执行记录

### K-3(Task 4 + 本单增补的 `conversation_deleted`,2026-11-08)

**实际完成**:`self_read`(Task 4 原定)+ `conversation_deleted`(issue #152 正文新增),
按「fixture 先行 → imserver → App → Web → 文档」的顺序做,三端在同一个 PR 里。

| 端 | 改动 |
|---|---|
| fixture | `server_to_client.json` 追加 `self_read`(`peer=u8, seq=42`)与 `conversation_deleted`(`peer=u8`),README 的下行帧清单同步 |
| imserver | `frames.h` 加 `self_read_frame` / `conversation_deleted_frame`;`SessionRegistry::send_to_other_clients(uid, except, frame)`;`ws_server.cpp` 的 `handle_read` 与 `handle_delete` 各补一次扇出;`frames_fixture_test.cpp` 加两条真实序列化断言;新增 `tests/integration/test_self_read.py`(四条用例)并挂进 `scripts/test_http.sh` |
| App | `im_client.dart` 加 `ImSelfRead` / `ImConversationDeleted` 事件与 `ImConversation.copyWith`;`self_im_client.dart` 分发两帧;`im_manager.dart` 的 switch 补分支(sealed class 必须穷尽);`conversations_controller.dart` 消费事件(未读清零 / 移除会话);`protocol_fixture_test.dart` 两条断言 + `conversations_controller_test.dart` 一条用例 |
| Web | `im/types.ts` 加 `selfRead` / `conversationDeleted` 事件;`im/self/client.ts` 分发;`stores/chat.ts` 的 `clearUnread` / `removeConversation`;`ChatPage.vue` 会话被跨端删除后自动退回列表;`im-protocol-fixture.spec.ts` 两条断言 + 新增 `chat-self-sync.spec.ts` + `chat-page.spec.ts` 一条组件用例 |
| docs | `docs/ops/imserver.md` §14.1 迁移表补 `005_device_session.sql`、§14.5 与 §16.1 的 40101 口径改成 `im_device_session`、新增 §18 写这两个帧;`docs/pitfalls/im.md` 新增「多端在线(2026-11-08,批次 K)」四条 |

**与原计划的偏差**(按仓库约定记在这里,不改 Task 4 正文):

1. **App 多做了「消费」这一步**。Task 4 只要求 `self_im_client.dart` 解析成事件;但事件没人消费就等于 App 端没有可见行为(未读不清零、会话不消失)。实际把 `ImSelfRead` → 未读清零、`ImConversationDeleted` → 列表移除放进了 `conversations_controller.dart`,只动未读数、不碰 `peerReadSeq`,与 Web store 一一对应。
2. **Web 的 `src/im/self/types.ts` 不存在**。Task 4 写的这个路径实际是 `web/src/im/types.ts`(`ImEvent` 联合类型在那里,`src/im/self/` 只有 `client/map/image/voice/transport`)。
3. **Web 聊天页新增「会话被删 → 退回列表」的 watch**。issue 要求「若当前正打开该会话则退回列表」,而 store 不该依赖路由,所以导航放在 `ChatPage.vue`(用 `hadConversation` 区分「被跨端删除」与「深链进来列表还没拉到」)。
4. **`conversation_deleted` 只在软删成功(`ack ok=true`)时扇出**,避免对已不存在的会话做无意义的跨端移除。

**验证**:`scripts/verify.sh imserver` / `app` / `web` 全绿(输出贴在 PR 正文);契约自测做过 —— 把 fixture 里 `self_read` 的 `seq` 改成 `sequence`、`conversation_deleted` 的 `peer` 改成 `to`,三端同时红,还原后全绿。

**留给后续**:App 端「正打开的会话被跨端删除」时不会自动退出聊天页(Web 已做),需要 go_router 层配合,本单不动。

---

## 收尾记录(2026-11-09 归档)

**状态:四单全部合并进 `origin/master`,已于 2026-11-09 随 1.0.11 上线**(imserver 换镜像 +
`005_device_session.sql` 迁移 + 随下一版本发 App/Web);上线后生产即为 1.0.11 + `imserver:919a63a`。

| 单 | 栈 | PR | 合并 SHA | 结果 |
|---|---|---|---|---|
| K-1 | backend | #151 | `6aa772f` | 会话版本从 `User` 单列下沉为 `accounts.DeviceSession(user, client_type, version)`;JWT 与 IM token 都带 `ct`;判端只看**签发时**的 `X-Client` |
| K-2 | imserver | #150 | `f5802f2` | `SessionRegistry` 由 `uid → 单连接` 改为 `uid → {端 → 连接}`,按端注册与扇出;踢人按端(`kick_user(..., client_type=)`) |
| K-3 | imserver + App + Web | #155 | `37eaf56` | 下行 `self_read` / `conversation_deleted` 两帧,三端同 PR(契约联动);细节见上一节 |
| K-4 | App + Web | #154 | `fabf85a` | 统一上报端类型 `X-Client`,并复核 Web 多标签互顶 |

**与计划的偏差**:见上一节 K-3 的四条。另有一条**纪律性**的:后端与 imserver 各自维护一套端会话版本
(`accounts.DeviceSession` / `im_device_session`),所以回滚必须两端成对 —— 计划 Global Constraints 已写明,
执行时未破例,但这是本批最容易踩的一处。

**遗留(未闭环)**:
- App 端「正打开的会话被跨端删除」不自动退出聊天页(Web 已做),需 go_router 层配合。
- 生产已上线(`919a63a`,2026-11-09),实况见 `docs/ops/release.md` §6.6。
- 本文与 spec 引用的「第六轮功能开发拆批(K → L → M → N → O)」**从未写进 backlog**,M/N/O 至今未立项 ——
  2026-11-09 收尾时核实:`git log -S'第六轮' -- docs/backlog/` 无痕迹。
