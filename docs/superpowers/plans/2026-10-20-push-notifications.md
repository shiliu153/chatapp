# 推送:新的喜欢 / 配对成功 / 系统通知 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 让用户在 App 不在前台时也能收到「有人喜欢了你 / 配对成功 / 系统通知」,点击通知直达对应页面。

**Architecture:** Django 侧新增 `PushDevice` + `NotificationPreference` 两个模型与四个接口;业务事件统一经 `notifications/services.enqueue_push()` 在事务提交后入队 Celery 任务,任务按偏好与设备调用可插拔的推送客户端(极光 REST / 日志后端)。App 侧用 `jpush_flutter` 上报 registration_id、接收点击事件并按 `deeplink` 路由;Web 只做设置入口。

**Tech Stack:** Django 5.2 + DRF + Celery + Redis + requests;Flutter 3.47 + Riverpod + go_router + jpush_flutter 3.5.8;Vue 3 + Pinia + Vitest。

## Global Constraints

- 错误契约:失败一律 `{"code": <HTTP 状态码>, "message": "<中文>", "request_id": ...}`;业务码 = 前 3 位 HTTP + 2 位序号。
- 响应路径禁止任何第三方网络调用;跨系统副作用一律走 Celery,并挂在 `transaction.on_commit(fn, robust=True)` 上。
- 推送客户端对外**永不抛异常**(返回 `bool`),与 `im/client.py` 同约定;是否重试由任务层决定。
- 新增/修改 `/api/v1` 接口必须**同一次改动内**更新 `docs/api/`,否则 `ApiDocsCoverageTests` 红。
- 新增/修改任何 `.py` 文件必须补齐模块与函数/类 docstring,公开函数带参数要写 `Args:` 小节,否则 `CommentCoverageTests` 红。
- 单设备登录:同一账号只保留最新一台 `PushDevice`。
- App 端 UI 一律走「心跳」token(`AppColors` / `AppSpacing` / `AppText`),禁止裸 hex、裸字号、裸间距。
- 测试纪律:后端全量绿(前置 Redis)+ `flutter analyze` 零告警 + Web `vue-tsc` 零错误 / `eslint --max-warnings 0` 零告警。
- 没有极光 key 时后端必须走日志后端、App 必须跳过初始化且不报错。

---

## 文件结构

**后端(新增/修改)**

| 文件 | 职责 |
|---|---|
| `chatapp/notifications/models.py` | `PushDevice` / `PushPlatform` / `NotificationPreference`(含 `for_user` / `allows`) |
| `chatapp/notifications/migrations/0001_initial.py` | 建表迁移(由 `makemigrations` 生成) |
| `chatapp/notifications/serializers.py` | 设备上报与偏好读写序列化 |
| `chatapp/notifications/views.py` | 四个接口 |
| `chatapp/notifications/urls.py` | `push/` 子路由 |
| `chatapp/notifications/push.py` | `PushClient` / `LogPushClient` / `JPushClient` / `get_push_client` |
| `chatapp/notifications/services.py` | `enqueue_push()` 唯一入队入口 |
| `chatapp/notifications/tasks.py` | 追加 `send_push` 任务与 `like_cooldown_key` |
| `chatapp/notifications/tests.py` | 模型/接口/客户端/任务测试 |
| `chatapp/discovery/views.py` | swipe 新建 like 时入队 |
| `chatapp/discovery/services.py` | `notify_match(match, actor_id)` 追加配对推送 |
| `chatapp/moderation/services.py` | 举报处理、封禁/解封入队 |
| `chatapp/config/settings.py` | `PUSH_ENABLED` / `JPUSH_APP_KEY` / `JPUSH_MASTER_SECRET` / `PUSH_LIKE_COOLDOWN_SECONDS` |
| `chatapp/config/api_urls.py` | 挂 `push/` |
| `chatapp/.env.example` | 三个新键 |

**App(新增/修改)**

| 文件 | 职责 |
|---|---|
| `app/pubspec.yaml` | `jpush_flutter: ^3.5.8` |
| `app/android/app/build.gradle.kts` | JPush manifestPlaceholders |
| `app/android/app/src/main/AndroidManifest.xml` | 关闭 Flutter 深链 + 通知权限 |
| `app/lib/core/config.dart` | `jpushAppKey` 编译期常量 |
| `app/lib/core/push/push_service.dart` | 抽象接口 |
| `app/lib/core/push/jpush_push_service.dart` | 极光实现(唯一 import 插件的文件) |
| `app/lib/core/push/push_repository.dart` | 四个接口的 App 侧调用 + `PushPreferences` |
| `app/lib/core/push/push_controller.dart` | 生命周期 + 深链路由 + 三个 provider |
| `app/lib/app.dart` | 激活 `pushControllerProvider` |
| `app/lib/features/settings/notification_settings_page.dart` | 三项真开关 + 权限提示 |
| `app/test/support/fake_push_service.dart` | 测试替身 |
| `app/test/support/harness.dart` | 默认 override 推送服务 |
| `app/test/core/push/push_controller_test.dart` | 控制器测试 |
| `app/test/features/settings/notification_settings_page_test.dart` | 设置页测试(重写) |

**Web(新增/修改)**

| 文件 | 职责 |
|---|---|
| `web/src/api/push.ts` | 偏好读写 |
| `web/src/stores/push.ts` | 偏好状态与回滚 |
| `web/src/features/settings/NotificationSettingsPage.vue` | 三个可点开关 |
| `web/tests/component/notification-settings-page.spec.ts` | 页面测试(重写) |

**文档**

| 文件 | 职责 |
|---|---|
| `docs/api/push.md` | 4 个接口的对外文档 |
| `docs/api/README.md` | 目录与接口一览,总数 36 → 40 |

---

### Task 1: 推送模型与迁移

**Files:**
- Create: `chatapp/notifications/models.py`
- Create: `chatapp/notifications/migrations/0001_initial.py`(由命令生成)
- Test: `chatapp/notifications/tests.py`

**Interfaces:**
- Produces:
  - `PushPlatform`(`TextChoices`:`ANDROID="android"` / `IOS="ios"`)
  - `PushDevice(user, registration_id, platform, app_version, created_at, updated_at)`
  - `NotificationPreference(user, likes, matches, system, updated_at)`
  - `NotificationPreference.for_user(user) -> NotificationPreference`
  - `NotificationPreference.allows(kind: str) -> bool`(`like` / `match` / `system`)

- [x] **Step 1: 写失败测试**

在 `chatapp/notifications/tests.py` 顶部补 import,并在文件末尾追加:

```python
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from notifications.models import NotificationPreference, PushDevice, PushPlatform

User = get_user_model()


class PushDeviceModelTests(TestCase):
    """推送设备:registration_id 全局唯一,随用户删除级联清理。"""

    def setUp(self):
        self.a = User.objects.create_user(phone="13800138000")
        self.b = User.objects.create_user(phone="13900139000")

    def test_registration_id_is_globally_unique(self):
        PushDevice.objects.create(user=self.a, registration_id="rid-1",
                                  platform=PushPlatform.ANDROID)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PushDevice.objects.create(user=self.b, registration_id="rid-1",
                                          platform=PushPlatform.IOS)

    def test_devices_are_deleted_with_user(self):
        PushDevice.objects.create(user=self.a, registration_id="rid-1",
                                  platform=PushPlatform.ANDROID)
        self.a.delete()
        self.assertFalse(PushDevice.objects.exists())


class NotificationPreferenceModelTests(TestCase):
    """通知偏好:默认全开、只建一行、未知类型一律不发。"""

    def setUp(self):
        self.user = User.objects.create_user(phone="13800138000")

    def test_for_user_creates_defaults_once(self):
        pref = NotificationPreference.for_user(self.user)
        self.assertTrue(pref.likes)
        self.assertTrue(pref.matches)
        self.assertTrue(pref.system)

        again = NotificationPreference.for_user(self.user)
        self.assertEqual(again.pk, pref.pk)
        self.assertEqual(NotificationPreference.objects.count(), 1)

    def test_allows_known_and_unknown_kinds(self):
        pref = NotificationPreference.for_user(self.user)
        self.assertTrue(pref.allows("like"))
        self.assertTrue(pref.allows("match"))
        self.assertTrue(pref.allows("system"))
        self.assertFalse(pref.allows("message"))

    def test_preference_is_deleted_with_user(self):
        NotificationPreference.for_user(self.user)
        self.user.delete()
        self.assertFalse(NotificationPreference.objects.exists())
```

- [x] **Step 2: 跑测试确认失败**

```powershell
cd chatapp
$env:TEST_REDIS_PORT="16379"
python manage.py test notifications
```

预期:`ModuleNotFoundError: No module named 'notifications.models'`。

- [x] **Step 3: 写模型**

创建 `chatapp/notifications/models.py`:

```python
"""推送相关的持久化模型:设备与通知偏好。

设计要点:
    1. ``registration_id`` 全局唯一:同一台设备换账号登录时设备易主,
       旧账号自然失去这台设备(与单设备登录一致);
    2. 偏好是账号级、不预建:``NotificationPreference.for_user`` 读取时
       才落库,默认全开;注销随用户 CASCADE 删除。
"""

from django.conf import settings
from django.db import models


class PushPlatform(models.TextChoices):
    """推送设备平台。"""

    ANDROID = "android", "Android"
    IOS = "ios", "iOS"


class PushDevice(models.Model):
    """一台接收推送的设备(以极光 registration_id 标识)。"""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="push_devices")
    registration_id = models.CharField("极光 registration_id", max_length=128, unique=True)
    platform = models.CharField("平台", max_length=16, choices=PushPlatform.choices)
    app_version = models.CharField("App 版本", max_length=32, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        verbose_name = "推送设备"
        verbose_name_plural = "推送设备"

    def __str__(self):
        """后台与日志中的可读表示。

        Returns:
            ``用户 id:平台:registration_id``。
        """
        return f"{self.user_id}:{self.platform}:{self.registration_id}"


class NotificationPreference(models.Model):
    """账号级通知偏好;三类通知默认全开。"""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name="notification_preference")
    likes = models.BooleanField("新的喜欢", default=True)
    matches = models.BooleanField("配对成功", default=True)
    system = models.BooleanField("系统通知", default=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "通知偏好"
        verbose_name_plural = "通知偏好"

    @classmethod
    def for_user(cls, user):
        """取(必要时创建)用户的通知偏好。

        Args:
            user: 目标用户。

        Returns:
            该用户的 ``NotificationPreference`` 实例。
        """
        preference, _ = cls.objects.get_or_create(user=user)
        return preference

    def allows(self, kind: str) -> bool:
        """判断某一类通知是否开启。

        Args:
            kind: 通知类型,取值 ``like`` / ``match`` / ``system``。

        Returns:
            开启返回 ``True``;未知类型返回 ``False``(宁可不发)。
        """
        return {
            "like": self.likes,
            "match": self.matches,
            "system": self.system,
        }.get(kind, False)
```

- [x] **Step 4: 生成迁移并检查**

```powershell
cd chatapp
python manage.py makemigrations notifications
```

预期:生成 `0001_initial.py`,包含 `PushDevice` 与 `NotificationPreference` 两张表。打开确认没有意外改动其他 app。

- [x] **Step 5: 跑测试确认通过**

```powershell
cd chatapp
$env:TEST_REDIS_PORT="16379"
python manage.py test notifications
```

预期:全部通过(含原有短信测试)。

- [x] **Step 6: 提交**

```powershell
git add chatapp/notifications/models.py chatapp/notifications/migrations chatapp/notifications/tests.py
git commit -m "feat(push): PushDevice + NotificationPreference 模型与迁移"
```

---

### Task 2: 设备接口(POST / DELETE)

**Files:**
- Create: `chatapp/notifications/serializers.py`
- Create: `chatapp/notifications/views.py`
- Create: `chatapp/notifications/urls.py`
- Modify: `chatapp/config/api_urls.py`
- Test: `chatapp/notifications/tests.py`

**Interfaces:**
- Consumes: Task 1 的 `PushDevice` / `PushPlatform`
- Produces:
  - `POST /api/v1/push/devices` → `200 {"registration_id": str, "platform": str}`
  - `DELETE /api/v1/push/devices/{registration_id}` → `204`

- [x] **Step 1: 写失败测试**

在 `chatapp/notifications/tests.py` 追加(顶部补 `from rest_framework.test import APITestCase` 与 `from rest_framework_simplejwt.tokens import RefreshToken`):

```python
class PushDeviceApiTests(APITestCase):
    """设备上报:幂等、单设备、换账号易主、解绑幂等。"""

    def setUp(self):
        self.me = User.objects.create_user(phone="13800138000")
        self.other = User.objects.create_user(phone="13900139000")
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.me).access_token}")

    def _register(self, rid="rid-1", platform="android", version="1.0.0"):
        """上报一台设备。

        Args:
            rid: registration_id。
            platform: 平台。
            version: App 版本。

        Returns:
            DRF 响应对象。
        """
        return self.client.post("/api/v1/push/devices", {
            "registration_id": rid, "platform": platform, "app_version": version,
        }, format="json")

    def test_register_creates_device(self):
        resp = self._register()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data, {"registration_id": "rid-1", "platform": "android"})
        device = PushDevice.objects.get(registration_id="rid-1")
        self.assertEqual(device.user_id, self.me.id)
        self.assertEqual(device.app_version, "1.0.0")

    def test_register_is_idempotent(self):
        self._register()
        self._register()
        self.assertEqual(PushDevice.objects.count(), 1)

    def test_register_keeps_only_latest_device(self):
        self._register("rid-1")
        self._register("rid-2")
        self.assertEqual(
            list(PushDevice.objects.filter(user=self.me).values_list("registration_id", flat=True)),
            ["rid-2"],
        )

    def test_register_takes_over_device_from_previous_account(self):
        PushDevice.objects.create(user=self.other, registration_id="rid-1",
                                  platform=PushPlatform.ANDROID)
        resp = self._register("rid-1")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(PushDevice.objects.get(registration_id="rid-1").user_id, self.me.id)
        self.assertFalse(PushDevice.objects.filter(user=self.other).exists())

    def test_invalid_platform_rejected(self):
        resp = self._register(platform="windows")
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(PushDevice.objects.exists())

    def test_unregister_is_idempotent(self):
        self._register()
        first = self.client.delete("/api/v1/push/devices/rid-1")
        second = self.client.delete("/api/v1/push/devices/rid-1")
        self.assertEqual(first.status_code, 204)
        self.assertEqual(second.status_code, 204)
        self.assertFalse(PushDevice.objects.exists())

    def test_cannot_unregister_other_users_device(self):
        PushDevice.objects.create(user=self.other, registration_id="rid-9",
                                  platform=PushPlatform.ANDROID)
        resp = self.client.delete("/api/v1/push/devices/rid-9")
        self.assertEqual(resp.status_code, 204)
        self.assertTrue(PushDevice.objects.filter(registration_id="rid-9").exists())

    def test_requires_auth(self):
        self.client.credentials()
        self.assertEqual(self._register().status_code, 401)
```

- [x] **Step 2: 跑测试确认失败**

```powershell
cd chatapp
$env:TEST_REDIS_PORT="16379"
python manage.py test notifications.tests.PushDeviceApiTests
```

预期:全部 404(路由不存在)。

- [x] **Step 3: 写序列化、视图与路由**

创建 `chatapp/notifications/serializers.py`:

```python
"""推送接口的序列化:设备上报与通知偏好。

设计要点:
    设备用普通 ``Serializer`` 而不是 ``ModelSerializer``:接口只接收三个字段,
    用户与时间戳都由服务端决定,不给客户端越权空间。
"""

from rest_framework import serializers

from .models import NotificationPreference, PushPlatform


class DeviceSerializer(serializers.Serializer):
    """设备上报的入参。"""

    registration_id = serializers.CharField(max_length=128)
    platform = serializers.ChoiceField(choices=PushPlatform.choices)
    app_version = serializers.CharField(max_length=32, required=False, allow_blank=True,
                                        default="")


class PreferenceSerializer(serializers.ModelSerializer):
    """通知偏好的读写形状(三个布尔字段)。"""

    class Meta:
        model = NotificationPreference
        fields = ["likes", "matches", "system"]
```

创建 `chatapp/notifications/views.py`:

```python
"""推送设备与通知偏好接口。

设计要点:
    1. 上报设备即「单设备」:同一账号只保留最新一台,旧设备记录直接删除;
    2. 解绑只删自己的设备,且不区分「不存在」与「不是你的」—— 一律 204,
       避免泄漏他人设备是否存在;
    3. 偏好读取时按需创建,默认全开。
"""

from django.db import transaction
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import NotificationPreference, PushDevice
from .serializers import DeviceSerializer, PreferenceSerializer


@api_view(["POST"])
def register_device(request):
    """上报推送设备(POST /api/v1/push/devices)。

    幂等:同一 registration_id 重复上报只更新归属与版本;同账号的其他设备被删除。

    Args:
        request: DRF 请求对象,body 需带 ``registration_id`` 与 ``platform``。

    Returns:
        ``{"registration_id": str, "platform": str}``。
    """
    serializer = DeviceSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    me = request.user
    with transaction.atomic():
        PushDevice.objects.update_or_create(
            registration_id=data["registration_id"],
            defaults={
                "user": me,
                "platform": data["platform"],
                "app_version": data.get("app_version", ""),
            },
        )
        PushDevice.objects.filter(user=me).exclude(
            registration_id=data["registration_id"]).delete()
    return Response({"registration_id": data["registration_id"],
                     "platform": data["platform"]})


@api_view(["DELETE"])
def unregister_device(request, registration_id):
    """解绑推送设备(DELETE /api/v1/push/devices/{registration_id})。

    幂等:设备不存在、或属于别人,一律 204(不泄漏他人设备信息)。

    Args:
        request: DRF 请求对象。
        registration_id: 极光 registration_id。

    Returns:
        204 空响应。
    """
    PushDevice.objects.filter(user=request.user, registration_id=registration_id).delete()
    return Response(status=204)


@api_view(["GET", "PATCH"])
def preferences(request):
    """读取或修改通知偏好(GET/PATCH /api/v1/push/preferences)。

    PATCH 为局部更新:只改传入的字段,未传的保持不变。

    Args:
        request: DRF 请求对象;PATCH 时 body 可带 ``likes`` / ``matches`` / ``system``。

    Returns:
        ``{"likes": bool, "matches": bool, "system": bool}``。
    """
    preference = NotificationPreference.for_user(request.user)
    if request.method == "PATCH":
        serializer = PreferenceSerializer(preference, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
    return Response(PreferenceSerializer(preference).data)
```

创建 `chatapp/notifications/urls.py`:

```python
"""``/api/v1/push`` 的子路由。"""

from django.urls import path

from . import views

urlpatterns = [
    path("devices", views.register_device),
    path("devices/<str:registration_id>", views.unregister_device),
    path("preferences", views.preferences),
]
```

修改 `chatapp/config/api_urls.py`,在 `path("", include("feedback.urls")),` 之后加:

```python
    path("push/", include("notifications.urls")),
```

- [x] **Step 4: 跑测试确认通过**

```powershell
cd chatapp
$env:TEST_REDIS_PORT="16379"
python manage.py test notifications.tests.PushDeviceApiTests
```

预期:全部通过。

- [x] **Step 5: 提交**

```powershell
git add chatapp/notifications/serializers.py chatapp/notifications/views.py chatapp/notifications/urls.py chatapp/config/api_urls.py chatapp/notifications/tests.py
git commit -m "feat(push): 设备上报与解绑接口"
```

---

### Task 3: 偏好接口(GET / PATCH)

**Files:**
- Modify: `chatapp/notifications/tests.py`(追加测试;视图已在 Task 2 写好)
- Test: `chatapp/notifications/tests.py`

**Interfaces:**
- Consumes: Task 1 的 `NotificationPreference.for_user`、Task 2 的 `preferences` 视图
- Produces: `GET/PATCH /api/v1/push/preferences`

- [x] **Step 1: 写失败测试**

```python
class PushPreferenceApiTests(APITestCase):
    """通知偏好:默认全开、局部更新、非法值 400。"""

    def setUp(self):
        self.me = User.objects.create_user(phone="13800138000")
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.me).access_token}")

    def test_get_returns_defaults(self):
        resp = self.client.get("/api/v1/push/preferences")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data, {"likes": True, "matches": True, "system": True})

    def test_patch_updates_only_given_field(self):
        resp = self.client.patch("/api/v1/push/preferences", {"likes": False}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data, {"likes": False, "matches": True, "system": True})
        self.assertFalse(NotificationPreference.for_user(self.me).likes)

    def test_patch_rejects_non_boolean(self):
        resp = self.client.patch("/api/v1/push/preferences", {"likes": "maybe"}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(NotificationPreference.for_user(self.me).likes)

    def test_requires_auth(self):
        self.client.credentials()
        self.assertEqual(self.client.get("/api/v1/push/preferences").status_code, 401)
```

- [x] **Step 2: 跑测试确认失败**

```powershell
cd chatapp
$env:TEST_REDIS_PORT="16379"
python manage.py test notifications.tests.PushPreferenceApiTests
```

预期:如果 Task 2 的视图已经写好,这一组会**直接通过**;若未通过,按报错修 `preferences` 视图。保留测试即可。

- [x] **Step 3: 跑测试确认通过**

```powershell
cd chatapp
$env:TEST_REDIS_PORT="16379"
python manage.py test notifications.tests.PushPreferenceApiTests
```

预期:全部通过。

- [x] **Step 4: 提交**

```powershell
git add chatapp/notifications/tests.py
git commit -m "test(push): 通知偏好接口测试"
```

---

### Task 4: 推送客户端、任务与冷却

**Files:**
- Create: `chatapp/notifications/push.py`
- Create: `chatapp/notifications/services.py`
- Modify: `chatapp/notifications/tasks.py`
- Modify: `chatapp/config/settings.py`
- Modify: `chatapp/.env.example`
- Test: `chatapp/notifications/tests.py`

**Interfaces:**
- Consumes: Task 1 的模型
- Produces:
  - `get_push_client() -> PushClient`
  - `enqueue_push(user_id: int, kind: str, *, title: str, alert: str, extras: dict) -> None`
  - `send_push` Celery 任务(`.delay(user_id, kind, title, alert, extras)`)
  - `like_cooldown_key(user_id: int) -> str`

- [x] **Step 1: 写失败测试**

在 `chatapp/notifications/tests.py` 追加(顶部补 `from unittest.mock import patch`、`from django.test import SimpleTestCase, override_settings`、`import requests`):

```python
class PushClientTests(SimpleTestCase):
    """推送客户端:日志后端不触网;极光载荷正确;网络错误不抛。"""

    def test_log_client_returns_true_and_logs(self):
        with self.assertLogs("notifications", level="INFO") as captured:
            ok = LogPushClient().send(["rid-1"], title="t", alert="a", extras={})
        self.assertTrue(ok)
        self.assertIn("推送-日志", captured.output[0])

    @override_settings(PUSH_ENABLED=True, JPUSH_APP_KEY="k", JPUSH_MASTER_SECRET="s")
    def test_enabled_with_keys_returns_jpush_client(self):
        self.assertIsInstance(get_push_client(), JPushClient)

    @override_settings(PUSH_ENABLED=False)
    def test_disabled_returns_log_client(self):
        self.assertIsInstance(get_push_client(), LogPushClient)

    @patch("notifications.push.requests.post")
    def test_jpush_client_posts_expected_payload(self, post):
        post.return_value.status_code = 200
        client = JPushClient("key", "secret")
        ok = client.send(["rid-1"], title="有人喜欢了你", alert="去看看是谁",
                         extras={"deeplink": "/likes"})
        self.assertTrue(ok)
        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://api.jpush.cn/v3/push")
        self.assertEqual(kwargs["json"]["audience"]["registration_id"], ["rid-1"])
        self.assertEqual(kwargs["json"]["notification"]["android"]["extras"]["deeplink"], "/likes")
        self.assertTrue(kwargs["headers"]["Authorization"].startswith("Basic "))

    @patch("notifications.push.requests.post",
           side_effect=requests.RequestException("boom"))
    def test_jpush_client_swallows_network_error(self, _post):
        self.assertFalse(JPushClient("key", "secret").send(
            ["rid-1"], title="t", alert="a", extras={}))

    @patch("notifications.push.requests.post")
    def test_jpush_client_reports_non_2xx(self, post):
        post.return_value.status_code = 401
        post.return_value.text = "unauthorized"
        self.assertFalse(JPushClient("key", "secret").send(
            ["rid-1"], title="t", alert="a", extras={}))


class SendPushTaskTests(TestCase):
    """推送任务:偏好、设备、冷却、失败重试的边界。"""

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(phone="13800138000")
        PushDevice.objects.create(user=self.user, registration_id="rid-1",
                                  platform=PushPlatform.ANDROID)

    def test_skips_when_preference_disabled(self):
        NotificationPreference.objects.create(user=self.user, likes=False)
        with patch("notifications.tasks.get_push_client") as factory:
            send_push.run(self.user.id, "like", "t", "a", {})
        factory.assert_not_called()

    def test_skips_without_devices(self):
        PushDevice.objects.all().delete()
        with patch("notifications.tasks.get_push_client") as factory:
            send_push.run(self.user.id, "match", "t", "a", {})
        factory.assert_not_called()

    def test_skips_unknown_user(self):
        with patch("notifications.tasks.get_push_client") as factory:
            send_push.run(999999, "match", "t", "a", {})
        factory.assert_not_called()

    def test_sends_to_all_devices(self):
        PushDevice.objects.create(user=self.user, registration_id="rid-2",
                                  platform=PushPlatform.IOS)
        with patch("notifications.tasks.get_push_client") as factory:
            send_push.run(self.user.id, "match", "配对成功", "你们互相喜欢了", {"deeplink": "/chat/2"})
        client = factory.return_value
        client.send.assert_called_once()
        ids = client.send.call_args.args[0]
        self.assertEqual(set(ids), {"rid-1", "rid-2"})

    def test_like_cooldown_blocks_second_send(self):
        with patch("notifications.tasks.get_push_client") as factory:
            send_push.run(self.user.id, "like", "t", "a", {})
            send_push.run(self.user.id, "like", "t", "a", {})
        self.assertEqual(factory.return_value.send.call_count, 1)

    def test_failed_send_releases_cooldown_and_raises(self):
        with patch("notifications.tasks.get_push_client") as factory:
            factory.return_value.send.return_value = False
            with self.assertRaises(RuntimeError):
                send_push.run(self.user.id, "like", "t", "a", {})
        self.assertIsNone(cache.get(like_cooldown_key(self.user.id)))
```

顶部 import 增加:

```python
from django.core.cache import cache
from django.test import SimpleTestCase, override_settings
import requests

from notifications.push import JPushClient, LogPushClient, get_push_client
from notifications.tasks import like_cooldown_key, send_push
```

- [x] **Step 2: 跑测试确认失败**

```powershell
cd chatapp
$env:TEST_REDIS_PORT="16379"
python manage.py test notifications.tests.PushClientTests notifications.tests.SendPushTaskTests
```

预期:`ModuleNotFoundError: No module named 'notifications.push'`。

- [x] **Step 3: 写配置**

在 `chatapp/config/settings.py` 的「腾讯云 IM REST」段之后插入:

```python
# --- 推送(极光 JPush;没有 key 时自动落到日志后端,本地/CI 不会误发) ---
PUSH_ENABLED = os.getenv("PUSH_ENABLED", "0") == "1"
JPUSH_APP_KEY = os.getenv("JPUSH_APP_KEY", "")
JPUSH_MASTER_SECRET = os.getenv("JPUSH_MASTER_SECRET", "")
PUSH_LIKE_COOLDOWN_SECONDS = int(os.getenv("PUSH_LIKE_COOLDOWN_SECONDS", "1800"))
```

在 `chatapp/.env.example` 末尾追加:

```dotenv
# 推送(极光 JPush);PUSH_ENABLED=1 且 key 齐全才真的发推送,否则只打日志
PUSH_ENABLED=0
JPUSH_APP_KEY=
JPUSH_MASTER_SECRET=
# 同一接收者「新的喜欢」推送的最小间隔(秒)
# PUSH_LIKE_COOLDOWN_SECONDS=1800
```

- [x] **Step 4: 写推送客户端**

创建 `chatapp/notifications/push.py`:

```python
"""推送通道:极光 REST API 与开发期日志后端。

设计要点:
    1. 业务侧只认 ``get_push_client().send(...)``,换通道不动业务代码;
    2. ``send`` 对外永不抛异常(返回 False 由任务层决定重试),与 ``im/client.py`` 同约定;
    3. 没有配置 key 时自动落到日志后端,本地与 CI 不会误发真推送。
"""

import base64
import logging
from typing import Protocol

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

JPUSH_ENDPOINT = "https://api.jpush.cn/v3/push"
REQUEST_TIMEOUT_SECONDS = 5


class PushClient(Protocol):
    """推送通道接口。"""

    def send(self, registration_ids: list[str], *, title: str, alert: str,
             extras: dict) -> bool:
        """向一组设备发送一条通知。

        Args:
            registration_ids: 极光 registration_id 列表。
            title: 通知标题。
            alert: 通知正文。
            extras: 附加数据;``deeplink`` 用于客户端点击跳转。

        Returns:
            发送成功返回 ``True``;失败返回 ``False``,不抛异常。
        """
        ...


class LogPushClient:
    """开发 / 测试后端:只打日志,永不触网。"""

    def send(self, registration_ids: list[str], *, title: str, alert: str,
             extras: dict) -> bool:
        """把推送内容写进日志。

        Args:
            registration_ids: 设备列表(只记录数量)。
            title: 通知标题。
            alert: 通知正文。
            extras: 附加数据。

        Returns:
            恒为 ``True``。
        """
        logger.info("[推送-日志] devices=%s title=%s alert=%s extras=%s",
                    len(registration_ids), title, alert, extras)
        return True


class JPushClient:
    """极光 REST API v3 客户端(按 registration_id 投递)。"""

    def __init__(self, app_key: str, master_secret: str):
        """保存 Basic 认证串。

        Args:
            app_key: 极光应用的 AppKey。
            master_secret: 极光应用的 MasterSecret。
        """
        token = base64.b64encode(f"{app_key}:{master_secret}".encode()).decode()
        self._authorization = f"Basic {token}"

    def _payload(self, registration_ids: list[str], title: str, alert: str,
                 extras: dict) -> dict:
        """拼极光 v3 推送载荷。

        Args:
            registration_ids: 目标设备列表。
            title: 通知标题。
            alert: 通知正文。
            extras: 附加数据。

        Returns:
            可直接作为 JSON body 的字典。
        """
        return {
            "platform": "all",
            "audience": {"registration_id": registration_ids},
            "notification": {
                "android": {"title": title, "alert": alert, "extras": extras},
                "ios": {"title": title, "alert": alert, "sound": "default",
                        "badge": "+1", "extras": extras},
            },
            "options": {"apns_production": False, "time_to_live": 86400},
        }

    def send(self, registration_ids: list[str], *, title: str, alert: str,
             extras: dict) -> bool:
        """调用极光推送接口。

        Args:
            registration_ids: 目标设备列表;为空视为成功(无事可做)。
            title: 通知标题。
            alert: 通知正文。
            extras: 附加数据。

        Returns:
            2xx 返回 ``True``;网络错误或非 2xx 返回 ``False``。
        """
        if not registration_ids:
            return True
        try:
            response = requests.post(
                JPUSH_ENDPOINT,
                json=self._payload(registration_ids, title, alert, extras),
                headers={"Authorization": self._authorization},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException:
            logger.exception("极光推送请求失败")
            return False
        if response.status_code // 100 != 2:
            logger.warning("极光推送失败 status=%s body=%s",
                           response.status_code, response.text[:500])
            return False
        return True


def get_push_client() -> PushClient:
    """按配置返回推送客户端。

    Returns:
        配置齐全且开启时返回 ``JPushClient``,否则返回 ``LogPushClient``。
    """
    if settings.PUSH_ENABLED and settings.JPUSH_APP_KEY and settings.JPUSH_MASTER_SECRET:
        return JPushClient(settings.JPUSH_APP_KEY, settings.JPUSH_MASTER_SECRET)
    return LogPushClient()
```

- [x] **Step 5: 写入队服务与任务**

创建 `chatapp/notifications/services.py`:

```python
"""推送的业务入口:把「发一条推送」收敛成一个函数。

设计要点:
    所有业务事件都调 ``enqueue_push``,由它统一 ``on_commit`` 入队;
    业务代码不需要知道 Celery、偏好与设备的存在。
"""

from django.db import transaction

from .tasks import send_push


def enqueue_push(user_id: int, kind: str, *, title: str, alert: str, extras: dict) -> None:
    """事务提交后入队一条推送。

    Args:
        user_id: 接收者账号 id。
        kind: 通知类型,``like`` / ``match`` / ``system``。
        title: 通知标题。
        alert: 通知正文。
        extras: 附加数据;``deeplink`` 是点击后要打开的 App 路径。
    """
    transaction.on_commit(
        lambda: send_push.delay(user_id, kind, title, alert, extras), robust=True)
```

在 `chatapp/notifications/tasks.py` 追加(顶部补 import):

```python
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache

from .models import NotificationPreference, PushDevice
from .push import get_push_client


def like_cooldown_key(user_id: int) -> str:
    """「新的喜欢」推送的冷却键。

    Args:
        user_id: 接收者账号 id。

    Returns:
        Redis 缓存键。
    """
    return f"push:like:{user_id}"


@shared_task(autoretry_for=(Exception,), retry_backoff=True, retry_jitter=True, max_retries=3)
def send_push(user_id: int, kind: str, title: str, alert: str, extras: dict) -> None:
    """按偏好与设备发送一条推送;任一步不满足都静默返回。

    Args:
        user_id: 接收者账号 id。
        kind: 通知类型,``like`` / ``match`` / ``system``。
        title: 通知标题。
        alert: 通知正文。
        extras: 附加数据(含 ``deeplink``)。

    Raises:
        RuntimeError: 推送通道返回失败,触发 Celery 重试。
    """
    user = get_user_model().objects.filter(id=user_id).first()
    if user is None:
        return
    if not NotificationPreference.for_user(user).allows(kind):
        return
    registration_ids = list(
        PushDevice.objects.filter(user=user).values_list("registration_id", flat=True))
    if not registration_ids:
        return

    cooldown_key = None
    if kind == "like":
        cooldown_key = like_cooldown_key(user_id)
        if not cache.add(cooldown_key, 1, settings.PUSH_LIKE_COOLDOWN_SECONDS):
            return
    try:
        ok = get_push_client().send(registration_ids, title=title, alert=alert, extras=extras)
    except Exception:
        if cooldown_key:
            cache.delete(cooldown_key)
        raise
    if not ok:
        if cooldown_key:
            cache.delete(cooldown_key)
        raise RuntimeError("推送发送失败")
```

> `tasks.py` 现有的 `send_sms_code` 与 import 保持不动,新 import 放在文件顶部。

- [x] **Step 6: 跑测试确认通过**

```powershell
cd chatapp
$env:TEST_REDIS_PORT="16379"
python manage.py test notifications
```

预期:全部通过。

- [x] **Step 7: 提交**

```powershell
git add chatapp/notifications/push.py chatapp/notifications/services.py chatapp/notifications/tasks.py chatapp/config/settings.py chatapp/.env.example chatapp/notifications/tests.py
git commit -m "feat(push): 极光/日志推送客户端 + 入队服务 + 发送任务(含喜欢冷却)"
```

---

### Task 5: 业务触发点(喜欢 / 配对 / 举报 / 封禁)

**Files:**
- Modify: `chatapp/discovery/views.py`
- Modify: `chatapp/discovery/services.py`
- Modify: `chatapp/moderation/services.py`
- Test: `chatapp/discovery/tests.py`
- Test: `chatapp/moderation/tests.py`

**Interfaces:**
- Consumes: Task 4 的 `enqueue_push(user_id, kind, *, title, alert, extras)`
- Produces:
  - `notify_match(match, actor_id=None)`(签名扩展,旧调用保持可用)
  - swipe 新建 like 时入队 `kind="like"`
  - 举报处理 / 封禁 / 解封入队 `kind="system"`

- [x] **Step 1: 写失败测试**

在 `chatapp/discovery/tests.py` 追加:

```python
class SwipePushTests(APITestCase):
    """滑卡推送:新建 like 才推、幂等重放不推、配对只推先喜欢的一方。"""

    def setUp(self):
        self.a = User.objects.create_user(phone="13800138000")
        self.b = User.objects.create_user(phone="13900139000")
        for user in (self.a, self.b):
            Profile.objects.create(user=user, nickname=f"用户{user.id}", gender="male",
                                   birthday=date(1995, 1, 1), city="上海", bio="hi",
                                   status=ProfileStatus.COMPLETE)
            Photo.objects.create(user=user, file="a.jpg", status=PhotoStatus.APPROVED)
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.a).access_token}")

    def _like(self, user):
        """以当前登录身份喜欢某人。

        Args:
            user: 目标用户。

        Returns:
            DRF 响应对象。
        """
        return self.client.post("/api/v1/discovery/swipe",
                                {"target_user_id": user.id, "action": "like"}, format="json")

    def test_new_like_enqueues_push_to_target(self):
        with patch("notifications.services.send_push.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                resp = self._like(self.b)
        self.assertEqual(resp.status_code, 200)
        delay.assert_called_once()
        args = delay.call_args.args
        self.assertEqual(args[0], self.b.id)
        self.assertEqual(args[1], "like")
        self.assertEqual(args[4]["deeplink"], "/likes")

    def test_repeated_swipe_does_not_push_again(self):
        self._like(self.b)
        with patch("notifications.services.send_push.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                self._like(self.b)
        delay.assert_not_called()

    def test_mutual_like_pushes_match_to_first_liker_only(self):
        with patch("notifications.services.send_push.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                self._like(self.b)          # A → B:一条 like 推送给 B
                self.client.credentials(
                    HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.b).access_token}")
                self._like(self.a)          # B → A:配对成功,推给先喜欢的 A
        self.assertEqual(delay.call_count, 2)
        first, second = delay.call_args_list
        self.assertEqual((first.args[0], first.args[1]), (self.b.id, "like"))
        self.assertEqual((second.args[0], second.args[1]), (self.a.id, "match"))
        self.assertEqual(second.args[4]["deeplink"], f"/chat/{self.b.id}")
```

在 `chatapp/moderation/tests.py` 追加(先看该文件已有 import,补 `from unittest.mock import patch` 与 `from notifications.services import enqueue_push` 所在模块):

```python
class ModerationPushTests(TestCase):
    """举报处理与封禁:各自入队一条 system 推送。"""

    def setUp(self):
        self.user = User.objects.create_user(phone="13800138000")
        self.reporter = User.objects.create_user(phone="13900139000")

    def test_report_handled_enqueues_system_push(self):
        report = Report.objects.create(reporter=self.reporter, target=self.user,
                                       reason="骚扰", status="handled")
        with patch("notifications.services.send_push.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                notify_report_handled(report)
        delay.assert_called_once()
        args = delay.call_args.args
        self.assertEqual((args[0], args[1]), (self.reporter.id, "system"))
        self.assertEqual(args[4]["deeplink"], "/chat/system_notice")

    def test_ban_enqueues_system_push(self):
        with patch("notifications.services.send_push.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                log_ban_change(self.user, ProfileStatus.COMPLETE, ProfileStatus.BANNED_HEAVY,
                               "违规", operator=None)
        delay.assert_called_once()
        args = delay.call_args.args
        self.assertEqual((args[0], args[1]), (self.user.id, "system"))
        self.assertEqual(args[4]["deeplink"], "/chat/system_notice")
```

> 若 `moderation/tests.py` 里 `Report` 的必填字段不同,以该文件现有构造方式为准(照抄同文件里创建 Report 的代码);`log_ban_change` 与 `notify_report_handled` 的 import 也从该文件现有 import 补齐。

- [x] **Step 2: 跑测试确认失败**

```powershell
cd chatapp
$env:TEST_REDIS_PORT="16379"
python manage.py test discovery.tests.SwipePushTests moderation.tests.ModerationPushTests
```

预期:断言失败(`delay` 未被调用)。

- [x] **Step 3: 接入触发点**

`chatapp/discovery/views.py`:

1. 顶部 import 增加:

```python
from notifications.services import enqueue_push
```

2. `swipe` 在 `return Response({"matched": matched})` 之前插入:

```python
    if created and swipe_obj.action == SwipeAction.LIKE and not matched:
        enqueue_push(
            target.id, "like",
            title="有人喜欢了你", alert="去看看是谁",
            extras={"deeplink": "/likes", "type": "like"},
        )
```

3. 互喜分支的 `notify_match(match)` 改为 `notify_match(match, actor_id=me.id)`。

`chatapp/discovery/services.py`:

1. 顶部 import 增加:

```python
from notifications.services import enqueue_push
```

2. `notify_match` 改为:

```python
def notify_match(match, actor_id=None):
    """配对成功后给双方发 IM 灰条,并给「先喜欢的一方」发推送。

    on_commit:配对真正落库后才入队;robust=True:broker 抖动不影响配对结果。

    Args:
        match: 刚创建的配对记录,双方 id 从它上面取。
        actor_id: 本次触发配对的用户 id(正在滑卡的人);``None`` 表示不推配对通知。
    """
    a_id, b_id = match.user_a_id, match.user_b_id
    transaction.on_commit(lambda: im_tasks.send_match_notice.delay(a_id, b_id), robust=True)
    if actor_id is None:
        return
    receiver_id = b_id if actor_id == a_id else a_id
    other = match.user_b if receiver_id == a_id else match.user_a
    nickname = getattr(getattr(other, "profile", None), "nickname", "") or "对方"
    enqueue_push(
        receiver_id, "match",
        title="配对成功", alert=f"你和{nickname}互相喜欢,快去打招呼吧",
        extras={"deeplink": f"/chat/{actor_id}", "type": "match"},
    )
```

`chatapp/moderation/services.py`:

1. 顶部 import 增加:

```python
from notifications.services import enqueue_push
```

2. `log_ban_change` 三个分支各追加一行:

```python
    if new_status == ProfileStatus.BANNED_LIGHT:
        _write_log(user, BanAction.BAN_LIGHT, reason, operator)
        _enqueue(im_tasks.ban_notice, user.id, "light", reason or "")
        enqueue_push(user.id, "system", title="账号受限",
                     alert=f"你的账号已被限制:{reason}" if reason else "你的账号已被限制,暂时无法滑卡",
                     extras={"deeplink": "/chat/system_notice", "type": "system"})
    elif new_status == ProfileStatus.BANNED_HEAVY:
        _write_log(user, BanAction.BAN_HEAVY, reason, operator)
        _enqueue(im_tasks.ban_notice, user.id, "heavy", reason or "")
        enqueue_push(user.id, "system", title="账号受限",
                     alert=f"你的账号已被限制:{reason}" if reason else "你的账号已被限制,暂时无法使用",
                     extras={"deeplink": "/chat/system_notice", "type": "system"})
    elif old_status in Profile.BANNED_STATUSES:
        _write_log(user, BanAction.UNBAN, reason, operator)
        _enqueue(im_tasks.banned_lifted, user.id)
        enqueue_push(user.id, "system", title="限制已解除",
                     alert="你的账号限制已解除",
                     extras={"deeplink": "/chat/system_notice", "type": "system"})
```

3. `notify_report_handled` 末尾追加:

```python
    enqueue_push(report.reporter_id, "system",
                 title="举报已处理", alert="你提交的举报已处理完成",
                 extras={"deeplink": "/chat/system_notice", "type": "system"})
```

- [x] **Step 4: 跑测试确认通过**

```powershell
cd chatapp
$env:TEST_REDIS_PORT="16379"
python manage.py test discovery.tests.SwipePushTests moderation.tests.ModerationPushTests
```

预期:全部通过。

- [x] **Step 5: 跑受影响 app 的全量测试**

```powershell
cd chatapp
$env:TEST_REDIS_PORT="16379"
python manage.py test discovery moderation notifications
```

预期:全绿(原有测试不能因 `notify_match` 签名变化而红)。

- [x] **Step 6: 提交**

```powershell
git add chatapp/discovery/views.py chatapp/discovery/services.py chatapp/moderation/services.py chatapp/discovery/tests.py chatapp/moderation/tests.py
git commit -m "feat(push): 喜欢/配对/举报/封禁四类事件接入推送"
```

---

### Task 6: 接口文档与门禁

**Files:**
- Create: `docs/api/push.md`
- Modify: `docs/api/README.md`
- Test: `chatapp/config/tests.py`(既有门禁,无需改)

**Interfaces:**
- Consumes: Task 2/3 的四个接口
- Produces: `ApiDocsCoverageTests` 绿

- [x] **Step 1: 先跑门禁确认会红**

```powershell
cd chatapp
$env:TEST_REDIS_PORT="16379"
python manage.py test config.tests.ApiDocsCoverageTests
```

预期:失败,提示 4 个接口未写文档。

- [x] **Step 2: 启动后端,抓真实响应**

```powershell
cd chatapp
python manage.py migrate
python manage.py runserver 8000
```

另开一个终端,用测试账号(验证码固定 `123456`)依次调用,把响应原样记下来:

```powershell
$body = '{"phone":"13800000001"}'
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/auth/sms/send -ContentType application/json -Body $body
$verify = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/auth/sms/verify -ContentType application/json -Body '{"phone":"13800000001","code":"123456"}'
$headers = @{ Authorization = "Bearer $($verify.access)" }
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/push/devices -Headers $headers -ContentType application/json -Body '{"registration_id":"190e35f7e0a7c3b2d1","platform":"android","app_version":"1.0.0"}'
Invoke-RestMethod -Method Get -Uri http://127.0.0.1:8000/api/v1/push/preferences -Headers $headers
Invoke-RestMethod -Method Patch -Uri http://127.0.0.1:8000/api/v1/push/preferences -Headers $headers -ContentType application/json -Body '{"likes":false}'
Invoke-RestMethod -Method Delete -Uri http://127.0.0.1:8000/api/v1/push/devices/190e35f7e0a7c3b2d1 -Headers $headers
```

预期:`POST` 返回 `registration_id` + `platform`;`GET` 三个 `true`;`PATCH` 后 `likes=false`;`DELETE` 204 无 body。

- [x] **Step 3: 写 `docs/api/push.md`**

按 `docs/api/README.md` 的 7 元素模板写四个小节(编号 `1.1`–`1.4`),内容:

- 分册标题 `# 推送(API Reference)` + 一句话说明;
- `### 1.1 上报推送设备`
  - 信息行:`> `POST` `/api/v1/push/devices` · 需要鉴权 · 无额外限流`
  - 描述:幂等 upsert;同一账号只保留最新一台设备(与单设备登录一致);`registration_id` 全局唯一,同一台设备换账号登录会易主;
  - 请求参数表:`registration_id`(必填,string,≤128)、`platform`(必填,string,`android`/`ios`)、`app_version`(可选,string,≤32);
  - 响应参数表:`registration_id`(string)、`platform`(string);
  - 请求示例(curl)+ 成功响应示例(用 Step 2 抓到的真实值)+ 失败示例(`platform` 非法,400);
  - 错误码表:`400` 参数不合法、`401` 未登录、`403` 重封禁。
- `### 1.2 解绑推送设备`
  - 信息行:`> `DELETE` `/api/v1/push/devices/{registration_id}` · 需要鉴权 · 无额外限流`
  - 描述:登出时调用;幂等 204;只删自己的设备,不存在或属于别人同样 204;
  - 路径参数表;响应 `204` 无 body;请求示例;错误码 `401` / `403`。
- `### 1.3 获取通知偏好`
  - 信息行:`> `GET` `/api/v1/push/preferences` · 需要鉴权 · 无额外限流`
  - 描述:无记录时返回默认全开并落库;三个字段分别对应「新的喜欢 / 配对成功 / 系统通知」;
  - 响应参数表 + 示例;错误码 `401` / `403`。
- `### 1.4 修改通知偏好`
  - 信息行:`> `PATCH` `/api/v1/push/preferences` · 需要鉴权 · 无额外限流`
  - 描述:局部更新,只改传入字段;返回更新后的完整对象;
  - 请求参数表(三个布尔,均可选)+ 响应表 + 示例;错误码 `400` / `401` / `403`。

- [x] **Step 4: 更新 `docs/api/README.md`**

1. 目录表加一行:`| [push.md](push.md) | 推送:设备上报与通知偏好 |`
2. 接口一览表加四行(按方法 + 路径排序放在 `presence` 之后、`reports` 之前):

```markdown
| POST | `/api/v1/push/devices` | 上报推送设备 | [push](push.md) |
| DELETE | `/api/v1/push/devices/{registration_id}` | 解绑推送设备 | [push](push.md) |
| GET | `/api/v1/push/preferences` | 获取通知偏好 | [push](push.md) |
| PATCH | `/api/v1/push/preferences` | 修改通知偏好 | [push](push.md) |
```

3. 「共 **36** 个接口」改为「共 **40** 个接口」。

- [x] **Step 5: 跑门禁**

```powershell
cd chatapp
$env:TEST_REDIS_PORT="16379"
python manage.py test config.tests.ApiDocsCoverageTests
```

预期:通过。

- [x] **Step 6: 提交**

```powershell
git add docs/api/push.md docs/api/README.md
git commit -m "docs(api): 新增推送分册(4 个接口,36→40)"
```

---

### Task 7: App 依赖、原生配置与推送服务抽象

**Files:**
- Modify: `app/pubspec.yaml`
- Modify: `app/android/app/build.gradle.kts`
- Modify: `app/android/app/src/main/AndroidManifest.xml`
- Modify: `app/lib/core/config.dart`
- Create: `app/lib/core/push/push_service.dart`
- Create: `app/lib/core/push/jpush_push_service.dart`
- Create: `app/test/support/fake_push_service.dart`
- Modify: `app/test/support/harness.dart`

**Interfaces:**
- Produces:
  - `PushService`(`start` / `registrationId` / `isNotificationEnabled` / `openNotificationSettings` / `stop`)
  - `JPushPushService` / `FakePushService`
  - `jpushAppKey` 常量

- [x] **Step 1: 加依赖并拉包**

`app/pubspec.yaml` 的 `tencent_cloud_chat_sdk` 之后加:

```yaml
  jpush_flutter: ^3.5.8
```

```powershell
cd app
../flutter/bin/flutter.bat pub get
```

预期:解析成功(若与 Flutter 3.47 冲突,按报错锁到 3.5.x 最新可用版本并在提交信息里注明)。

- [x] **Step 2: 写抽象接口**

创建 `app/lib/core/push/push_service.dart`:

```dart
/// 推送服务抽象:真实实现包极光 SDK,测试用 FakePushService。
///
/// 原生插件在 `flutter test` 里跑不起来,所以所有测试都走替身;
/// 实现必须吞掉异常 —— 推送是增强能力,不能影响 App 启动。
abstract class PushService {
  /// 初始化并开始接收推送。
  ///
  /// [onOpen] 在用户点击通知时回调,参数是通知携带的 deeplink 路径。
  Future<void> start({required void Function(String deeplink) onOpen});

  /// 当前设备的极光 registration_id;初始化失败返回 null。
  Future<String?> registrationId();

  /// 系统通知权限是否已开启。
  Future<bool> isNotificationEnabled();

  /// 跳转系统通知设置页。
  Future<void> openNotificationSettings();

  /// 停止接收推送(登出时调用)。
  Future<void> stop();
}
```

- [x] **Step 3: 写极光实现**

创建 `app/lib/core/push/jpush_push_service.dart`:

```dart
import 'package:flutter/foundation.dart';
import 'package:jpush_flutter/jpush_flutter.dart';
import 'package:jpush_flutter/jpush_interface.dart';

import '../config.dart';
import 'push_service.dart';

/// 极光实现:全项目唯一 import `jpush_flutter` 的文件。
class JPushPushService implements PushService {
  JPushPushService({String? appKey}) : _appKey = appKey ?? jpushAppKey;

  final String _appKey;
  final JPushFlutterInterface _jpush = JPush.newJPush();
  bool _started = false;

  @override
  Future<void> start({required void Function(String deeplink) onOpen}) async {
    if (_started) return;
    _started = true;
    try {
      _jpush.setup(
        appKey: _appKey,
        channel: 'developer-default',
        production: !kDebugMode,
        debug: kDebugMode,
      );
      // 前台不弹通知栏:正在用 App 时,页面自身的刷新比系统通知更合适
      _jpush.setUnShowAtTheForeground(unShow: true);
      _jpush.addEventHandler(onOpenNotification: (Map<String, dynamic> message) {
        final extras = message['extras'];
        final path = extras is Map ? extras['deeplink'] : null;
        if (path is String && path.isNotEmpty) onOpen(path);
      });
      _jpush.requestRequiredPermission();
    } catch (error) {
      debugPrint('推送初始化失败: $error');
    }
  }

  @override
  Future<String?> registrationId() async {
    try {
      final id = await _jpush.getRegistrationID();
      return id.isEmpty ? null : id;
    } catch (error) {
      debugPrint('取 registration_id 失败: $error');
      return null;
    }
  }

  @override
  Future<bool> isNotificationEnabled() async {
    try {
      return await _jpush.isNotificationEnabled();
    } catch (_) {
      return false;
    }
  }

  @override
  Future<void> openNotificationSettings() async {
    try {
      _jpush.openSettingsForNotification();
    } catch (error) {
      debugPrint('打开系统通知设置失败: $error');
    }
  }

  @override
  Future<void> stop() async {
    try {
      await _jpush.stopPush();
    } catch (error) {
      debugPrint('停止推送失败: $error');
    }
  }
}
```

在 `app/lib/core/config.dart` 末尾加:

```dart
/// 极光 AppKey;Android 原生以 `key.properties` 注入的 manifest placeholder 为准,
/// 这里给 Dart 侧 `setup()` 用,两处填同一个值。
const String jpushAppKey = String.fromEnvironment('JPUSH_APP_KEY');
```

- [x] **Step 4: 写测试替身**

创建 `app/test/support/fake_push_service.dart`:

```dart
import 'package:chatapp_app/core/push/push_service.dart';

/// 推送替身:记录调用、可注入 registration_id、可手动触发点击。
class FakePushService implements PushService {
  FakePushService({this.registrationIdValue = 'rid-test', this.notificationEnabled = true});

  final String? registrationIdValue;
  bool notificationEnabled;
  int startCalls = 0;
  int stopCalls = 0;
  void Function(String deeplink)? _onOpen;

  @override
  Future<void> start({required void Function(String deeplink) onOpen}) async {
    startCalls++;
    _onOpen = onOpen;
  }

  /// 模拟用户点击通知。
  void tap(String deeplink) => _onOpen?.call(deeplink);

  @override
  Future<String?> registrationId() async => registrationIdValue;

  @override
  Future<bool> isNotificationEnabled() async => notificationEnabled;

  @override
  Future<void> openNotificationSettings() async {}

  @override
  Future<void> stop() async {
    stopCalls++;
  }
}
```

在 `app/test/support/harness.dart` 的 `pumpApp` overrides 里加:

```dart
      pushServiceProvider.overrideWithValue(fakePush ?? FakePushService()),
```

并在函数签名增加可选参数:

```dart
    FakePushService? fakePush,
```

顶部 import:

```dart
import 'package:chatapp_app/core/push/push_controller.dart';
import 'fake_push_service.dart';
```

> `pushServiceProvider` 在 Task 8 创建;本步骤先建测试替身与 harness 参数,`pushServiceProvider` 的 import 在 Task 8 落地后编译通过。为避免中间态红,Task 7 与 Task 8 连续执行,Task 7 末尾不单独跑全量。

- [x] **Step 5: Android 配置**

`app/android/app/build.gradle.kts` 的 `defaultConfig` 内(`versionName` 之后)加:

```kotlin
        manifestPlaceholders["JPUSH_PKGNAME"] = applicationId!!
        manifestPlaceholders["JPUSH_APPKEY"] =
            (keystoreProperties["jpush.appKey"] as String?) ?: ""
        manifestPlaceholders["JPUSH_CHANNEL"] =
            (keystoreProperties["jpush.channel"] as String?) ?: "developer-default"
```

`app/android/app/src/main/AndroidManifest.xml`:

1. `<manifest>` 下加权限:

```xml
    <uses-permission android:name="android.permission.POST_NOTIFICATIONS" />
```

2. `<activity android:name=".MainActivity" ...>` 内加 meta-data(极光 README 的 Flutter 3.29+ 白屏坑):

```xml
            <meta-data
                android:name="flutter_deeplinking_enabled"
                android:value="false" />
```

- [x] **Step 6: 本地填 key(不进仓库)**

在 `app/android/key.properties` 追加(值从极光控制台取;没有就先留空):

```properties
jpush.appKey=
jpush.channel=developer-default
```

在 `chatapp/.env` 追加:

```dotenv
PUSH_ENABLED=1
JPUSH_APP_KEY=
JPUSH_MASTER_SECRET=
```

> 两个文件都已 gitignore;空值时后端走日志后端、App 初始化失败也不报错。

- [x] **Step 7: 提交**

```powershell
git add app/pubspec.yaml app/pubspec.lock app/lib/core/config.dart app/lib/core/push/push_service.dart app/lib/core/push/jpush_push_service.dart app/test/support/fake_push_service.dart app/android/app/build.gradle.kts app/android/app/src/main/AndroidManifest.xml
git commit -m "feat(app/push): 极光插件 + PushService 抽象与测试替身"
```

---

### Task 8: 设备上报、登出解绑与深链

**Files:**
- Create: `app/lib/core/push/push_repository.dart`
- Create: `app/lib/core/push/push_controller.dart`
- Modify: `app/lib/app.dart`
- Modify: `app/test/support/harness.dart`
- Test: `app/test/core/push/push_controller_test.dart`

**Interfaces:**
- Consumes: Task 7 的 `PushService` / `FakePushService`;`ApiClient` / `apiClientProvider`;`sessionProvider`;`routerProvider`
- Produces:
  - `PushPreferences`(`likes` / `matches` / `system`,含 `fromJson` / `copyWith`)
  - `PushRepository`(`fetchPreferences` / `updatePreferences` / `registerDevice` / `unregisterDevice`)
  - `pushServiceProvider` / `pushRepositoryProvider` / `pushControllerProvider`
  - `pushDeeplinkHandlerProvider`(`void Function(String)`,测试可替换成记录器)

- [x] **Step 1: 写失败测试**

创建 `app/test/core/push/push_controller_test.dart`:

```dart
import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/core/push/push_controller.dart';
import 'package:chatapp_app/features/auth/session.dart';
import 'package:chatapp_app/features/presence/presence_controller.dart';
import 'package:chatapp_app/im/im_manager.dart';

import '../../support/fake_im_client.dart';
import '../../support/fake_push_service.dart';
import '../../support/scripted_adapter.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late ScriptedAdapter adapter;
  late FakeImClient fakeIm;
  late FakePushService fakePush;
  late ProviderContainer container;
  late List<String> opened;

  void buildContainer() {
    final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
    final refreshDio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))
      ..httpClientAdapter = adapter;
    container = ProviderContainer(overrides: [
      baseDioProvider.overrideWithValue(dio),
      refreshDioProvider.overrideWithValue(refreshDio),
      imClientProvider.overrideWithValue(fakeIm),
      pushServiceProvider.overrideWithValue(fakePush),
      pushDeeplinkHandlerProvider.overrideWithValue(opened.add),
      heartbeatIntervalProvider.overrideWithValue(null),
      presenceRefreshIntervalProvider.overrideWithValue(null),
    ]);
    addTearDown(container.dispose);
  }

  Future<void> login() async {
    SharedPreferences.setMockInitialValues(
        {'auth.access': 'a', 'auth.refresh': 'r', 'auth.user_id': '1'});
    adapter.routes['POST /auth/token/refresh'] =
        (options) => ok({'access': 'a2', 'refresh': 'r2'});
    await container.read(sessionProvider.notifier).bootstrap();
  }

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    adapter = ScriptedAdapter({});
    fakeIm = FakeImClient();
    fakePush = FakePushService();
    opened = [];
    addTearDown(fakeIm.dispose);
  });

  test('登录后启动推送并上报 registration_id', () async {
    adapter.routes['POST /push/devices'] =
        (options) => ok({'registration_id': 'rid-test', 'platform': 'android'});
    buildContainer();
    await login();
    container.read(pushControllerProvider);
    await pumpEventQueue();

    expect(fakePush.startCalls, 1);
    final register = adapter.log
        .where((r) => r.method == 'POST' && r.path == '/push/devices')
        .toList();
    expect(register, hasLength(1));
    expect((register.single.data as Map)['registration_id'], 'rid-test');
  });

  test('登出时解绑并停止推送', () async {
    adapter.routes['POST /push/devices'] =
        (options) => ok({'registration_id': 'rid-test', 'platform': 'android'});
    adapter.routes['DELETE /push/devices/rid-test'] = (options) => ok({}, status: 204);
    buildContainer();
    await login();
    container.read(pushControllerProvider);
    await pumpEventQueue();

    await container.read(sessionProvider.notifier).logout();
    await pumpEventQueue();

    expect(fakePush.stopCalls, 1);
    expect(adapter.log.any((r) => r.method == 'DELETE' && r.path == '/push/devices/rid-test'),
        isTrue);
  });

  test('registration_id 为空时不上报', () async {
    fakePush = FakePushService(registrationIdValue: null);
    buildContainer();
    await login();
    container.read(pushControllerProvider);
    await pumpEventQueue();

    expect(adapter.log.any((r) => r.path == '/push/devices'), isFalse);
  });

  test('点击通知交给 deeplink 处理器', () async {
    adapter.routes['POST /push/devices'] =
        (options) => ok({'registration_id': 'rid-test', 'platform': 'android'});
    buildContainer();
    await login();
    container.read(pushControllerProvider);
    await pumpEventQueue();

    fakePush.tap('/likes');
    await pumpEventQueue();

    expect(opened, ['/likes']);
  });
}
```

> `ScriptedAdapter` 的构造是 `ScriptedAdapter({...})`,请求记录在 `log` 里,响应助手是顶层
> `ok()` / `jsonError()` / `offline()`;断言点按上面的写法即可。

- [x] **Step 2: 跑测试确认失败**

```powershell
cd app
../flutter/bin/flutter.bat test test/core/push/push_controller_test.dart
```

预期:编译失败(`push_controller.dart` 不存在)。

- [x] **Step 3: 写仓库与控制器**

创建 `app/lib/core/push/push_repository.dart`:

```dart
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api_client.dart';
import '../providers.dart';

/// 三类通知开关(账号级,与后端 `NotificationPreference` 一一对应)。
class PushPreferences {
  const PushPreferences({required this.likes, required this.matches, required this.system});

  factory PushPreferences.fromJson(Map<String, dynamic> json) => PushPreferences(
        likes: json['likes'] as bool,
        matches: json['matches'] as bool,
        system: json['system'] as bool,
      );

  final bool likes;
  final bool matches;
  final bool system;

  PushPreferences copyWith({bool? likes, bool? matches, bool? system}) => PushPreferences(
        likes: likes ?? this.likes,
        matches: matches ?? this.matches,
        system: system ?? this.system,
      );
}

/// 推送相关的后端调用:设备上报/解绑与偏好读写。
class PushRepository {
  PushRepository(this._api);

  final ApiClient _api;

  Future<PushPreferences> fetchPreferences() async {
    final data = await _api.get('/push/preferences') as Map<String, dynamic>;
    return PushPreferences.fromJson(data);
  }

  Future<PushPreferences> updatePreferences({bool? likes, bool? matches, bool? system}) async {
    final data = await _api.patch('/push/preferences', data: {
      if (likes != null) 'likes': likes,
      if (matches != null) 'matches': matches,
      if (system != null) 'system': system,
    }) as Map<String, dynamic>;
    return PushPreferences.fromJson(data);
  }

  Future<void> registerDevice(String registrationId,
      {String platform = 'android', String? appVersion}) async {
    await _api.post('/push/devices', data: {
      'registration_id': registrationId,
      'platform': platform,
      if (appVersion != null) 'app_version': appVersion,
    });
  }

  Future<void> unregisterDevice(String registrationId) async {
    await _api.delete('/push/devices/$registrationId');
  }
}

final pushRepositoryProvider =
    Provider<PushRepository>((ref) => PushRepository(ref.watch(apiClientProvider)));
```

创建 `app/lib/core/push/push_controller.dart`:

```dart
import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../features/auth/session.dart';
import '../../router.dart';
import 'jpush_push_service.dart';
import 'push_repository.dart';
import 'push_service.dart';

/// 推送生命周期:登录上报、登出解绑、点击通知路由。
enum PushStatus { idle, registering, ready, failed }

/// 真实推送服务(全局单例语义);测试里 override 成 FakePushService。
final pushServiceProvider = Provider<PushService>((ref) => JPushPushService());

class PushController extends Notifier<PushStatus> {
  String? _registrationId;
  bool _started = false;

  @override
  PushStatus build() {
    ref.listen(sessionProvider, (_, next) {
      switch (next) {
        case SessionLoggedIn():
          unawaited(_register());
        case SessionLoggedOut():
          unawaited(_unregister());
        default:
          break;
      }
    });
    if (ref.read(sessionProvider) is SessionLoggedIn) {
      unawaited(_register());
    }
    return PushStatus.idle;
  }

  Future<void> _register() async {
    if (_started) return;
    _started = true;
    state = PushStatus.registering;
    try {
      final service = ref.read(pushServiceProvider);
      await service.start(onOpen: _openDeeplink);
      final id = await service.registrationId();
      if (id == null || id.isEmpty) {
        state = PushStatus.failed;
        return;
      }
      _registrationId = id;
      await ref.read(pushRepositoryProvider).registerDevice(id);
      state = PushStatus.ready;
    } catch (error) {
      debugPrint('推送注册失败: $error');
      state = PushStatus.failed;
    }
  }

  Future<void> _unregister() async {
    final id = _registrationId;
    _registrationId = null;
    _started = false;
    try {
      if (id != null) await ref.read(pushRepositoryProvider).unregisterDevice(id);
    } catch (error) {
      debugPrint('推送解绑失败: $error');
    }
    try {
      await ref.read(pushServiceProvider).stop();
    } catch (error) {
      debugPrint('停止推送失败: $error');
    }
    state = PushStatus.idle;
  }

  void _openDeeplink(String path) {
    if (ref.read(sessionProvider) is! SessionLoggedIn) return;
    if (!path.startsWith('/')) return;
    ref.read(pushDeeplinkHandlerProvider)(path);
  }
}

/// 点击通知后的跳转动作;测试里 override 成记录器,避免真的驱动 GoRouter。
final pushDeeplinkHandlerProvider = Provider<void Function(String)>((ref) => (path) {
      ref.read(routerProvider).go(path);
    });

final pushControllerProvider =
    NotifierProvider<PushController, PushStatus>(PushController.new);
```

在 `app/lib/app.dart` 的 `build` 里加一行(激活生命周期):

```dart
    ref.watch(pushControllerProvider);
```

并 import:

```dart
import 'core/push/push_controller.dart';
```

- [x] **Step 4: 跑测试确认通过**

```powershell
cd app
../flutter/bin/flutter.bat test test/core/push/push_controller_test.dart
```

预期:4 个用例通过。

- [x] **Step 5: 跑 analyze**

```powershell
cd app
../flutter/bin/flutter.bat analyze
```

预期:No issues found。

- [x] **Step 6: 提交**

```powershell
git add app/lib/core/push/push_repository.dart app/lib/core/push/push_controller.dart app/lib/app.dart app/test/core/push/push_controller_test.dart app/test/support/harness.dart
git commit -m "feat(app/push): 登录上报/登出解绑/点击深链"
```

---

### Task 9: App 通知设置页

**Files:**
- Modify: `app/lib/features/settings/notification_settings_page.dart`
- Test: `app/test/features/settings/notification_settings_page_test.dart`(重写)

**Interfaces:**
- Consumes: `PushRepository` / `PushPreferences`(Task 8)、`pushServiceProvider`(Task 8)
- Produces: 三项真开关 + 权限提示

- [x] **Step 1: 写失败测试**

重写 `app/test/features/settings/notification_settings_page_test.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/push/push_controller.dart';
import 'package:chatapp_app/core/push/push_repository.dart';
import 'package:chatapp_app/features/settings/notification_settings_page.dart';

import '../../support/fake_push_service.dart';

/// 仓库替身:不发网络请求,只按内存里的偏好返回。
class _FakePushRepository implements PushRepository {
  _FakePushRepository(this.preferences, {this.failUpdate = false});

  PushPreferences preferences;
  final bool failUpdate;

  @override
  Future<PushPreferences> fetchPreferences() async => preferences;

  @override
  Future<PushPreferences> updatePreferences({bool? likes, bool? matches, bool? system}) async {
    if (failUpdate) throw ApiException('更新失败');
    preferences = preferences.copyWith(likes: likes, matches: matches, system: system);
    return preferences;
  }

  @override
  Future<void> registerDevice(String registrationId,
      {String platform = 'android', String? appVersion}) async {}

  @override
  Future<void> unregisterDevice(String registrationId) async {}
}

void main() {
  Future<FakePushService> pumpPage(
    WidgetTester tester, {
    PushPreferences? preferences,
    bool notificationEnabled = true,
    bool failUpdate = false,
  }) async {
    final fake = FakePushService(notificationEnabled: notificationEnabled);
    await tester.pumpWidget(ProviderScope(
      overrides: [
        pushServiceProvider.overrideWithValue(fake),
        pushRepositoryProvider.overrideWithValue(_FakePushRepository(
          preferences ??
              const PushPreferences(likes: true, matches: true, system: true),
          failUpdate: failUpdate,
        )),
      ],
      child: const MaterialApp(home: NotificationSettingsPage()),
    ));
    await tester.pumpAndSettle();
    return fake;
  }

  testWidgets('三个开关按偏好渲染', (tester) async {
    await pumpPage(tester,
        preferences: const PushPreferences(likes: true, matches: true, system: false));

    expect(find.text('新的喜欢'), findsOneWidget);
    expect(find.text('配对成功'), findsOneWidget);
    expect(find.text('系统通知'), findsOneWidget);
    expect(find.text('新消息提醒需要接入离线推送,将在后续版本开放'), findsOneWidget);

    final switches = tester.widgetList<Switch>(find.byType(Switch)).toList();
    expect(switches, hasLength(3));
    expect(switches.every((item) => item.onChanged != null), isTrue);
    expect(switches.map((item) => item.value).toList(), [true, true, false]);
  });

  testWidgets('通知权限关闭时显示提示', (tester) async {
    await pumpPage(tester, notificationEnabled: false);
    expect(find.text('系统通知未开启'), findsOneWidget);
    expect(find.text('去开启'), findsOneWidget);
  });

  testWidgets('切换失败时回滚并提示', (tester) async {
    await pumpPage(tester, failUpdate: true);

    await tester.tap(find.byType(Switch).first);
    await tester.pumpAndSettle();

    expect(tester.widgetList<Switch>(find.byType(Switch)).first.value, isTrue);
    expect(find.text('更新失败'), findsOneWidget);
  });
}
```

> `_FakePushRepository` 用 `implements PushRepository` 覆盖全部方法,测试不碰网络;
> `ApiException` 从 `package:chatapp_app/core/api_exception.dart` import。

- [x] **Step 2: 跑测试确认失败**

```powershell
cd app
../flutter/bin/flutter.bat test test/features/settings/notification_settings_page_test.dart
```

预期:失败(页面还是旧的两项只读骨架)。

- [x] **Step 3: 重写页面**

`app/lib/features/settings/notification_settings_page.dart` 改为 `ConsumerStatefulWidget`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_exception.dart';
import '../../core/push/push_controller.dart';
import '../../core/push/push_repository.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/theme/app_typography.dart';
import '../../core/widgets/app_error_view.dart';
import '../../core/widgets/app_list_row.dart';
import '../../core/widgets/app_row_group.dart';
import '../../core/widgets/app_sub_page_bar.dart';
import '../../core/widgets/app_toast.dart';

/// 通知设置:三项真实开关(账号级)+ 系统通知权限提示。
class NotificationSettingsPage extends ConsumerStatefulWidget {
  const NotificationSettingsPage({super.key});

  @override
  ConsumerState<NotificationSettingsPage> createState() => _NotificationSettingsPageState();
}

class _NotificationSettingsPageState extends ConsumerState<NotificationSettingsPage> {
  PushPreferences? _prefs;
  bool _loading = true;
  String? _error;
  bool _notificationEnabled = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final prefs = await ref.read(pushRepositoryProvider).fetchPreferences();
      final enabled = await ref.read(pushServiceProvider).isNotificationEnabled();
      if (!mounted) return;
      setState(() {
        _prefs = prefs;
        _notificationEnabled = enabled;
        _loading = false;
      });
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _error = error.message;
        _loading = false;
      });
    }
  }

  Future<void> _toggle({bool? likes, bool? matches, bool? system}) async {
    final current = _prefs;
    if (current == null) return;
    final next = current.copyWith(likes: likes, matches: matches, system: system);
    setState(() => _prefs = next);           // 乐观更新
    try {
      final saved = await ref.read(pushRepositoryProvider)
          .updatePreferences(likes: likes, matches: matches, system: system);
      if (!mounted) return;
      setState(() => _prefs = saved);
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() => _prefs = current);      // 失败回滚
      AppToast.show(context, error.message);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        backgroundColor: AppColors.bgPage,
        body: SafeArea(
          bottom: false,
          child: Column(
            children: [
              const AppSubPageBar(title: '通知设置'),
              Expanded(child: _body()),
            ],
          ),
        ),
      );

  Widget _body() {
    if (_loading) return const Center(child: CircularProgressIndicator());
    final error = _error;
    if (error != null) {
      return AppErrorView(message: error, onRetry: _load);
    }
    final prefs = _prefs!;
    return ListView(
      padding: const EdgeInsets.fromLTRB(
          AppSpacing.pageH, AppSpacing.md, AppSpacing.pageH, AppSpacing.xxl),
      children: [
        if (!_notificationEnabled) ...[
          AppRowGroup(children: [
            AppListRow(
              key: const Key('notifications.permission'),
              icon: Icons.notifications_off_rounded,
              title: '系统通知未开启',
              subtitle: '开启后才能收到提醒',
              trailing: Text('去开启',
                  style: AppText.body.copyWith(color: AppColors.brand)),
              onTap: () => ref.read(pushServiceProvider).openNotificationSettings(),
            ),
          ]),
          const SizedBox(height: AppSpacing.cardGap),
        ],
        AppRowGroup(children: [
          _NotifyRow(
            key: const Key('notifications.likes'),
            icon: Icons.favorite_rounded,
            title: '新的喜欢',
            subtitle: '有人喜欢你时提醒你',
            value: prefs.likes,
            onChanged: (value) => _toggle(likes: value),
          ),
          _NotifyRow(
            key: const Key('notifications.matches'),
            icon: Icons.celebration_rounded,
            title: '配对成功',
            subtitle: '互相喜欢时提醒你',
            value: prefs.matches,
            onChanged: (value) => _toggle(matches: value),
          ),
          _NotifyRow(
            key: const Key('notifications.system'),
            icon: Icons.shield_rounded,
            title: '系统通知',
            subtitle: '举报处理、账号限制等通知',
            value: prefs.system,
            onChanged: (value) => _toggle(system: value),
          ),
        ]),
        const SizedBox(height: AppSpacing.lg),
        Text('新消息提醒需要接入离线推送,将在后续版本开放',
            style: AppText.caption.copyWith(color: AppColors.text3)),
      ],
    );
  }
}

class _NotifyRow extends StatelessWidget {
  const _NotifyRow({
    super.key,
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.value,
    required this.onChanged,
  });

  final IconData icon;
  final String title;
  final String subtitle;
  final bool value;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) => AppListRow(
        icon: icon,
        title: title,
        subtitle: subtitle,
        showChevron: false,
        trailing: Switch.adaptive(value: value, onChanged: onChanged),
      );
}
```

> `AppErrorView` 的构造参数与 `AppColors.primary` 名称以现有组件为准(`app/lib/core/widgets/app_error_view.dart`、`app/lib/core/theme/app_colors.dart`);若颜色 token 叫 `brandPrimary` 之类,改用实际名字。

- [x] **Step 4: 跑测试确认通过**

```powershell
cd app
../flutter/bin/flutter.bat test test/features/settings/notification_settings_page_test.dart
```

预期:2 个用例通过。

- [x] **Step 5: 跑 analyze + 全量测试**

```powershell
cd app
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test
```

预期:零告警、全绿(原有 375 个用例 + 新增)。

- [x] **Step 6: 提交**

```powershell
git add app/lib/features/settings/notification_settings_page.dart app/test/features/settings/notification_settings_page_test.dart
git commit -m "feat(app/settings): 通知设置三项真开关 + 权限提示"
```

---

### Task 10: Web 通知设置页

**Files:**
- Create: `web/src/api/push.ts`
- Create: `web/src/stores/push.ts`
- Modify: `web/src/features/settings/NotificationSettingsPage.vue`
- Test: `web/tests/component/notification-settings-page.spec.ts`(重写)

**Interfaces:**
- Consumes: `GET/PATCH /api/v1/push/preferences`
- Produces: 三个可点开关 + 说明文案

- [x] **Step 1: 写失败测试**

重写 `web/tests/component/notification-settings-page.spec.ts`:

```ts
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import NotificationSettingsPage from '@/features/settings/NotificationSettingsPage.vue'

const getPushPreferences = vi.fn()
const updatePushPreferences = vi.fn()

vi.mock('@/api/push', () => ({
  getPushPreferences: () => getPushPreferences(),
  updatePushPreferences: (patch: unknown) => updatePushPreferences(patch),
}))

describe('NotificationSettingsPage', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    getPushPreferences.mockReset()
    updatePushPreferences.mockReset()
  })

  it('按后端偏好渲染三个开关与网页端说明', async () => {
    getPushPreferences.mockResolvedValue({ likes: true, matches: true, system: false })
    const w = mount(NotificationSettingsPage, {
      global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })
    await flushPromises()

    expect(w.text()).toContain('新的喜欢')
    expect(w.text()).toContain('配对成功')
    expect(w.text()).toContain('系统通知')
    expect(w.text()).toContain('网页端不接收推送')

    const switches = w.findAll('[role="switch"]')
    expect(switches).toHaveLength(3)
    expect(switches[2].attributes('aria-checked')).toBe('false')
  })

  it('切换开关时调用接口并更新状态', async () => {
    getPushPreferences.mockResolvedValue({ likes: true, matches: true, system: true })
    updatePushPreferences.mockResolvedValue({ likes: false, matches: true, system: true })
    const w = mount(NotificationSettingsPage, {
      global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })
    await flushPromises()

    await w.findAll('[role="switch"]')[0].trigger('click')
    await flushPromises()

    expect(updatePushPreferences).toHaveBeenCalledWith({ likes: false })
    expect(w.findAll('[role="switch"]')[0].attributes('aria-checked')).toBe('false')
  })

  it('接口失败时回滚并提示', async () => {
    getPushPreferences.mockResolvedValue({ likes: true, matches: true, system: true })
    updatePushPreferences.mockRejectedValue(new Error('网络错误'))
    const w = mount(NotificationSettingsPage, {
      global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })
    await flushPromises()

    await w.findAll('[role="switch"]')[0].trigger('click')
    await flushPromises()

    expect(w.findAll('[role="switch"]')[0].attributes('aria-checked')).toBe('true')
    expect(w.text()).toContain('网络错误')
  })
})
```

- [x] **Step 2: 跑测试确认失败**

```powershell
cd web
npm run test:run -- tests/component/notification-settings-page.spec.ts
```

预期:失败(`@/api/push` 不存在)。

- [x] **Step 3: 写 api 与 store**

创建 `web/src/api/push.ts`:

```ts
import { http } from './http'

export interface PushPreferences {
  likes: boolean
  matches: boolean
  system: boolean
}

export async function getPushPreferences(): Promise<PushPreferences> {
  const { data } = await http.get<PushPreferences>('/push/preferences')
  return data
}

export async function updatePushPreferences(
  patch: Partial<PushPreferences>,
): Promise<PushPreferences> {
  const { data } = await http.patch<PushPreferences>('/push/preferences', patch)
  return data
}
```

创建 `web/src/stores/push.ts`:

```ts
import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as pushApi from '@/api/push'
import type { PushPreferences } from '@/api/push'
import { parseApiError } from '@/api/error'

export const usePushStore = defineStore('push', () => {
  const prefs = ref<PushPreferences | null>(null)
  const loading = ref(false)
  const error = ref('')

  async function load(): Promise<void> {
    loading.value = true
    error.value = ''
    try {
      prefs.value = await pushApi.getPushPreferences()
    } catch (e) {
      error.value = parseApiError(e).message
    } finally {
      loading.value = false
    }
  }

  async function toggle(key: keyof PushPreferences, value: boolean): Promise<void> {
    const current = prefs.value
    if (!current) return
    prefs.value = { ...current, [key]: value }
    error.value = ''
    try {
      prefs.value = await pushApi.updatePushPreferences({ [key]: value })
    } catch (e) {
      prefs.value = current
      error.value = parseApiError(e).message
    }
  }

  return { prefs, loading, error, load, toggle }
})
```

- [x] **Step 4: 重写页面**

`web/src/features/settings/NotificationSettingsPage.vue`:

```vue
<script setup lang="ts">
import { onMounted } from 'vue'
import { RouterLink } from 'vue-router'
import { storeToRefs } from 'pinia'
import { usePushStore } from '@/stores/push'
import type { PushPreferences } from '@/api/push'

const store = usePushStore()
const { prefs, loading, error } = storeToRefs(store)

const rows: { key: keyof PushPreferences; title: string; desc: string }[] = [
  { key: 'likes', title: '新的喜欢', desc: '有人喜欢你时提醒你' },
  { key: 'matches', title: '配对成功', desc: '互相喜欢时提醒你' },
  { key: 'system', title: '系统通知', desc: '举报处理、账号限制等通知' },
]

onMounted(() => {
  void store.load()
})
</script>

<template>
  <section class="notify">
    <header class="notify__header">
      <RouterLink class="notify__back" :to="{ name: 'settings' }">← 返回</RouterLink>
      <h1 class="notify__title">通知设置</h1>
      <p class="notify__hint">网页端不接收推送,这里的设置只影响 App。</p>
    </header>

    <p v-if="loading" class="notify__hint">加载中…</p>
    <p v-else-if="error" class="notify__error">{{ error }}</p>

    <ul v-if="prefs" class="notify__list">
      <li v-for="row in rows" :key="row.key" class="notify__row">
        <span class="notify__meta">
          <span class="notify__name">{{ row.title }}</span>
          <span class="notify__desc">{{ row.desc }}</span>
        </span>
        <button
          type="button"
          class="notify__switch"
          :class="{ 'notify__switch--on': prefs[row.key] }"
          role="switch"
          :aria-checked="prefs[row.key]"
          @click="store.toggle(row.key, !prefs[row.key])"
        >
          <span class="notify__knob" />
        </button>
      </li>
    </ul>

    <p class="notify__hint">
      新消息提醒需要接入离线推送,将在后续版本开放。
    </p>
  </section>
</template>

<style scoped>
/* 保留原有 .notify 布局;只新增开关「开」态与错误文案样式 */
.notify__switch--on {
  background: var(--color-brand);
  cursor: pointer;
}
.notify__switch--on .notify__knob {
  left: 21px;
}
.notify__error {
  margin: 0;
  color: var(--color-danger);
  font-size: var(--text-caption);
}
</style>
```

> 样式沿用现有 `.notify__*` 规则(本文件原有 scoped 样式保留,只追加三条);token 名以 `web/src/styles/tokens.css` 为准(`--color-brand` / `--color-danger` 若不存在,换成实际名称,例如 `--color-primary`)。

- [x] **Step 5: 跑测试**

```powershell
cd web
npm run test:run -- tests/component/notification-settings-page.spec.ts
```

预期:3 个用例通过。

- [x] **Step 6: type-check 与 lint**

```powershell
cd web
npm run type-check
npm run lint
```

预期:零错误、零告警。

- [x] **Step 7: 提交**

```powershell
git add web/src/api/push.ts web/src/stores/push.ts web/src/features/settings/NotificationSettingsPage.vue web/tests/component/notification-settings-page.spec.ts
git commit -m "feat(web/settings): 通知设置三项开关(可编辑,注明仅影响 App)"
```

---

### Task 11: 全量验证、文档回填与收尾

**Files:**
- Modify: `docs/superpowers/specs/2026-10-20-push-notifications-design.md`(状态行)
- Modify: `docs/superpowers/plans/2026-10-20-push-notifications.md`(checkbox + 执行记录)
- Modify: `CLAUDE.md`(里程碑 + 下一步)
- Modify: `README.md`(如接口表/下一步有对应描述)

- [x] **Step 1: 后端全量**

```powershell
cd chatapp
$env:TEST_REDIS_PORT="16379"
python manage.py test
```

预期:全绿(含 `ApiDocsCoverageTests` / `CommentCoverageTests`)。

- [x] **Step 2: App 全量**

```powershell
cd app
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test
```

预期:零告警、全绿。

- [x] **Step 3: Web 全量**

```powershell
cd web
npm run type-check
npm run lint
npm run test:coverage
```

预期:零错误、零告警、覆盖率达标(70/60/70/70)。

- [x] **Step 4: 真机/日志后端验证**

没有极光 key 时:

1. 起后端 + Celery worker;
2. 用 `python manage.py im_send` 无关;直接构造:另一个账号喜欢当前账号,观察后端日志出现
   `[推送-日志] devices=... title=有人喜欢了你`;
3. 关掉「新的喜欢」开关后重复,日志不再出现。

有 key 时按 spec §9 的 7 条清单走真机。

- [x] **Step 5: 回填文档**

1. spec 第 3 行状态改为 `已交付(2026-10-2X)`;若真机未完成,写 `已交付(代码与门禁;真机待 key)`;
2. plan 全部 `- [x]`,末尾加「执行记录」段:测试数、commit、与计划的偏差;
3. `CLAUDE.md` 里程碑表加一行:

```
| 2026-10-2X | P1-4「推送」交付(极光 JPush;设备注册/三类通知/深链;接口 36→40,后端 XXX / App XXX / Web XXX 测试绿) |
```

4. `CLAUDE.md`「下一步」改为:P1 留存闭环收官;P1-4b 聊天消息推送待 HTTPS 域名或厂商证书;上线合规轨继续。

- [x] **Step 6: 提交**

```powershell
git add docs/superpowers/specs/2026-10-20-push-notifications-design.md docs/superpowers/plans/2026-10-20-push-notifications.md CLAUDE.md README.md
git commit -m "docs: P1-4 推送收尾回填(验收结果与里程碑)"
```

---

## 自检清单(写完后逐条核对)

- [x] 后端:模型、四个接口、客户端、任务、冷却、四个触发点、文档门禁都有对应任务;
- [x] App:依赖与原生配置、抽象与替身、登录上报/登出解绑、深链、设置页都有对应任务;
- [x] Web:api、store、页面、测试都有对应任务;
- [x] 类型一致:`enqueue_push(user_id, kind, *, title, alert, extras)` 在 Task 4/5 中同名同参;
      `PushService` 五个方法在 Task 7/8/9 中同名;
- [x] 没有「TBD / 类似 Task N / 自行补充」类占位。

---

## 执行记录(2026-10-20)

**结果**:11 个任务全部完成,分支 `feat/p1-4-push`;代码、三端门禁与接口文档全绿,真机推送待极光 key。

**门禁**

| 套件 | 结果 |
|---|---|
| 后端 `python manage.py test` | 459 tests OK(含 `ApiDocsCoverageTests` / `CommentCoverageTests`) |
| App `flutter analyze` | No issues found |
| App `flutter test` | 382 tests passed |
| Web `vue-tsc` / `eslint --max-warnings 0` | 零错误 / 零告警 |
| Web `npm run test:coverage` | 338 tests passed;覆盖率 86.68 / 82.31 / 82.02 / 88.72(门槛 70/60/70/70) |

**提交**

1. `docs(spec): P1-4 推送设计(极光 JPush + 设备/偏好/三类通知)`
2. `docs(plan): P1-4 推送实施计划(11 任务)`
3. `feat(push): PushDevice + NotificationPreference 模型与迁移`
4. `feat(push): 设备上报与解绑接口`
5. `test(push): 通知偏好接口测试`
6. `feat(push): 极光/日志推送客户端 + 入队服务 + 发送任务(含喜欢冷却)`
7. `feat(push): 喜欢/配对/举报/封禁四类事件接入推送`
8. `docs(api): 新增推送分册(4 个接口,36→40)`
9. `feat(app/push): 极光接入 + 设备上报/深链 + 通知设置三项真开关`
10. `feat(web/settings): 通知设置三项开关(可编辑,注明仅影响 App)`
11. `feat(push): push_test 管理命令(真机验收自检三类推送)`

**与计划的偏差 / 踩到的坑**

1. **`flutter pub add` 的符号链接提示**:命令末尾报「Building with plugins requires symlink support」,
   但 `flutter pub get`、`analyze`、`test` 都正常;若之后打 APK 遇到同类报错,需在 Windows
   设置里开启「开发者模式」。
2. **极光 `EventHandler` 返回 `Future<dynamic>`**:`onOpenNotification` 回调必须写成 `async`,
   否则编译报「A non-null value must be returned」。
3. **`swipe` 里 `created` 是配对分支的局部变量**:推送判断最初直接用它,报
   `UnboundLocalError`;把滑卡记录的返回值改名为 `swipe_created` 后才正确。
4. **登录态测试都会触发推送注册**:`pumpApp` 默认注入
   `FakePushService(registrationIdValue: null)`,避免每个用例多打一次 `/push/devices` 404;
   `settings_page_test` 的 DELETE 断言改为按路径过滤(推送解绑也是 DELETE)。
5. **Web 动效 token 是 `--motion-fast`**,没有 `--motion-micro`,页面里已改用前者。
6. **本机 Redis 映射在 16379**,后端测试统一用 `$env:TEST_REDIS_PORT="16379"` 跑。

**待用户执行(真机)**

1. 注册极光账号 → 创建应用(包名 `com.chatapp.chatapp_app`)→ 拿 AppKey / MasterSecret;
2. `app/android/key.properties` 填 `jpush.appKey`;`chatapp/.env` 填 `JPUSH_APP_KEY` 与
   `JPUSH_MASTER_SECRET`(并把 `PUSH_ENABLED=1`);重新打 APK;
3. 先在 App 登录一次(登记设备),再跑
   `python manage.py push_test --user <账号id> --kind all --peer <聊天对象id>`,
   确认三类推送都能收到、点击跳转正确;
4. 按 spec §9 的 7 条清单验收:三类推送各收一条、点击跳对页面、关开关后不再收到、
   被顶号后旧设备不再收到。
