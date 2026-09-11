# M3 合规收尾 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付 M3 里程碑:审核台(照片审核/举报队列/封禁+审计)、举报拉黑全链路(接口+前端)、重封禁全域拦截、用户协议与隐私政策(首启弹窗同意)、Android 签名 APK。

**Architecture:** 后端在空的 `moderation` app 里落 Report/Block/BanLog 三模型与全部接口,封禁拦截用一个全局 DRF 权限类;IM 侧联动(黑名单、踢下线)复用 `im/client.py` 的 REST 客户端 + 后台线程模式。前端在 `features/moderation`(数据层)、`features/profile/user_profile_page.dart`(资料卡)、`features/legal`(协议)、`features/shell`(封禁页)落地,IM 抽象层扩 `deleteConversation`。

**Tech Stack:** Django 5.2 + DRF + MySQL(后端);Flutter 3.47 + Riverpod 3 + go_router + dio + tencent_cloud_chat_sdk(前端)。

上游文档:`docs/superpowers/specs/2026-09-11-m3-compliance-design.md`(设计)、`2026-09-09-dating-app-mvp-design.md`(总 spec)。

## Global Constraints

- 后端失败响应统一 `{"code": <HTTP状态码>, "message": "<中文提示>"}`(全局异常处理器已就位,新代码只需抛 DRF 异常)
- 后端命令 cwd = `chatapp/`,Python 用 anaconda `Django` 环境;测试 `python manage.py test`,单 app `python manage.py test moderation`
- **凡是会触发 IM 调用的用例必须 mock**,否则真打腾讯云(项目铁律,M2c 教训)
- 限流用例必须 `cache.clear()`(计数在 LocMem 缓存里,跨用例残留导致偶发 429)
- 后台线程函数(`moderation.services._dispatch_async` / `discovery.services._notify_async`)是测试的 patch 点,**别 patch 线程里的真实调用**
- 前端命令 cwd = `app/`,用 `../flutter/bin/flutter.bat`;`analyze` 必须零告警
- 前端 widget 测试:网络用 `ScriptedAdapter` 按 `"METHOD path"` 铺路由,IM 用 `FakeImClient`,`pumpApp` 默认已注入
- 文案一律中文;分支 `m3-compliance`;每个 Task 完成即 commit(提交信息带 `(M3)` 后缀,与 `(M2c)` 风格一致)

---

## 批次 1:模型 + 封禁链路(后端)

### Task 1: moderation 三模型 + Profile.ban_reason

**Files:**
- Modify: `chatapp/moderation/models.py`(当前是空壳)
- Modify: `chatapp/users/models.py`(Profile 加字段)
- Create: `chatapp/moderation/migrations/0001_initial.py`、`chatapp/users/migrations/0003_profile_ban_reason.py`(makemigrations 生成)
- Test: `chatapp/moderation/tests.py`(扩充现有 TextCheckTests)

**Interfaces:**
- Produces: `ReportType`(harassment/porn/fraud/other)、`ReportStatus`(pending/handled)、`BanAction`(ban_light/ban_heavy/unban);模型 `Report(reporter, target, type, detail, status, handled_note, handled_by, created_at, handled_at)`、`Block(blocker, blocked, created_at)`、`BanLog(user, action, reason, operator, created_at)`;`Profile.ban_reason` 字段。后续 Task 3/6/7/9 全部依赖这些名字。

- [x] **Step 1: 写模型测试(先让它失败)**

在 `chatapp/moderation/tests.py` 末尾追加(保留文件头部现有的 TextCheckTests):

```python
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from .models import BanAction, BanLog, Block, Report, ReportStatus, ReportType

User = get_user_model()


class ModerationModelTests(TestCase):
    def setUp(self):
        self.a = User.objects.create_user(phone="13800138000")
        self.b = User.objects.create_user(phone="13900139000")

    def test_block_pair_is_unique(self):
        Block.objects.create(blocker=self.a, blocked=self.b)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Block.objects.create(blocker=self.a, blocked=self.b)

    def test_block_self_rejected_by_check_constraint(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Block.objects.create(blocker=self.a, blocked=self.a)

    def test_report_defaults_to_pending(self):
        report = Report.objects.create(reporter=self.a, target=self.b, type=ReportType.HARASSMENT)
        self.assertEqual(report.status, ReportStatus.PENDING)
        self.assertIsNone(report.handled_at)

    def test_ban_log_records_action(self):
        log = BanLog.objects.create(user=self.b, action=BanAction.BAN_HEAVY,
                                    reason="骚扰他人", operator=self.a)
        self.assertEqual(log.action, "ban_heavy")
        self.assertEqual(BanLog.objects.filter(user=self.b).count(), 1)

    def test_profile_has_ban_reason_field(self):
        profile = self.b.profile
        profile.ban_reason = "违规"
        profile.save()
        self.b.profile.refresh_from_db()
        self.assertEqual(self.b.profile.ban_reason, "违规")
```

- [x] **Step 2: 跑测试确认失败**

```bash
python manage.py test moderation
```

Expected: FAIL —— `ImportError: cannot import name 'BanAction' from 'moderation.models'`(以及 `test_profile_has_ban_reason_field` 会因为 profile 不存在/字段缺失报错)。

- [x] **Step 3: 实现三个模型**

`chatapp/moderation/models.py` 全文替换:

```python
from django.conf import settings
from django.db import models
from django.db.models import F, Q


class ReportType(models.TextChoices):
    HARASSMENT = "harassment", "骚扰"
    PORN = "porn", "色情"
    FRAUD = "fraud", "诈骗"
    OTHER = "other", "其他"


class ReportStatus(models.TextChoices):
    PENDING = "pending", "待处理"
    HANDLED = "handled", "已处理"


class Report(models.Model):
    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                 related_name="reports_made")
    target = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                               related_name="reports_received")
    type = models.CharField("类型", max_length=20, choices=ReportType.choices)
    detail = models.CharField("补充说明", max_length=200, blank=True)
    status = models.CharField("状态", max_length=10, choices=ReportStatus.choices,
                              default=ReportStatus.PENDING)
    handled_note = models.CharField("处理备注", max_length=200, blank=True)
    handled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="reports_handled")
    created_at = models.DateTimeField(auto_now_add=True)
    handled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"report#{self.pk}({self.reporter_id}->{self.target_id}:{self.type})"


class Block(models.Model):
    blocker = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name="blocks_made")
    blocked = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name="blocks_received")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["blocker", "blocked"], name="uniq_block_pair"),
            models.CheckConstraint(condition=~Q(blocker=F("blocked")), name="block_not_self"),
        ]

    def __str__(self):
        return f"block({self.blocker_id}->{self.blocked_id})"


class BanAction(models.TextChoices):
    BAN_LIGHT = "ban_light", "轻度封禁"
    BAN_HEAVY = "ban_heavy", "重度封禁"
    UNBAN = "unban", "解封"


class BanLog(models.Model):
    """封禁审计,只增不改;当前生效原因在 Profile.ban_reason。"""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="ban_logs")
    action = models.CharField("动作", max_length=10, choices=BanAction.choices)
    reason = models.CharField("原因", max_length=200, blank=True)
    operator = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                 on_delete=models.SET_NULL, related_name="ban_actions")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"ban#{self.pk}({self.user_id}:{self.action})"
```

`chatapp/users/models.py` 的 `Profile` 里,`status` 字段后面加一行:

```python
    ban_reason = models.CharField("封禁原因", max_length=200, blank=True)
```

- [x] **Step 4: 生成迁移并跑测试**

```bash
python manage.py makemigrations moderation users
python manage.py test moderation
```

Expected: PASS(迁移文件名形如 `moderation/migrations/0001_initial.py`、`users/migrations/0003_profile_ban_reason.py`)。

- [x] **Step 5: 全量回归 + commit**

```bash
python manage.py test
git add chatapp/moderation chatapp/users
git commit -m "feat: moderation models (Report/Block/BanLog) + Profile.ban_reason (M3)"
```

---

### Task 2: 重封禁全域 403(全局权限类)

**Files:**
- Create: `chatapp/moderation/permissions.py`
- Modify: `chatapp/config/settings.py:152-154`(DEFAULT_PERMISSION_CLASSES)
- Modify: `chatapp/im/views.py`(删掉重复的 heavy 检查)
- Modify: `chatapp/users/serializers.py:41-52`(ProfileSerializer 暴露 ban_reason)
- Test: `chatapp/moderation/tests.py`

**Interfaces:**
- Consumes: `ProfileStatus`(users.models)、`get_profile`(users.services)
- Produces: `moderation.permissions.IsNotHeavyBanned`;`GET /users/me` 响应新增 `ban_reason` 字段(前端封禁页用)。Task 16 依赖。

- [x] **Step 1: 写权限测试(先让它失败)**

在 `chatapp/moderation/tests.py` 追加:

```python
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from users.models import Photo, PhotoStatus, Profile, ProfileStatus


class IsNotHeavyBannedTests(APITestCase):
    """重封禁 = 全业务 403;白名单(看自己资料/标签池)放行;轻封禁不受影响。"""

    def setUp(self):
        self.me = User.objects.create_user(phone="13800138000")
        Profile.objects.create(user=self.me, nickname="我", gender="male", birthday="2000-01-01",
                               city="上海", bio="你好", status=ProfileStatus.COMPLETE)
        Photo.objects.create(user=self.me, file="photos/x.png", status=PhotoStatus.APPROVED)
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.me).access_token}")

    def _ban(self, status):
        Profile.objects.filter(user=self.me).update(status=status)

    def test_heavy_banned_blocked_across_business_endpoints(self):
        self._ban(ProfileStatus.BANNED_HEAVY)
        for method, url in [
            ("get", "/api/v1/discovery/candidates"),
            ("get", "/api/v1/matches"),
            ("post", "/api/v1/discovery/swipe"),
            ("post", "/api/v1/users/me/photos"),
            ("patch", "/api/v1/users/me/preference"),
        ]:
            resp = getattr(self.client, method)(url)
            self.assertEqual(resp.status_code, 403, msg=f"{method} {url} 应 403")
            self.assertEqual(resp.json()["message"], "账号已被封禁,如有疑问请联系客服")

    def test_heavy_banned_can_still_read_own_profile_and_tags(self):
        self._ban(ProfileStatus.BANNED_HEAVY)
        self.assertEqual(self.client.get("/api/v1/users/me").status_code, 200)
        self.assertEqual(self.client.get("/api/v1/users/tags").status_code, 200)

    def test_heavy_banned_cannot_patch_own_profile(self):
        self._ban(ProfileStatus.BANNED_HEAVY)
        resp = self.client.patch("/api/v1/users/me", {"city": "北京"}, format="json")
        self.assertEqual(resp.status_code, 403)

    def test_light_banned_only_swipe_blocked(self):
        self._ban(ProfileStatus.BANNED_LIGHT)
        self.assertEqual(self.client.get("/api/v1/discovery/candidates").status_code, 200)
        # swipe 里先过序列化器再查封禁,所以要带合法 body
        resp = self.client.post("/api/v1/discovery/swipe",
                                {"target_user_id": 999999, "action": "like"}, format="json")
        self.assertEqual(resp.status_code, 403)

    def test_me_exposes_ban_reason(self):
        Profile.objects.filter(user=self.me).update(
            status=ProfileStatus.BANNED_HEAVY, ban_reason="骚扰他人")
        data = self.client.get("/api/v1/users/me").json()
        self.assertEqual(data["status"], "banned_heavy")
        self.assertEqual(data["ban_reason"], "骚扰他人")
```

- [x] **Step 2: 跑测试确认失败**

```bash
python manage.py test moderation.tests.IsNotHeavyBannedTests
```

Expected: FAIL —— heavy 用例拿到 200/其它码(还没有全局权限类);`test_me_exposes_ban_reason` 因响应无该键 KeyError。

- [x] **Step 3: 实现权限类 + 挂载 + 序列化字段**

新建 `chatapp/moderation/permissions.py`:

```python
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission

from users.models import ProfileStatus
from users.services import get_profile

# (方法, 路径) 白名单:被封禁的人也要能读自己的资料(前端要展示封禁原因)和标签池
BAN_EXEMPT = {
    ("GET", "/api/v1/users/me"),
    ("GET", "/api/v1/users/tags"),
}


class IsNotHeavyBanned(BasePermission):
    """重封禁 → 全部业务接口 403;轻封禁只管滑卡(swipe 视图里另有检查)。"""

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return True   # 登录/验证码/刷新 token 等 AllowAny 接口不归这里管
        if (request.method, request.path) in BAN_EXEMPT:
            return True
        if get_profile(request.user).status == ProfileStatus.BANNED_HEAVY:
            raise PermissionDenied("账号已被封禁,如有疑问请联系客服")
        return True
```

`chatapp/config/settings.py` 的 REST_FRAMEWORK 里:

```python
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
        "moderation.permissions.IsNotHeavyBanned",
    ),
```

`chatapp/im/views.py` 删掉 heavy 检查(全局类已覆盖),改为:

```python
@api_view(["POST"])
def user_sig(request):
    return Response({
        "user_sig": gen_user_sig(request.user.im_user_id),
        "sdkappid": settings.IM_SDKAPPID,
        "im_user_id": request.user.im_user_id,
        "expire": settings.IM_SIG_EXPIRE,
    })
```

同时删掉该文件里不再使用的 import(`PermissionDenied`、`ProfileStatus`、`get_profile`)。

`chatapp/users/serializers.py` 的 `ProfileSerializer.Meta.fields` 加 `"ban_reason"`(放在 `"status"` 后):

```python
        fields = ["id", "phone", "nickname", "gender", "birthday", "age", "city", "bio",
                  "status", "ban_reason", "missing_fields", "tags", "photos", "preference"]
```

- [x] **Step 4: 跑测试确认通过 + 回归**

```bash
python manage.py test moderation.tests.IsNotHeavyBannedTests
python manage.py test
```

Expected: PASS(注意 `im/tests.py::test_heavy_banned_rejected` 仍应通过——现在由全局权限类拦下)。

- [x] **Step 5: Commit**

```bash
git add chatapp/moderation/permissions.py chatapp/config/settings.py chatapp/im/views.py chatapp/users/serializers.py chatapp/moderation/tests.py
git commit -m "feat: global heavy-ban permission with read-only whitelist (M3)"
```

### Task 3: 封禁审计服务 + admin 封禁操作 + IM 踢下线

**Files:**
- Create: `chatapp/moderation/services.py`
- Modify: `chatapp/im/client.py`(加 `kick_user`)
- Modify: `chatapp/users/admin.py`(ProfileAdmin 加 ban_reason 列 + save_model 钩子)
- Test: `chatapp/moderation/tests.py`、`chatapp/im/tests.py`

**Interfaces:**
- Produces: `moderation.services.log_ban_change(user, old_status, new_status, reason, operator)`、`_dispatch_async(fn, *args)`(后续 Task 7 的 `sync_im_blacklist` 和测试 patch 都依赖这个名字)、`moderation.services.blocked_user_ids(user) -> set[int]`(Task 8 用);`im.client.kick_user(identifier) -> bool`。Task 6/7/8 依赖。

- [x] **Step 1: 写服务与 kick 测试(先让它失败)**

`chatapp/moderation/tests.py` 追加:

```python
from unittest.mock import patch

from im import client as im_client

from .services import log_ban_change


class BanAuditServiceTests(TestCase):
    def setUp(self):
        self.operator = User.objects.create_superuser(phone="13700137000", password="pw")
        self.target = User.objects.create_user(phone="13900139000")

    def test_heavy_ban_writes_log_and_kicks_offline(self):
        with patch("moderation.services._dispatch_async") as dispatch:
            log_ban_change(self.target, ProfileStatus.COMPLETE, ProfileStatus.BANNED_HEAVY,
                           "骚扰他人", self.operator)
        log = BanLog.objects.get(user=self.target)
        self.assertEqual(log.action, BanAction.BAN_HEAVY)
        self.assertEqual(log.reason, "骚扰他人")
        self.assertEqual(log.operator, self.operator)
        dispatch.assert_called_once_with(im_client.kick_user, self.target.im_user_id)

    def test_light_ban_writes_log_without_kick(self):
        with patch("moderation.services._dispatch_async") as dispatch:
            log_ban_change(self.target, ProfileStatus.COMPLETE, ProfileStatus.BANNED_LIGHT,
                           "轻度违规", self.operator)
        self.assertEqual(BanLog.objects.get(user=self.target).action, BanAction.BAN_LIGHT)
        dispatch.assert_not_called()

    def test_unban_writes_unban_log(self):
        log_ban_change(self.target, ProfileStatus.BANNED_HEAVY, ProfileStatus.COMPLETE,
                       "申诉通过", self.operator)
        self.assertEqual(BanLog.objects.get(user=self.target).action, BanAction.UNBAN)

    def test_non_ban_transition_writes_nothing(self):
        log_ban_change(self.target, ProfileStatus.INCOMPLETE, ProfileStatus.COMPLETE, "", self.operator)
        self.assertFalse(BanLog.objects.exists())


class ProfileAdminHookTests(TestCase):
    """admin 保存 Profile 的钩子:运营只填 状态+原因,审计自动落。"""

    def setUp(self):
        self.operator = User.objects.create_superuser(phone="13700137000", password="pw")
        self.target = User.objects.create_user(phone="13900139000")
        Profile.objects.get_or_create(user=self.target)

    def _save(self, status, reason):
        from django.contrib import admin as django_admin
        from django.test import RequestFactory

        from users.admin import ProfileAdmin

        request = RequestFactory().post("/admin/")
        request.user = self.operator
        model_admin = ProfileAdmin(Profile, django_admin.site)
        obj = Profile.objects.get(user=self.target)   # get_profile 或首次访问已懒创建
        obj.status = status
        obj.ban_reason = reason
        with patch("moderation.services._dispatch_async"):
            model_admin.save_model(request, obj, form=None, change=True)

    def test_heavy_ban_via_admin_writes_audit(self):
        self._save(ProfileStatus.BANNED_HEAVY, "骚扰他人")
        log = BanLog.objects.get(user=self.target)
        self.assertEqual(log.action, BanAction.BAN_HEAVY)
        self.assertEqual(log.operator, self.operator)

    def test_unban_via_admin_clears_nothing_but_writes_audit(self):
        Profile.objects.filter(user=self.target).update(
            status=ProfileStatus.BANNED_HEAVY, ban_reason="骚扰他人")
        self._save(ProfileStatus.COMPLETE, "")
        self.assertEqual(BanLog.objects.get(user=self.target).action, BanAction.UNBAN)
```

`chatapp/im/tests.py` 的 `ImClientTests` 里追加(kick_user 加进文件顶部 import):

```python
    def test_kick_user_payload(self):
        with patch("im.client._request", return_value={"ActionStatus": "OK", "ErrorCode": 0}) as req:
            self.assertTrue(kick_user("u5"))
        args, _ = req.call_args
        self.assertEqual(args[0], "im_open_login_svc")
        self.assertEqual(args[1], "kick")
        self.assertEqual(args[2], {"UserID": "u5"})

    def test_kick_user_network_error_returns_false(self):
        with patch("im.client._request", side_effect=Exception("boom")):
            self.assertFalse(kick_user("u5"))
```

- [x] **Step 2: 跑测试确认失败**

```bash
python manage.py test moderation.tests.BanAuditServiceTests moderation.tests.ProfileAdminHookTests im.tests.ImClientTests
```

Expected: FAIL —— `moderation/services.py` 不存在(ImportError),`kick_user` 未定义。

- [x] **Step 3: 实现服务与客户端函数**

新建 `chatapp/moderation/services.py`:

```python
import logging
import threading

from im import client as im_client
from users.models import Profile, ProfileStatus

from .models import BanAction, BanLog, Block

logger = logging.getLogger(__name__)


def blocked_user_ids(user) -> set[int]:
    """与我有拉黑关系的人(我拉黑的 ∪ 拉黑我的);候选/配对/资料卡统一用它。"""
    made = Block.objects.filter(blocker=user).values_list("blocked_id", flat=True)
    received = Block.objects.filter(blocked=user).values_list("blocker_id", flat=True)
    return set(made) | set(received)


def log_ban_change(user, old_status, new_status, reason, operator) -> None:
    """admin 保存 Profile 时调用:状态跨封禁边界就写审计;重封禁顺带踢下线。"""
    if new_status == old_status:
        return
    if new_status == ProfileStatus.BANNED_LIGHT:
        _write_log(user, BanAction.BAN_LIGHT, reason, operator)
    elif new_status == ProfileStatus.BANNED_HEAVY:
        _write_log(user, BanAction.BAN_HEAVY, reason, operator)
        _dispatch_async(im_client.kick_user, user.im_user_id)
    elif old_status in Profile.BANNED_STATUSES:
        _write_log(user, BanAction.UNBAN, reason, operator)


def sync_im_blacklist(blocker, blocked, *, add: bool) -> None:
    """拉黑/解除后同步 IM 黑名单(后台线程,失败只记日志;UI 侧还有双向不可见兜底)。"""
    fn = im_client.black_list_add if add else im_client.black_list_delete
    _dispatch_async(fn, blocker.im_user_id, blocked.im_user_id)


def _write_log(user, action, reason, operator) -> None:
    try:
        BanLog.objects.create(user=user, action=action, reason=reason or "", operator=operator)
    except Exception:
        # 审计写失败不该炸掉运营的保存动作(Profile 已经保存过了)
        logger.exception("写 BanLog 失败 user=%s action=%s", user.pk, action)


def _dispatch_async(fn, *args) -> None:
    """IM 调用一律丢后台线程:接口响应不等腾讯 REST(同配对灰条 _notify_async 模式)。"""
    threading.Thread(target=fn, args=args, daemon=True).start()
```

`chatapp/im/client.py` 末尾追加:

```python
def kick_user(identifier: str) -> bool:
    """把账号的在线 IM 会话踢下线(重封禁用;不然已有 userSig 最长 7 天还能聊)。"""
    try:
        result = _request("im_open_login_svc", "kick", {"UserID": identifier})
    except Exception:
        logger.exception("IM kick 调用失败 identifier=%s", identifier)
        return False
    return _check(result, "kick")
```

`chatapp/users/admin.py`:引入审计钩子并把 ProfileAdmin 改成:

```python
from moderation.services import log_ban_change


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "nickname", "gender", "city", "status", "ban_reason")
    list_filter = ("status", "gender")
    search_fields = ("nickname", "user__phone")

    def save_model(self, request, obj, form, change):
        old_status = None
        if change:
            old_status = (Profile.objects.filter(pk=obj.pk)
                          .values_list("status", flat=True).first())
        super().save_model(request, obj, form, change)
        log_ban_change(obj.user, old_status, obj.status, obj.ban_reason, request.user)
```

- [x] **Step 4: 跑测试确认通过 + 回归**

```bash
python manage.py test moderation.tests.BanAuditServiceTests moderation.tests.ProfileAdminHookTests im.tests
python manage.py test
```

Expected: PASS。⚠️ 若日志里出现 `IM kick 调用失败` 之类字样说明有用例真打了腾讯云,回去补 mock。

- [x] **Step 5: Commit**

```bash
git add chatapp/moderation/services.py chatapp/im/client.py chatapp/im/tests.py chatapp/users/admin.py chatapp/moderation/tests.py
git commit -m "feat: ban audit hook + admin ban flow + IM kick (M3)"
```

---

### Task 4: 照片审核台(预览 + 批量通过/驳回)

**Files:**
- Modify: `chatapp/users/admin.py`(PhotoAdmin)
- Test: `chatapp/users/tests.py`(文件顶部补 import,末尾追加测试类)

**Interfaces:**
- Consumes: `Profile.refresh_status()`(M1 已有;封禁状态不会被覆盖)
- Produces: admin 动作名 `approve_photos` / `reject_photos`(审核台按名字调用,手测清单会用到)

- [x] **Step 1: 写测试(先让它失败)**

`chatapp/users/tests.py` 顶部 import 区加 `from django.contrib.auth import get_user_model` 已有,再在文件末尾追加:

```python
class PhotoAdminActionTests(TestCase):
    """审核台批量动作:改照片状态,并重算用户的「资料完善」状态。"""

    def setUp(self):
        self.staff = User.objects.create_superuser(phone="13700137000", password="pw")
        self.user = User.objects.create_user(phone="13900139000")
        self.profile = Profile.objects.create(
            user=self.user, nickname="小红", gender="female", birthday="2000-01-01",
            city="上海", bio="你好", status=ProfileStatus.COMPLETE)
        self.photo = Photo.objects.create(user=self.user, file="photos/x.png",
                                          status=PhotoStatus.APPROVED)
        self.client.force_login(self.staff)

    def _run_action(self, action, *photos):
        return self.client.post("/admin/users/photo/", {
            "action": action,
            "_selected_action": [p.pk for p in photos],
        })

    def test_reject_action_marks_photo_and_profile_incomplete(self):
        resp = self._run_action("reject_photos", self.photo)
        self.assertEqual(resp.status_code, 302)
        self.photo.refresh_from_db()
        self.profile.refresh_from_db()
        self.assertEqual(self.photo.status, PhotoStatus.REJECTED)
        self.assertEqual(self.profile.status, ProfileStatus.INCOMPLETE)

    def test_approve_action_completes_profile_again(self):
        Photo.objects.filter(pk=self.photo.pk).update(status=PhotoStatus.PENDING)
        Profile.objects.filter(pk=self.profile.pk).update(status=ProfileStatus.INCOMPLETE)
        self._run_action("approve_photos", self.photo)
        self.photo.refresh_from_db()
        self.profile.refresh_from_db()
        self.assertEqual(self.photo.status, PhotoStatus.APPROVED)
        self.assertEqual(self.profile.status, ProfileStatus.COMPLETE)
```

- [x] **Step 2: 跑测试确认失败**

```bash
python manage.py test users.tests.PhotoAdminActionTests
```

Expected: FAIL —— 动作 `reject_photos` 不存在(admin 返回 200 重渲染并提示 invalid action,断言 302 失败)。

- [x] **Step 3: 实现 PhotoAdmin**

`chatapp/users/admin.py`:`from django.utils.html import format_html` 加到 import 区,PhotoAdmin 替换为:

```python
@admin.action(description="通过所选照片")
def approve_photos(modeladmin, request, queryset):
    _review_photos(modeladmin, request, queryset, PhotoStatus.APPROVED)


@admin.action(description="驳回所选照片")
def reject_photos(modeladmin, request, queryset):
    _review_photos(modeladmin, request, queryset, PhotoStatus.REJECTED)


def _review_photos(modeladmin, request, queryset, status):
    user_ids = set(queryset.values_list("user_id", flat=True))
    count = queryset.count()
    queryset.update(status=status)
    # 照片数量变化会影响「资料完善」判定(掉回未完善 = 失去候选资格),必须重算
    for profile in Profile.objects.filter(user_id__in=user_ids):
        profile.refresh_status()
    modeladmin.message_user(request, f"已处理 {count} 张照片")


@admin.register(Photo)
class PhotoAdmin(admin.ModelAdmin):
    list_display = ("id", "preview", "user", "status", "order", "created_at")
    list_filter = ("status",)
    actions = [approve_photos, reject_photos]

    @admin.display(description="预览")
    def preview(self, obj):
        if not obj.file:
            return "-"
        return format_html('<img src="{}" style="height:60px;border-radius:4px">', obj.file.url)
```

- [x] **Step 4: 跑测试确认通过 + 回归**

```bash
python manage.py test users.tests.PhotoAdminActionTests
python manage.py test
```

Expected: PASS(全量测试里 `ProfileModelTests.test_refresh_status_does_not_override_ban` 仍绿)。

- [x] **Step 5: Commit**

```bash
git add chatapp/users/admin.py chatapp/users/tests.py
git commit -m "feat: photo review console in admin (M3)"
```

---

### Task 5: 举报队列 admin + Block/BanLog 只读对账页

**Files:**
- Modify: `chatapp/moderation/admin.py`(当前是空壳)
- Test: `chatapp/moderation/tests.py`

**Interfaces:**
- Consumes: Task 1 的模型;`ReportStatus`、`timezone.now()`
- Produces: 审核台页面(手测清单用);`ReportAdmin.save_model` 自动补 `handled_at/handled_by`

- [x] **Step 1: 写测试(先让它失败)**

`chatapp/moderation/tests.py` 追加:

```python
class ReportAdminTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_superuser(phone="13700137000", password="pw")
        self.reporter = User.objects.create_user(phone="13800138000")
        self.target = User.objects.create_user(phone="13900139000")
        self.report = Report.objects.create(reporter=self.reporter, target=self.target,
                                            type=ReportType.HARASSMENT, detail="发骚扰消息")

    def test_handling_report_fills_handler_and_time(self):
        from django.contrib import admin as django_admin
        from django.test import RequestFactory

        from .admin import ReportAdmin

        request = RequestFactory().post("/admin/")
        request.user = self.staff
        model_admin = ReportAdmin(Report, django_admin.site)
        obj = Report.objects.get(pk=self.report.pk)
        obj.status = ReportStatus.HANDLED
        obj.handled_note = "已警告"
        model_admin.save_model(request, obj, form=None, change=True)
        obj.refresh_from_db()
        self.assertEqual(obj.handled_by, self.staff)
        self.assertIsNotNone(obj.handled_at)
        self.assertEqual(obj.handled_note, "已警告")

    def test_block_and_banlog_admins_are_readonly(self):
        from django.contrib import admin as django_admin
        from django.test import RequestFactory

        from .admin import BanLogAdmin, BlockAdmin

        request = RequestFactory().get("/admin/")
        request.user = self.staff
        for model, admin_cls in [(Block, BlockAdmin), (BanLog, BanLogAdmin)]:
            model_admin = admin_cls(model, django_admin.site)
            self.assertFalse(model_admin.has_add_permission(request))
            self.assertFalse(model_admin.has_change_permission(request))
            self.assertFalse(model_admin.has_delete_permission(request))
```

- [x] **Step 2: 跑测试确认失败**

```bash
python manage.py test moderation.tests.ReportAdminTests
```

Expected: FAIL —— `moderation/admin.py` 里没有 `ReportAdmin`。

- [x] **Step 3: 实现 admin**

`chatapp/moderation/admin.py` 全文替换:

```python
from django.contrib import admin
from django.utils import timezone

from .models import BanLog, Block, Report, ReportStatus


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("id", "type", "status", "reporter", "target", "created_at", "handled_by")
    list_filter = ("status", "type")
    search_fields = ("reporter__phone", "target__phone", "detail")
    readonly_fields = ("created_at", "handled_at", "handled_by")
    # 倒序排:字符串降序让 "pending" 排在 "handled" 前面,打开就是待办
    ordering = ("-status", "-created_at")

    def save_model(self, request, obj, form, change):
        if obj.status == ReportStatus.HANDLED and obj.handled_at is None:
            obj.handled_at = timezone.now()
            obj.handled_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(Block)
class BlockAdmin(admin.ModelAdmin):
    """只读对账页:拉黑必须走 App 接口(要同步 IM),手工加会漏。"""

    list_display = ("id", "blocker", "blocked", "created_at")
    search_fields = ("blocker__phone", "blocked__phone")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(BanLog)
class BanLogAdmin(admin.ModelAdmin):
    """只读审计页:只增不改。"""

    list_display = ("id", "user", "action", "reason", "operator", "created_at")
    list_filter = ("action",)
    search_fields = ("user__phone",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
```

- [x] **Step 4: 跑测试确认通过 + 回归**

```bash
python manage.py test moderation
python manage.py test
```

Expected: PASS。

- [x] **Step 5: Commit**

```bash
git add chatapp/moderation/admin.py chatapp/moderation/tests.py
git commit -m "feat: report queue + readonly audit admins (M3)"
```

## 批次 2:举报/拉黑接口 + 可见性联动(后端)

### Task 6: 举报接口(幂等 + 限流)

**Files:**
- Create: `chatapp/moderation/serializers.py`、`chatapp/moderation/throttles.py`、`chatapp/moderation/views.py`、`chatapp/moderation/urls.py`
- Modify: `chatapp/config/api_urls.py`、`chatapp/config/settings.py:156`(限流额度)
- Test: `chatapp/moderation/tests.py`(顶部 import 区补 `from django.core.cache import cache`)

**Interfaces:**
- Produces: `POST /api/v1/reports` → 新建 201 / 已有待处理举报 200,响应 `{id, type, status}`;`ReportCreateSerializer`、`ReportSerializer`、`ReportThrottle`(Task 7 在同一批文件里继续加)。

- [x] **Step 1: 写测试(先让它失败)**

`chatapp/moderation/tests.py` 追加:

```python
from django.core.cache import cache   # 记得合并进文件顶部 import 区


class ReportApiTests(APITestCase):
    URL = "/api/v1/reports"

    def setUp(self):
        cache.clear()               # 限流计数在缓存里,用例之间必须清
        self.addCleanup(cache.clear)
        self.me = User.objects.create_user(phone="13800138000")
        self.target = User.objects.create_user(phone="13900139000")
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.me).access_token}")

    def report(self, target_id=None, type_="harassment", detail=""):
        return self.client.post(self.URL, {
            "target_user_id": self.target.id if target_id is None else target_id,
            "type": type_,
            "detail": detail,
        }, format="json")

    def test_creates_pending_report(self):
        resp = self.report(detail="一直发骚扰消息")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["status"], "pending")
        report = Report.objects.get()
        self.assertEqual((report.reporter, report.target), (self.me, self.target))
        self.assertEqual(report.detail, "一直发骚扰消息")

    def test_duplicate_pending_report_is_idempotent(self):
        first = self.report()
        second = self.report(type_="fraud")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["id"], first.json()["id"])
        self.assertEqual(Report.objects.count(), 1)

    def test_new_report_after_previous_handled(self):
        Report.objects.create(reporter=self.me, target=self.target, type="harassment",
                              status=ReportStatus.HANDLED)
        self.assertEqual(self.report().status_code, 201)
        self.assertEqual(Report.objects.count(), 2)

    def test_cannot_report_self(self):
        self.assertEqual(self.report(target_id=self.me.id).status_code, 400)

    def test_unknown_target_returns_404(self):
        self.assertEqual(self.report(target_id=999999).status_code, 404)

    def test_invalid_type_rejected(self):
        self.assertEqual(self.report(type_="spam").status_code, 400)

    def test_requires_auth(self):
        self.client.credentials()
        self.assertEqual(self.report().status_code, 401)

    def test_report_throttled(self):
        from .throttles import ReportThrottle

        other = User.objects.create_user(phone="13900139001")
        with patch.object(ReportThrottle, "rate", "2/day", create=True):
            self.assertEqual(self.report(target_id=other.id).status_code, 201)
            self.assertEqual(self.report().status_code, 201)
            self.assertEqual(self.report(type_="fraud").status_code, 429)
```

- [x] **Step 2: 跑测试确认失败**

```bash
python manage.py test moderation.tests.ReportApiTests
```

Expected: FAIL —— `/api/v1/reports` 路由不存在(404)。

- [x] **Step 3: 实现序列化器/限流/视图/路由**

新建 `chatapp/moderation/serializers.py`:

```python
from rest_framework import serializers

from .models import Report, ReportType


class ReportCreateSerializer(serializers.Serializer):
    target_user_id = serializers.IntegerField()
    type = serializers.ChoiceField(choices=ReportType.choices)
    detail = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


class ReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = Report
        fields = ["id", "type", "status"]
```

新建 `chatapp/moderation/throttles.py`:

```python
from rest_framework.throttling import SimpleRateThrottle


class ReportThrottle(SimpleRateThrottle):
    """按用户限流举报;额度在 settings.DEFAULT_THROTTLE_RATES["report"]。"""

    scope = "report"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": request.user.id}
```

新建 `chatapp/moderation/views.py`:

```python
from django.contrib.auth import get_user_model
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.exceptions import ValidationError
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response

from .models import Report, ReportStatus
from .serializers import ReportCreateSerializer, ReportSerializer
from .throttles import ReportThrottle

User = get_user_model()


@api_view(["POST"])
@throttle_classes([ReportThrottle])
def create_report(request):
    serializer = ReportCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    if data["target_user_id"] == request.user.id:
        raise ValidationError("不能举报自己")
    target = get_object_or_404(User, id=data["target_user_id"])
    # 幂等:同一对象已有未处理举报就不重复建,直接返回已有记录
    report, created = Report.objects.get_or_create(
        reporter=request.user, target=target, status=ReportStatus.PENDING,
        defaults={"type": data["type"], "detail": data["detail"]},
    )
    return Response(ReportSerializer(report).data, status=201 if created else 200)
```

新建 `chatapp/moderation/urls.py`:

```python
from django.urls import path

from . import views

urlpatterns = [
    path("reports", views.create_report),
]
```

`chatapp/config/api_urls.py` 加一行(moderation 没有统一前缀,路径写在它自己的 urls 里):

```python
    path("", include("moderation.urls")),
```

`chatapp/config/settings.py` 的 `DEFAULT_THROTTLE_RATES`:

```python
    "DEFAULT_THROTTLE_RATES": {"sms_send": "20/hour", "swipe": "300/hour", "report": "20/day"},
```

- [x] **Step 4: 跑测试确认通过 + 回归**

```bash
python manage.py test moderation.tests.ReportApiTests
python manage.py test
```

Expected: PASS。

- [x] **Step 5: Commit**

```bash
git add chatapp/moderation chatapp/config
git commit -m "feat: report API with idempotency and throttle (M3)"
```

---

### Task 7: 拉黑接口 + IM 黑名单同步

**Files:**
- Modify: `chatapp/moderation/serializers.py`(+Block 序列化器)
- Modify: `chatapp/moderation/views.py`(+blocks / unblock)
- Modify: `chatapp/moderation/urls.py`(+两条路由)
- Modify: `chatapp/im/client.py`(+black_list_add / black_list_delete)
- Test: `chatapp/moderation/tests.py`、`chatapp/im/tests.py`(import 区补 `black_list_add, black_list_delete`)

**Interfaces:**
- Consumes: `moderation.services.sync_im_blacklist(blocker, blocked, *, add)`(Task 3)、`im.client.black_list_add/delete(owner, other)`
- Produces: `POST /api/v1/blocks`(201/200)、`GET /api/v1/blocks`(列表 `[{user_id, nickname, avatar_url, blocked_at}]`)、`DELETE /api/v1/blocks/{user_id}`(204);`BlockSerializer`

- [x] **Step 1: 写测试(先让它失败)**

`chatapp/moderation/tests.py` 追加(顶部 import 区补 `from users.models import Photo, PhotoStatus, Profile, ProfileStatus` 与 `from im import client as im_client`、`from .models import Block`):

```python
class BlockApiTests(APITestCase):
    URL = "/api/v1/blocks"

    def setUp(self):
        self.me = User.objects.create_user(phone="13800138000")
        self.target = User.objects.create_user(phone="13900139000")
        Profile.objects.create(user=self.target, nickname="小红", gender="female",
                               birthday="2000-01-01", city="上海", bio="你好",
                               status=ProfileStatus.COMPLETE)
        Photo.objects.create(user=self.target, file="photos/x.png", status=PhotoStatus.APPROVED)
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.me).access_token}")

    def test_block_creates_row_and_syncs_im(self):
        with patch("moderation.services._dispatch_async") as dispatch:
            resp = self.client.post(self.URL, {"target_user_id": self.target.id}, format="json")
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(Block.objects.filter(blocker=self.me, blocked=self.target).exists())
        dispatch.assert_called_once_with(im_client.black_list_add,
                                         self.me.im_user_id, self.target.im_user_id)

    def test_duplicate_block_idempotent_without_resync(self):
        Block.objects.create(blocker=self.me, blocked=self.target)
        with patch("moderation.services._dispatch_async") as dispatch:
            resp = self.client.post(self.URL, {"target_user_id": self.target.id}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Block.objects.count(), 1)
        dispatch.assert_not_called()

    def test_cannot_block_self(self):
        resp = self.client.post(self.URL, {"target_user_id": self.me.id}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_unknown_target_returns_404(self):
        resp = self.client.post(self.URL, {"target_user_id": 999999}, format="json")
        self.assertEqual(resp.status_code, 404)

    def test_list_shows_nickname_and_avatar(self):
        Block.objects.create(blocker=self.me, blocked=self.target)
        data = self.client.get(self.URL).json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["user_id"], self.target.id)
        self.assertEqual(data[0]["nickname"], "小红")
        self.assertTrue(data[0]["avatar_url"].startswith("http://testserver/media/"))

    def test_list_avatar_null_without_approved_photo(self):
        Photo.objects.update(status=PhotoStatus.PENDING)
        Block.objects.create(blocker=self.me, blocked=self.target)
        self.assertIsNone(self.client.get(self.URL).json()[0]["avatar_url"])

    def test_unblock_removes_and_syncs_im(self):
        Block.objects.create(blocker=self.me, blocked=self.target)
        with patch("moderation.services._dispatch_async") as dispatch:
            resp = self.client.delete(f"{self.URL}/{self.target.id}")
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(Block.objects.exists())
        dispatch.assert_called_once_with(im_client.black_list_delete,
                                         self.me.im_user_id, self.target.im_user_id)

    def test_unblock_missing_is_idempotent(self):
        with patch("moderation.services._dispatch_async") as dispatch:
            resp = self.client.delete(f"{self.URL}/{self.target.id}")
        self.assertEqual(resp.status_code, 204)
        dispatch.assert_not_called()

    def test_requires_auth(self):
        self.client.credentials()
        self.assertEqual(self.client.get(self.URL).status_code, 401)
```

`chatapp/im/tests.py` 的 `ImClientTests` 追加:

```python
    def test_black_list_add_payload(self):
        with patch("im.client._request", return_value={"ErrorCode": 0}) as req:
            self.assertTrue(black_list_add("u1", "u2"))
        args, _ = req.call_args
        self.assertEqual(args[0], "sns")
        self.assertEqual(args[1], "black_list_add")
        self.assertEqual(args[2], {"From_Account": "u1", "To_Account": ["u2"]})

    def test_black_list_delete_payload(self):
        with patch("im.client._request", return_value={"ErrorCode": 0}) as req:
            self.assertTrue(black_list_delete("u1", "u2"))
        args, _ = req.call_args
        self.assertEqual(args[1], "black_list_delete")

    def test_black_list_error_returns_false(self):
        with patch("im.client._request", side_effect=Exception("boom")):
            self.assertFalse(black_list_add("u1", "u2"))
```

- [x] **Step 2: 跑测试确认失败**

```bash
python manage.py test moderation.tests.BlockApiTests im.tests.ImClientTests
```

Expected: FAIL —— 路由 404、`black_list_add` 未定义。

- [x] **Step 3: 实现**

`chatapp/moderation/serializers.py` 追加(import 区补 `from users.models import PhotoStatus`、`from .models import Block`):

```python
class BlockCreateSerializer(serializers.Serializer):
    target_user_id = serializers.IntegerField()


class BlockSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(source="blocked.id", read_only=True)
    blocked_at = serializers.DateTimeField(source="created_at", read_only=True)
    nickname = serializers.SerializerMethodField()
    avatar_url = serializers.SerializerMethodField()

    class Meta:
        model = Block
        fields = ["user_id", "nickname", "avatar_url", "blocked_at"]

    def get_nickname(self, block):
        profile = getattr(block.blocked, "profile", None)
        return profile.nickname if profile else ""

    def get_avatar_url(self, block):
        for photo in block.blocked.photos.all():
            if photo.status == PhotoStatus.APPROVED:
                return self.context["request"].build_absolute_uri(photo.file.url)
        return None
```

`chatapp/moderation/views.py` 追加(import 区补 `from .models import Block`、`from .serializers import BlockCreateSerializer, BlockSerializer`、`from .services import sync_im_blacklist`):

```python
@api_view(["GET", "POST"])
def blocks(request):
    if request.method == "POST":
        serializer = BlockCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target_id = serializer.validated_data["target_user_id"]
        if target_id == request.user.id:
            raise ValidationError("不能拉黑自己")
        target = get_object_or_404(User, id=target_id)
        block, created = Block.objects.get_or_create(blocker=request.user, blocked=target)
        if created:
            sync_im_blacklist(request.user, target, add=True)
        return Response(BlockSerializer(block, context={"request": request}).data,
                        status=201 if created else 200)

    entries = (Block.objects.filter(blocker=request.user)
               .select_related("blocked__profile").prefetch_related("blocked__photos"))
    return Response([BlockSerializer(block, context={"request": request}).data for block in entries])


@api_view(["DELETE"])
def unblock(request, user_id):
    block = Block.objects.filter(blocker=request.user, blocked_id=user_id).first()
    if block is not None:
        target = block.blocked
        block.delete()
        sync_im_blacklist(request.user, target, add=False)
    return Response(status=204)
```

`chatapp/moderation/urls.py` 追加两条:

```python
    path("blocks", views.blocks),
    path("blocks/<int:user_id>", views.unblock),
```

`chatapp/im/client.py` 追加:

```python
def black_list_add(owner_identifier: str, other_identifier: str) -> bool:
    return _black_list("black_list_add", owner_identifier, other_identifier)


def black_list_delete(owner_identifier: str, other_identifier: str) -> bool:
    return _black_list("black_list_delete", owner_identifier, other_identifier)


def _black_list(command: str, owner_identifier: str, other_identifier: str) -> bool:
    # ⚠️ identifier 语义(是否必须管理员)实施时用真凭据实测,与 sendmsg 的 60010 同类问题
    payload = {"From_Account": owner_identifier, "To_Account": [other_identifier]}
    try:
        result = _request("sns", command, payload)
    except Exception:
        logger.exception("IM %s 失败 %s -> %s", command, owner_identifier, other_identifier)
        return False
    return _check(result, command)
```

- [x] **Step 4: 跑测试确认通过 + 回归**

```bash
python manage.py test moderation.tests.BlockApiTests im.tests
python manage.py test
```

Expected: PASS。

- [x] **Step 5: 真凭据实测(设计文档 §9 的待实测点;本机 `.env` 有真 key)**

```bash
cd chatapp && python manage.py shell
```

```python
from im import client
client.black_list_add("u8", "u9")     # 期望 True
client.black_list_delete("u8", "u9")  # 期望 True
client.kick_user("u9")                # 期望 True(如 u9 不在线,允许返回失败,重点看错误码)
```

若返回 False,看日志里的腾讯错误码:若是 `60010`(identifier 必须管理员)这类问题,**不动**(当前 `_request` 默认管理员,语义正确);若是「From_Account 与 identifier 不匹配」,把 `_black_list` 改成用 `From_Account` 身份签名(参照 `send_custom_elem` 的注释),并同步改 `im/tests.py` 的断言与注释。结论记到本 Task 末尾 + CLAUDE.md。

> **实测结论(2026-09-11,真凭据)**:`black_list_add("u8","u9")` / 重复 add / `black_list_delete` / `kick_user("u9")` 四个调用**全部返回 True**。结论:**`sns/black_list_*` 与 `im_open_login_svc/kick` 用管理员 identifier 均成立**,`_request` 默认管理员语义不用改;重复 add 腾讯侧幂等。黑名单测试条目已当场删除。

- [x] **Step 6: Commit**

```bash
git add chatapp/moderation chatapp/im docs/superpowers/plans/2026-09-11-m3-compliance.md
git commit -m "feat: block/unblock API with IM blacklist sync (M3)"
```

---

### Task 8: 候选与配对的拉黑过滤(双向)

**Files:**
- Modify: `chatapp/discovery/views.py`(candidates / match_list)
- Test: `chatapp/moderation/tests.py`(加 `from discovery.models import Match`)

**Interfaces:**
- Consumes: `moderation.services.blocked_user_ids(user) -> set[int]`(Task 3)
- Produces: 候选卡片与 `GET /matches` 都排除「我拉黑的 ∪ 拉黑我的」;Swipe/Match 数据不删(解除后自动恢复)

- [x] **Step 1: 写测试(先让它失败)**

`chatapp/moderation/tests.py` 追加:

```python
class BlockVisibilityTests(APITestCase):
    """拉黑双向不可见:候选/配对统一过滤;已有 Match 记录不删(解除后恢复)。"""

    def setUp(self):
        self.me = self._make_user("13800138000")
        self.other = self._make_user("13900139000")
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.me).access_token}")

    def _make_user(self, phone):
        user = User.objects.create_user(phone=phone)
        Profile.objects.create(user=user, nickname=phone, gender="female", birthday="2000-01-01",
                               city="上海", bio="你好", status=ProfileStatus.COMPLETE)
        Photo.objects.create(user=user, file="photos/x.png", status=PhotoStatus.APPROVED)
        return user

    def test_candidates_exclude_blocked_by_me(self):
        Block.objects.create(blocker=self.me, blocked=self.other)
        self.assertEqual(self.client.get("/api/v1/discovery/candidates").json(), [])

    def test_candidates_exclude_people_who_blocked_me(self):
        Block.objects.create(blocker=self.other, blocked=self.me)
        self.assertEqual(self.client.get("/api/v1/discovery/candidates").json(), [])

    def test_matches_exclude_blocked_pair(self):
        Match.objects.create(**Match.pair_kwargs(self.me, self.other))
        self.assertEqual(len(self.client.get("/api/v1/matches").json()), 1)
        Block.objects.create(blocker=self.other, blocked=self.me)
        self.assertEqual(self.client.get("/api/v1/matches").json(), [])

    def test_removing_block_restores_visibility(self):
        Block.objects.create(blocker=self.me, blocked=self.other).delete()
        self.assertEqual(len(self.client.get("/api/v1/discovery/candidates").json()), 1)
```

- [x] **Step 2: 跑测试确认失败**

```bash
python manage.py test moderation.tests.BlockVisibilityTests
```

Expected: FAIL —— 拉黑后候选里还能看到对方。

- [x] **Step 3: 实现过滤**

`chatapp/discovery/views.py`:`from moderation.services import blocked_user_ids` 加到 import 区;`candidates` 里 `qs = (...)` 追加一行 `.exclude(user_id__in=list(blocked_ids))`,即:

```python
    blocked_ids = blocked_user_ids(me)
    with_photos = Photo.objects.filter(status=PhotoStatus.APPROVED).values("user_id")
    qs = (Profile.objects.filter(status=ProfileStatus.COMPLETE, user_id__in=with_photos)
          .exclude(user_id=me.id)
          .exclude(user_id__in=list(swiped_ids))
          .exclude(user_id__in=matched_ids)
          .exclude(user_id__in=list(blocked_ids)))
```

`match_list` 同样过滤:

```python
    blocked_ids = blocked_user_ids(me)
    matches = (Match.objects.filter(Q(user_a=me) | Q(user_b=me))
               .exclude(Q(user_a_id__in=blocked_ids) | Q(user_b_id__in=blocked_ids))
               .select_related("user_a__profile", "user_b__profile")
               .prefetch_related("user_a__photos", "user_b__photos"))
```

- [x] **Step 4: 跑测试确认通过 + 回归**

```bash
python manage.py test moderation.tests.BlockVisibilityTests
python manage.py test discovery
python manage.py test
```

Expected: PASS(discovery 原有用例不受影响——没有任何 Block 数据时结果不变)。

- [x] **Step 5: Commit**

```bash
git add chatapp/discovery/views.py chatapp/moderation/tests.py
git commit -m "feat: hide blocked users from candidates and matches (M3)"
```

---

### Task 9: 公开资料卡接口 GET /users/{id}

**Files:**
- Modify: `chatapp/users/serializers.py`(+PublicProfileSerializer)
- Modify: `chatapp/users/views.py`(+public_profile)
- Modify: `chatapp/users/urls.py`(+路由)
- Test: `chatapp/users/tests.py`(顶部补 `from moderation.models import Block`,用已有的 `AuthMixin`)

**Interfaces:**
- Consumes: `moderation.services.blocked_user_ids`
- Produces: `GET /api/v1/users/{id}` → `{user_id, nickname, gender, age, city, bio, tags, photos}`(photos 只含过审);heavy 封禁/任一方拉黑/不存在 → 404 `{"code":404,"message":"用户不存在"}`。Task 12 前端依赖此响应形状。

- [x] **Step 1: 写测试(先让它失败)**

`chatapp/users/tests.py` 末尾追加:

```python
class PublicProfileTests(AuthMixin, APITestCase):
    def setUp(self):
        self.me = User.objects.create_user(phone="13800138000")
        self.login(self.me)
        self.other = User.objects.create_user(phone="13900139000")
        Profile.objects.create(user=self.other, nickname="小红", gender="female",
                               birthday="1998-01-01", city="上海", bio="喜欢爬山",
                               status=ProfileStatus.COMPLETE)
        Photo.objects.create(user=self.other, file="photos/a.png", status=PhotoStatus.APPROVED)
        Photo.objects.create(user=self.other, file="photos/b.png", status=PhotoStatus.PENDING)

    def _get(self):
        return self.client.get(f"/api/v1/users/{self.other.id}")

    def test_returns_public_fields_only(self):
        data = self._get().json()
        self.assertEqual(data["user_id"], self.other.id)
        self.assertEqual(data["nickname"], "小红")
        self.assertEqual(data["age"], calculate_age(date(1998, 1, 1)))
        self.assertEqual(len(data["photos"]), 1)          # 只有过审那张
        for hidden in ("phone", "birthday", "preference", "missing_fields"):
            self.assertNotIn(hidden, data)

    def test_heavy_banned_target_is_invisible(self):
        Profile.objects.filter(user=self.other).update(status=ProfileStatus.BANNED_HEAVY)
        self.assertEqual(self._get().status_code, 404)

    def test_light_banned_target_still_visible(self):
        Profile.objects.filter(user=self.other).update(status=ProfileStatus.BANNED_LIGHT)
        self.assertEqual(self._get().status_code, 200)

    def test_blocked_relationship_hides_both_ways(self):
        Block.objects.create(blocker=self.me, blocked=self.other)
        self.assertEqual(self._get().status_code, 404)
        Block.objects.all().delete()
        Block.objects.create(blocker=self.other, blocked=self.me)
        self.assertEqual(self._get().status_code, 404)

    def test_unknown_user_returns_404(self):
        self.assertEqual(self.client.get("/api/v1/users/999999").status_code, 404)

    def test_requires_auth(self):
        self.client.credentials()
        self.assertEqual(self._get().status_code, 401)
```

- [x] **Step 2: 跑测试确认失败**

```bash
python manage.py test users.tests.PublicProfileTests
```

Expected: FAIL —— 路由 `/api/v1/users/9` 不存在(404,但 JSON 形状不符 / 也有 404 巧合,以 fields 用例的失败为准)。

- [x] **Step 3: 实现**

`chatapp/users/serializers.py` 追加:

```python
class PublicProfileSerializer(serializers.ModelSerializer):
    """对方资料卡:只比 ProfileSerializer 少了隐私字段(手机号/生日/偏好/缺项)。"""

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

`chatapp/users/serializers.py` 顶部 import 补 `PhotoStatus`(models 里已有)。

`chatapp/users/views.py`:import 区补

```python
from django.contrib.auth import get_user_model
from rest_framework.exceptions import NotFound

from moderation.services import blocked_user_ids
from .serializers import PublicProfileSerializer

User = get_user_model()
```

视图追加:

```python
@api_view(["GET"])
def public_profile(request, user_id):
    # 双向拉黑 = 互相不存在;heavy 封禁的人对外不可见(轻封禁仍可见,还能聊天)
    if user_id in blocked_user_ids(request.user):
        raise NotFound("用户不存在")
    target = get_object_or_404(User, id=user_id)
    profile = getattr(target, "profile", None)
    if profile is None or profile.status == ProfileStatus.BANNED_HEAVY:
        raise NotFound("用户不存在")
    return Response(PublicProfileSerializer(profile, context={"request": request}).data)
```

`chatapp/users/views.py` 顶部 import 还要补 `ProfileStatus`(`from .models import Photo, PhotoStatus, Profile, ProfileStatus, Tag`)。

`chatapp/users/urls.py` 追加(放最后,**注意要在 `tags` 之后**(静态路径先匹配,数字路径不会误吃 `tags`——`<int:user_id>` 只匹配数字,安全)):

```python
    path("<int:user_id>", views.public_profile),
```

- [x] **Step 4: 跑测试确认通过 + 回归**

```bash
python manage.py test users
python manage.py test
```

Expected: PASS。

- [x] **Step 5: Commit**

```bash
git add chatapp/users
git commit -m "feat: public user profile endpoint (M3)"
```

## 批次 3:资料卡 + 举报/拉黑前端(全栈)

### Task 10: IM 抽象层新增 deleteConversation

**Files:**
- Modify: `app/lib/im/im_client.dart`(接口)
- Modify: `app/lib/im/tencent_im_client.dart`(真实实现)
- Modify: `app/test/support/fake_im_client.dart`(假实现)

**Interfaces:**
- Produces: `ImClient.deleteConversation(String peerId)`(peerId 形如 `u9`);Fake 会记流水 `deleteConversation:u9` 并把它从 `conversations` 里移除。Task 12 的拉黑流依赖。

- [x] **Step 1: 三个文件同步加方法**

`app/lib/im/im_client.dart` 的 `ImClient` 抽象类里,`markConversationRead` 后加:

```dart
  /// 删除本机会话(拉黑后清理用;对方设备上的会话不受影响)。
  Future<void> deleteConversation(String peerId);
```

`app/lib/im/tencent_im_client.dart` 的 `TencentImClient` 里追加:

```dart
  @override
  Future<void> deleteConversation(String peerId) async {
    final result = await TencentImSDKPlugin.v2TIMManager
        .getConversationManager()
        .deleteConversation(conversationID: 'c2c_$peerId');
    _check(result.code, result.desc);
  }
```

`app/test/support/fake_im_client.dart` 里追加:

```dart
  @override
  Future<void> deleteConversation(String peerId) async {
    log.add('deleteConversation:$peerId');
    conversations = conversations.where((item) => item.peerId != peerId).toList();
  }
```

- [x] **Step 2: 验证(编译即接口测试)**

```bash
cd app && ../flutter/bin/flutter.bat analyze && ../flutter/bin/flutter.bat test
```

Expected: `analyze` 零告警(两个实现都补齐了接口);原有测试全绿。真实行为在 Task 12 的拉黑流用例里断言。

- [x] **Step 3: Commit**

```bash
git add app/lib/im app/test/support/fake_im_client.dart
git commit -m "feat(app): ImClient.deleteConversation for block flow (M3)"
```

---

### Task 11: 前端 moderation 数据层(repository + provider)

**Files:**
- Create: `app/lib/features/moderation/models.dart`、`app/lib/features/moderation/moderation_repository.dart`、`app/lib/features/moderation/moderation_controller.dart`
- Modify: `app/test/support/sample_data.dart`(+两个造数函数)
- Test: `app/test/features/moderation/moderation_repository_test.dart`

**Interfaces:**
- Consumes: `ApiClient`(`core/api_client.dart`)、`apiClientProvider`(`core/providers.dart`)、`Tag`/`Photo`(`features/profile/models.dart`)
- Produces: `UserProfile{userId,nickname,gender,age,city,bio,tags,photos}`、`BlockedUser{userId,nickname,avatarUrl,blockedAt}`;`ModerationRepository.fetchUserProfile(int)/report({targetUserId,type,detail})/block(int)/unblock(int)/fetchBlockedUsers()`;`userProfileProvider(FutureProvider.family<UserProfile,int>)`、`blockedUsersProvider`。Task 12/13 依赖。

- [x] **Step 1: 写造数 + repository 测试(先让它失败)**

`app/test/support/sample_data.dart` 末尾追加:

```dart
/// 造一份 GET /users/{id} 的公开资料;字段可覆盖。
Map<String, dynamic> publicProfileJson({
  int userId = 9,
  String nickname = '小红',
  String? gender = 'female',
  int? age = 25,
  String city = '上海',
  String bio = '喜欢爬山',
  List<Map<String, dynamic>> tags = const [],
  List<Map<String, dynamic>>? photos,
}) =>
    {
      'user_id': userId,
      'nickname': nickname,
      'gender': gender,
      'age': age,
      'city': city,
      'bio': bio,
      'tags': tags,
      'photos': photos ?? [photoJson(userId * 100)],
    };

/// 造一份 GET /blocks 里的一条。
Map<String, dynamic> blockedUserJson({
  int userId = 9,
  String nickname = '小红',
  String? avatarUrl,
}) =>
    {
      'user_id': userId,
      'nickname': nickname,
      'avatar_url': avatarUrl,
      'blocked_at': '2026-09-11T12:00:00+08:00',
    };
```

新建 `app/test/features/moderation/moderation_repository_test.dart`:

```dart
import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/api_client.dart';
import 'package:chatapp_app/features/moderation/moderation_repository.dart';

import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

void main() {
  late ScriptedAdapter adapter;
  late ModerationRepository repository;

  setUp(() {
    adapter = ScriptedAdapter({});
    final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
    repository = ModerationRepository(ApiClient(dio));
  });

  test('fetchUserProfile 解析公开资料', () async {
    adapter.routes['GET /users/9'] = (options) => ok(publicProfileJson());
    final profile = await repository.fetchUserProfile(9);
    expect(profile.nickname, '小红');
    expect(profile.age, 25);
    expect(profile.photos, hasLength(1));
  });

  test('report 发 POST /reports 带三个字段', () async {
    adapter.routes['POST /reports'] =
        (options) => ok({'id': 1, 'type': 'harassment', 'status': 'pending'}, status: 201);
    await repository.report(targetUserId: 9, type: 'harassment', detail: '骚扰');
    expect(adapter.log.last.path, '/reports');
    expect(adapter.log.last.data, {'target_user_id': 9, 'type': 'harassment', 'detail': '骚扰'});
  });

  test('block / unblock 发对应请求', () async {
    adapter.routes['POST /blocks'] = (options) => ok({'user_id': 9}, status: 201);
    adapter.routes['DELETE /blocks/9'] = (options) => ok({}, status: 204);
    await repository.block(9);
    expect(adapter.log.last.data, {'target_user_id': 9});
    await repository.unblock(9);
    expect(adapter.log.last.method, 'DELETE');
    expect(adapter.log.last.path, '/blocks/9');
  });

  test('fetchBlockedUsers 解析列表', () async {
    adapter.routes['GET /blocks'] = (options) => ok([blockedUserJson()]);
    final users = await repository.fetchBlockedUsers();
    expect(users.single.nickname, '小红');
    expect(users.single.userId, 9);
  });
}
```

- [x] **Step 2: 跑测试确认失败**

```bash
cd app && ../flutter/bin/flutter.bat test test/features/moderation
```

Expected: FAIL —— `moderation_repository.dart` 不存在(编译错误)。

- [x] **Step 3: 实现三个文件**

新建 `app/lib/features/moderation/models.dart`:

```dart
// 他人资料卡与黑名单的数据模型;字段与后端 GET /users/{id}、GET /blocks 一一对应。
import '../profile/models.dart';

class UserProfile {
  const UserProfile({
    required this.userId,
    required this.nickname,
    required this.gender,
    required this.age,
    required this.city,
    required this.bio,
    required this.tags,
    required this.photos,
  });

  factory UserProfile.fromJson(Map<String, dynamic> json) => UserProfile(
        userId: json['user_id'] as int,
        nickname: (json['nickname'] ?? '') as String,
        gender: json['gender'] as String?,
        age: json['age'] as int?,
        city: (json['city'] ?? '') as String,
        bio: (json['bio'] ?? '') as String,
        tags: ((json['tags'] ?? const []) as List<dynamic>)
            .map((item) => Tag.fromJson(item as Map<String, dynamic>))
            .toList(),
        photos: ((json['photos'] ?? const []) as List<dynamic>)
            .map((item) => Photo.fromJson(item as Map<String, dynamic>))
            .toList(),
      );

  final int userId;
  final String nickname;
  final String? gender;
  final int? age;
  final String city;
  final String bio;
  final List<Tag> tags;
  final List<Photo> photos;
}

class BlockedUser {
  const BlockedUser({required this.userId, required this.nickname, this.avatarUrl, this.blockedAt});

  factory BlockedUser.fromJson(Map<String, dynamic> json) => BlockedUser(
        userId: json['user_id'] as int,
        nickname: (json['nickname'] ?? '') as String,
        avatarUrl: json['avatar_url'] as String?,
        blockedAt:
            json['blocked_at'] == null ? null : DateTime.tryParse(json['blocked_at'] as String),
      );

  final int userId;
  final String nickname;
  final String? avatarUrl;
  final DateTime? blockedAt;
}
```

新建 `app/lib/features/moderation/moderation_repository.dart`:

```dart
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import 'models.dart';

class ModerationRepository {
  ModerationRepository(this._api);

  final ApiClient _api;

  Future<UserProfile> fetchUserProfile(int userId) async =>
      UserProfile.fromJson(await _api.get('/users/$userId') as Map<String, dynamic>);

  Future<void> report({required int targetUserId, required String type, String detail = ''}) async {
    await _api.post('/reports', data: {
      'target_user_id': targetUserId,
      'type': type,
      'detail': detail,
    });
  }

  Future<void> block(int userId) async {
    await _api.post('/blocks', data: {'target_user_id': userId});
  }

  Future<void> unblock(int userId) async {
    await _api.delete('/blocks/$userId');
  }

  Future<List<BlockedUser>> fetchBlockedUsers() async {
    final data = await _api.get('/blocks') as List<dynamic>;
    return data.map((item) => BlockedUser.fromJson(item as Map<String, dynamic>)).toList();
  }
}

final moderationRepositoryProvider =
    Provider<ModerationRepository>((ref) => ModerationRepository(ref.watch(apiClientProvider)));
```

新建 `app/lib/features/moderation/moderation_controller.dart`:

```dart
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'models.dart';
import 'moderation_repository.dart';

/// 对方资料卡;404(不存在/被封禁/有拉黑关系)由页面按 ApiException 展示。
final userProfileProvider = FutureProvider.family<UserProfile, int>(
  (ref, userId) => ref.watch(moderationRepositoryProvider).fetchUserProfile(userId),
  retry: (retryCount, error) => null,   // 页面有手动「重试」,关掉自动重试免得错误态一闪而过
);

class BlockedUsersController extends AsyncNotifier<List<BlockedUser>> {
  @override
  Future<List<BlockedUser>> build() =>
      ref.watch(moderationRepositoryProvider).fetchBlockedUsers();

  Future<void> reload() async {
    state = const AsyncValue.loading();
    state = await AsyncValue.guard(
        () => ref.read(moderationRepositoryProvider).fetchBlockedUsers());
  }
}

final blockedUsersProvider =
    AsyncNotifierProvider<BlockedUsersController, List<BlockedUser>>(
  BlockedUsersController.new,
  retry: (retryCount, error) => null,
);
```

- [x] **Step 4: 跑测试确认通过**

```bash
cd app && ../flutter/bin/flutter.bat test test/features/moderation && ../flutter/bin/flutter.bat analyze
```

Expected: PASS + 零告警。

- [x] **Step 5: Commit**

```bash
git add app/lib/features/moderation app/test/features/moderation app/test/support/sample_data.dart
git commit -m "feat(app): moderation data layer for report/block (M3)"
```

---

### Task 12: 资料卡页 + 举报弹窗 + 拉黑流(含删会话)

**Files:**
- Create: `app/lib/features/moderation/widgets/report_sheet.dart`、`app/lib/features/profile/user_profile_page.dart`
- Modify: `app/lib/router.dart`(+`/users/:id`)
- Modify: `app/lib/features/chat/chat_page.dart`(标题可点进资料卡)
- Test: `app/test/features/profile/user_profile_page_test.dart`、`app/test/features/chat/chat_page_test.dart`(加用例)

**Interfaces:**
- Consumes: Task 10 的 `deleteConversation`、Task 11 的 `userProfileProvider`/`moderationRepositoryProvider`、`conversationsProvider`(chat)、`imClientProvider`(im_manager)
- Produces: 路由 `/users/:id`;组件 `ReportSheet`(弹窗返回 `({String type, String detail})?`);聊天页标题 key `chat.title`

- [x] **Step 1: 写 widget 测试(先让它失败)**

新建 `app/test/features/profile/user_profile_page_test.dart`:

```dart
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/features/profile/user_profile_page.dart';
import 'package:chatapp_app/im/im_client.dart';
import 'package:chatapp_app/im/im_manager.dart';

import '../../support/fake_im_client.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

class _LoggedInImManager extends ImManager {
  @override
  ImStatus build() => const ImLoggedIn('u3');
}

void main() {
  late ScriptedAdapter adapter;
  late FakeImClient fake;

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    adapter = ScriptedAdapter({});
    fake = FakeImClient();
    addTearDown(fake.dispose);
  });

  /// 从 '/' push 进资料卡,pop 才有得可退。
  Future<void> pumpProfile(WidgetTester tester, {int userId = 9}) async {
    final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
    final container = ProviderContainer(overrides: [
      baseDioProvider.overrideWithValue(dio),
      refreshDioProvider.overrideWithValue(dio),
      imClientProvider.overrideWithValue(fake),
      imStatusProvider.overrideWith(_LoggedInImManager.new),
    ]);
    addTearDown(container.dispose);
    final router = GoRouter(
      initialLocation: '/',
      routes: [
        GoRoute(path: '/', builder: (context, state) => const Scaffold(body: Text('首页'))),
        GoRoute(
          path: '/users/:id',
          builder: (context, state) =>
              UserProfilePage(userId: int.parse(state.pathParameters['id']!)),
        ),
      ],
    );
    await tester.pumpWidget(UncontrolledProviderScope(
      container: container,
      child: MaterialApp.router(routerConfig: router),
    ));
    await tester.pumpAndSettle();
    router.push('/users/$userId');
    await tester.pumpAndSettle();
  }

  testWidgets('渲染公开资料:昵称/年龄/城市/标签/简介/两个按钮', (tester) async {
    adapter.routes['GET /users/9'] = (options) => ok(publicProfileJson(
        nickname: '小红', age: 25, city: '上海', bio: '喜欢爬山', tags: [tagJson(1, '运动')]));
    await pumpProfile(tester);

    expect(find.text('小红 · 25 岁 · 上海'), findsOneWidget);
    expect(find.text('运动'), findsOneWidget);
    expect(find.text('喜欢爬山'), findsOneWidget);
    expect(find.byKey(const Key('user.report')), findsOneWidget);
    expect(find.byKey(const Key('user.block')), findsOneWidget);
  });

  testWidgets('404 → 「用户不存在」+ 重试按钮', (tester) async {
    adapter.routes['GET /users/9'] = (options) => jsonError(404, '用户不存在');
    await pumpProfile(tester);

    expect(find.text('用户不存在'), findsOneWidget);
    expect(find.byKey(const Key('user.retry')), findsOneWidget);
  });

  testWidgets('举报:选类型 → 提交 → POST /reports + 提示语', (tester) async {
    adapter.routes['GET /users/9'] = (options) => ok(publicProfileJson());
    adapter.routes['POST /reports'] =
        (options) => ok({'id': 1, 'type': 'harassment', 'status': 'pending'}, status: 201);
    await pumpProfile(tester);

    await tester.tap(find.byKey(const Key('user.report')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('report.type.harassment')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('report.submit')));
    await tester.pumpAndSettle();

    expect(adapter.log.lastWhere((r) => r.method == 'POST').path, '/reports');
    expect(find.text('已收到举报,我们会尽快处理'), findsOneWidget);
  });

  testWidgets('拉黑:确认 → POST /blocks + 删本机会话 + 返回上一页', (tester) async {
    adapter.routes['GET /users/9'] = (options) => ok(publicProfileJson());
    adapter.routes['POST /blocks'] = (options) => ok({'user_id': 9}, status: 201);
    fake.conversations = [const ImConversation(peerId: 'u9', unreadCount: 2)];
    await pumpProfile(tester);

    await tester.tap(find.byKey(const Key('user.block')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('user.block.confirm')));
    await tester.pumpAndSettle();

    expect(adapter.log.lastWhere((r) => r.method == 'POST').path, '/blocks');
    expect(fake.log, contains('deleteConversation:u9'));
    expect(find.text('首页'), findsOneWidget);   // 已返回上一页
    expect(find.text('已拉黑'), findsOneWidget);
  });
}
```

`app/test/features/chat/chat_page_test.dart`:把 `pumpChat` 里的 `MaterialApp(home: ChatPage(...))` 换成带路由的桥(其余用例不受影响),并新增一个用例:

```dart
  // pumpChat 内部改为:
    final router = GoRouter(
      initialLocation: '/chat/u9',
      routes: [
        GoRoute(
          path: '/chat/:peerId',
          builder: (context, state) => ChatPage(peerId: state.pathParameters['peerId']!),
        ),
        GoRoute(
          path: '/users/:id',
          builder: (context, state) => Scaffold(body: Text('资料卡:${state.pathParameters['id']}')),
        ),
      ],
    );
    await tester.pumpWidget(UncontrolledProviderScope(
      container: container,
      child: MaterialApp.router(routerConfig: router),
    ));

  // 新增用例:
  testWidgets('点标题进对方资料卡', (tester) async {
    await pumpChat(tester);

    await tester.tap(find.byKey(const Key('chat.title')));
    await tester.pumpAndSettle();

    expect(find.text('资料卡:9'), findsOneWidget);   // u9 → 用户 9
  });
```

(记得给 chat_page_test.dart 补 `import 'package:go_router/go_router.dart';`)

- [x] **Step 2: 跑测试确认失败**

```bash
cd app && ../flutter/bin/flutter.bat test test/features/profile/user_profile_page_test.dart test/features/chat/chat_page_test.dart
```

Expected: FAIL —— `user_profile_page.dart` 不存在;`chat.title` 找不到。

- [x] **Step 3: 实现**

新建 `app/lib/features/moderation/widgets/report_sheet.dart`:

```dart
import 'package:flutter/material.dart';

/// 举报类型:值与后端 ReportType 对齐。
const reportTypes = [
  ('harassment', '骚扰'),
  ('porn', '色情'),
  ('fraud', '诈骗'),
  ('other', '其他'),
];

/// 底部弹窗;提交时 pop 出 `(type, detail)`,取消 pop null。
class ReportSheet extends StatefulWidget {
  const ReportSheet({super.key});

  @override
  State<ReportSheet> createState() => _ReportSheetState();
}

class _ReportSheetState extends State<ReportSheet> {
  String? _type;
  final _detail = TextEditingController();

  @override
  void dispose() {
    _detail.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.fromLTRB(16, 16, 16, 16 + MediaQuery.viewInsetsOf(context).bottom),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('举报', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 4),
          for (final (value, label) in reportTypes)
            ListTile(
              key: Key('report.type.$value'),
              contentPadding: EdgeInsets.zero,
              title: Text(label),
              trailing: _type == value ? const Icon(Icons.check, color: Colors.pink) : null,
              onTap: () => setState(() => _type = value),
            ),
          TextField(
            key: const Key('report.detail'),
            controller: _detail,
            maxLength: 200,
            decoration: const InputDecoration(labelText: '补充说明(可选)'),
          ),
          const SizedBox(height: 8),
          SizedBox(
            width: double.infinity,
            child: FilledButton(
              key: const Key('report.submit'),
              onPressed: _type == null
                  ? null
                  : () => Navigator.pop(context, (type: _type!, detail: _detail.text.trim())),
              child: const Text('提交举报'),
            ),
          ),
        ],
      ),
    );
  }
}
```

新建 `app/lib/features/profile/user_profile_page.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_exception.dart';
import '../../im/im_manager.dart';
import '../chat/conversations_controller.dart';
import '../moderation/models.dart';
import '../moderation/moderation_controller.dart';
import '../moderation/moderation_repository.dart';
import '../moderation/widgets/report_sheet.dart';

class UserProfilePage extends ConsumerWidget {
  const UserProfilePage({super.key, required this.userId});

  final int userId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final profile = ref.watch(userProfileProvider(userId));
    return Scaffold(
      appBar: AppBar(title: const Text('资料')),
      body: profile.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (error, _) => Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(error is ApiException ? error.message : '加载失败,请重试'),
              const SizedBox(height: 12),
              FilledButton(
                key: const Key('user.retry'),
                onPressed: () => ref.invalidate(userProfileProvider(userId)),
                child: const Text('重试'),
              ),
            ],
          ),
        ),
        data: (data) => _ProfileBody(profile: data),
      ),
    );
  }
}

class _ProfileBody extends ConsumerWidget {
  const _ProfileBody({required this.profile});

  final UserProfile profile;

  void _snack(BuildContext context, String message) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _report(BuildContext context, WidgetRef ref) async {
    final result = await showModalBottomSheet<({String type, String detail})>(
      context: context,
      isScrollControlled: true,
      builder: (context) => const ReportSheet(),
    );
    if (result == null) return;
    try {
      await ref.read(moderationRepositoryProvider).report(
          targetUserId: profile.userId, type: result.type, detail: result.detail);
      if (context.mounted) _snack(context, '已收到举报,我们会尽快处理');
    } on ApiException catch (error) {
      if (context.mounted) _snack(context, error.message);
    }
  }

  Future<void> _block(BuildContext context, WidgetRef ref) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('拉黑这位用户?'),
        content: const Text('拉黑后你们将互相不可见,本机聊天记录会被清除'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('取消')),
          FilledButton(
            key: const Key('user.block.confirm'),
            onPressed: () => Navigator.pop(context, true),
            child: const Text('拉黑'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    try {
      await ref.read(moderationRepositoryProvider).block(profile.userId);
    } on ApiException catch (error) {
      if (context.mounted) _snack(context, error.message);
      return;
    }
    try {
      // 拉黑已生效,清本机会话只是收尾:失败不打断流程(对方消息已被 IM 黑名单拦)
      await ref.read(imClientProvider).deleteConversation('u${profile.userId}');
      await ref.read(conversationsProvider.notifier).reload();
    } catch (_) {}
    if (context.mounted) {
      _snack(context, '已拉黑');
      context.pop();
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return ListView(
      padding: const EdgeInsets.only(bottom: 24),
      children: [
        SizedBox(
          height: 360,
          child: profile.photos.isEmpty
              ? Container(
                  color: Colors.black12,
                  child: const Center(child: Icon(Icons.person, size: 64)))
              : PageView.builder(
                  itemCount: profile.photos.length,
                  itemBuilder: (context, index) => Image.network(
                    profile.photos[index].url,
                    fit: BoxFit.cover,
                    errorBuilder: (context, error, stack) =>
                        Container(color: Colors.black12, child: const Icon(Icons.broken_image_outlined)),
                  ),
                ),
        ),
        Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                '${profile.nickname}'
                '${profile.age == null ? '' : ' · ${profile.age} 岁'}'
                '${profile.city.isEmpty ? '' : ' · ${profile.city}'}',
                style: Theme.of(context).textTheme.titleLarge,
              ),
              if (profile.tags.isNotEmpty) ...[
                const SizedBox(height: 8),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [for (final tag in profile.tags) Chip(label: Text(tag.name))],
                ),
              ],
              if (profile.bio.isNotEmpty) ...[
                const SizedBox(height: 12),
                Text(profile.bio),
              ],
              const SizedBox(height: 24),
              Row(
                children: [
                  Expanded(
                    child: OutlinedButton(
                      key: const Key('user.report'),
                      onPressed: () => _report(context, ref),
                      child: const Text('举报'),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: OutlinedButton(
                      key: const Key('user.block'),
                      style: OutlinedButton.styleFrom(foregroundColor: Colors.red),
                      onPressed: () => _block(context, ref),
                      child: const Text('拉黑'),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ],
    );
  }
}
```

`app/lib/router.dart`:import 加 `features/profile/user_profile_page.dart`,routes 里加:

```dart
      GoRoute(
        path: '/users/:id',
        builder: (context, state) =>
            UserProfilePage(userId: int.parse(state.pathParameters['id']!)),
      ),
```

`app/lib/features/chat/chat_page.dart`:import 区补 `package:go_router/go_router.dart` 与 `../../im/im_repository.dart`;AppBar 改成:

```dart
      appBar: AppBar(
        title: InkWell(
          key: const Key('chat.title'),
          onTap: () => _openProfile(context, cache),
          child: Text(displayNameFor(cache, widget.peerId)),
        ),
      ),
```

并在 `_ChatPageState` 里加:

```dart
  void _openProfile(BuildContext context, Map<String, MatchEntry> cache) {
    // 优先用 matches 缓存里的真实 id;缓存没有(如刚被清)就按 u9 → 9 兜底
    final userId =
        cache[widget.peerId]?.userId ?? int.tryParse(widget.peerId.replaceFirst('u', ''));
    if (userId == null) return;
    context.push('/users/$userId');
  }
```

- [x] **Step 4: 跑测试确认通过 + 回归**

```bash
cd app && ../flutter/bin/flutter.bat test test/features/profile/user_profile_page_test.dart test/features/chat && ../flutter/bin/flutter.bat analyze
```

Expected: PASS + 零告警(注意:页面里的网络图片都带了 errorBuilder,符合项目约定)。

- [x] **Step 5: Commit**

```bash
git add app/lib app/test
git commit -m "feat(app): user profile card with report/block flows (M3)"
```

---

### Task 13: 黑名单管理页

**Files:**
- Create: `app/lib/features/settings/blocked_users_page.dart`
- Modify: `app/lib/features/settings/settings_page.dart`(+入口)、`app/lib/router.dart`(+`/settings/blocks`)
- Test: `app/test/features/settings/blocked_users_page_test.dart`

**Interfaces:**
- Consumes: `blockedUsersProvider` / `moderationRepositoryProvider`(Task 11)
- Produces: 路由 `/settings/blocks`;设置页「黑名单」入口

- [x] **Step 1: 写测试(先让它失败)**

新建 `app/test/features/settings/blocked_users_page_test.dart`:

```dart
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/features/settings/blocked_users_page.dart';

import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

void main() {
  late ScriptedAdapter adapter;

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    adapter = ScriptedAdapter({});
  });

  Future<void> pumpBlocked(WidgetTester tester) async {
    final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
    final container = ProviderContainer(overrides: [
      baseDioProvider.overrideWithValue(dio),
      refreshDioProvider.overrideWithValue(dio),
    ]);
    addTearDown(container.dispose);
    await tester.pumpWidget(UncontrolledProviderScope(
      container: container,
      child: const MaterialApp(home: BlockedUsersPage()),
    ));
    await tester.pumpAndSettle();
  }

  testWidgets('空态', (tester) async {
    adapter.routes['GET /blocks'] = (options) => ok([]);
    await pumpBlocked(tester);
    expect(find.text('还没有拉黑任何人'), findsOneWidget);
  });

  testWidgets('列表 + 解除拉黑', (tester) async {
    // 可变列表:解除后 reload 能拿到空列表,和真实后端行为一致
    var blocked = [blockedUserJson(userId: 9, nickname: '小红')];
    adapter.routes['GET /blocks'] = (options) => ok(blocked);
    adapter.routes['DELETE /blocks/9'] = (options) {
      blocked = [];
      return ok({}, status: 204);
    };
    await pumpBlocked(tester);

    expect(find.text('小红'), findsOneWidget);
    await tester.tap(find.byKey(const Key('unblock.9')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('unblock.confirm')));
    await tester.pumpAndSettle();

    expect(adapter.log.last.method, 'DELETE');
    expect(adapter.log.last.path, '/blocks/9');
    expect(find.text('还没有拉黑任何人'), findsOneWidget);   // reload 后空了
    expect(find.text('已解除拉黑'), findsOneWidget);
  });
}
```

- [x] **Step 2: 跑测试确认失败**

```bash
cd app && ../flutter/bin/flutter.bat test test/features/settings/blocked_users_page_test.dart
```

Expected: FAIL —— 文件不存在。

- [x] **Step 3: 实现**

新建 `app/lib/features/settings/blocked_users_page.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_exception.dart';
import '../moderation/models.dart';
import '../moderation/moderation_controller.dart';
import '../moderation/moderation_repository.dart';

class BlockedUsersPage extends ConsumerWidget {
  const BlockedUsersPage({super.key});

  Future<void> _unblock(BuildContext context, WidgetRef ref, BlockedUser user) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('解除对 ${user.nickname} 的拉黑?'),
        content: const Text('解除后你们将重新互相可见'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('取消')),
          FilledButton(
            key: const Key('unblock.confirm'),
            onPressed: () => Navigator.pop(context, true),
            child: const Text('解除'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    try {
      await ref.read(moderationRepositoryProvider).unblock(user.userId);
      await ref.read(blockedUsersProvider.notifier).reload();
      if (context.mounted) _snack(context, '已解除拉黑');
    } on ApiException catch (error) {
      if (context.mounted) _snack(context, error.message);
    }
  }

  void _snack(BuildContext context, String message) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final blocked = ref.watch(blockedUsersProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('黑名单')),
      body: blocked.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (error, _) => Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(error is ApiException ? error.message : '加载失败,请重试'),
              const SizedBox(height: 12),
              FilledButton(
                onPressed: () => ref.read(blockedUsersProvider.notifier).reload(),
                child: const Text('重试'),
              ),
            ],
          ),
        ),
        data: (items) => items.isEmpty
            ? const Center(child: Text('还没有拉黑任何人'))
            : ListView.separated(
                itemCount: items.length,
                separatorBuilder: (_, _) => const Divider(height: 1, indent: 72),
                itemBuilder: (context, index) {
                  final user = items[index];
                  final avatar = user.avatarUrl;
                  return ListTile(
                    leading: CircleAvatar(
                      backgroundImage: avatar == null ? null : NetworkImage(avatar),
                      onBackgroundImageError: avatar == null ? null : (error, stack) {},
                      child: avatar == null ? const Icon(Icons.person) : null,
                    ),
                    title: Text(user.nickname),
                    subtitle: Text(_dateLabel(user.blockedAt)),
                    trailing: TextButton(
                      key: Key('unblock.${user.userId}'),
                      onPressed: () => _unblock(context, ref, user),
                      child: const Text('解除'),
                    ),
                  );
                },
              ),
      ),
    );
  }
}

String _dateLabel(DateTime? time) {
  if (time == null) return '已拉黑';
  String two(int value) => value.toString().padLeft(2, '0');
  return '拉黑于 ${time.year}-${two(time.month)}-${two(time.day)}';
}
```

`app/lib/features/settings/settings_page.dart`:import 区加 `package:go_router/go_router.dart`,ListView 里(退出登录上面)加:

```dart
          ListTile(
            leading: const Icon(Icons.block),
            title: const Text('黑名单'),
            onTap: () => context.push('/settings/blocks'),
          ),
```

`app/lib/router.dart` 加:

```dart
      GoRoute(path: '/settings/blocks', builder: (context, state) => const BlockedUsersPage()),
```

(import 加 `features/settings/blocked_users_page.dart`)

- [x] **Step 4: 跑测试确认通过 + 回归**

```bash
cd app && ../flutter/bin/flutter.bat test && ../flutter/bin/flutter.bat analyze
```

Expected: PASS + 零告警。

- [x] **Step 5: Commit**

```bash
git add app/lib app/test
git commit -m "feat(app): blocked users management page (M3)"
```

## 批次 4:协议、封禁页(前端)

### Task 14: 用户协议 + 隐私政策(首启弹窗 + 全文页 + 设置入口)

**Files:**
- Create: `app/lib/features/legal/legal_texts.dart`、`app/lib/features/legal/legal_gate.dart`、`app/lib/features/legal/legal_page.dart`、`app/lib/features/legal/agreement_dialog.dart`
- Modify: `app/lib/features/auth/splash_page.dart`(启动门禁)、`app/lib/features/settings/settings_page.dart`(+2 入口)、`app/lib/router.dart`(+2 路由 + redirect 放行 `/legal`)、`app/test/support/harness.dart`(默认已同意)
- Test: `app/test/features/legal/agreement_gate_test.dart`

**Interfaces:**
- Produces: `legalVersion`(int)、`hasAgreedToLegal()`/`acceptLegal()`(SharedPreferences 键 `legal.agreed_version`)、路由 `/legal/agreement`、`/legal/privacy`、弹窗 `showAgreementDialog(context) -> Future<bool?>`(同意 true / 不同意 false)

- [x] **Step 1: 写测试(先让它失败)**

新建 `app/test/features/legal/agreement_gate_test.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/features/legal/legal_texts.dart';

import '../../support/harness.dart';
import '../../support/scripted_adapter.dart';

void main() {
  // harness 默认把 legal.agreed_version 设为当前版本;传 0 模拟「首次启动未同意」
  testWidgets('首次启动 → 弹协议;同意后进登录页并记下版本', (tester) async {
    await pumpApp(tester, ScriptedAdapter({}), prefs: {'legal.agreed_version': 0});
    await tester.pumpAndSettle();

    expect(find.text('同意并继续'), findsOneWidget);
    await tester.tap(find.byKey(const Key('agreement.accept')));
    await tester.pumpAndSettle();

    expect(find.text('获取验证码'), findsOneWidget);   // 已到登录页
    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getInt('legal.agreed_version'), legalVersion);
  });

  testWidgets('不同意 → 停在提示页,不启动', (tester) async {
    await pumpApp(tester, ScriptedAdapter({}), prefs: {'legal.agreed_version': 0});
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('agreement.decline')));
    await tester.pumpAndSettle();

    expect(find.text('需要同意《用户协议》与《隐私政策》才能使用本应用'), findsOneWidget);
    expect(find.text('获取验证码'), findsNothing);
  });

  testWidgets('已同意当前版本 → 不弹窗,直接进登录页', (tester) async {
    await pumpApp(tester, ScriptedAdapter({}), prefs: {'legal.agreed_version': legalVersion});
    await tester.pumpAndSettle();

    expect(find.text('同意并继续'), findsNothing);
    expect(find.text('获取验证码'), findsOneWidget);
  });
}
```

- [x] **Step 2: 跑测试确认失败**

```bash
cd app && ../flutter/bin/flutter.bat test test/features/legal
```

Expected: FAIL —— `legal_texts.dart` 不存在;harness 也还没有默认值。

- [x] **Step 3: 实现**

新建 `app/lib/features/legal/legal_texts.dart`:

```dart
// 用户协议与隐私政策草稿。改文案时把 legalVersion +1,启动弹窗会重新出现一次。
// ⚠️ 上架前需按应用商店与法规要求核对修订(见 spec §13)。
const int legalVersion = 1;

const String userAgreementText = '''
欢迎使用「交友 Chat」。在使用本应用前,请阅读并同意以下条款。

一、账号与资格
1. 本应用面向年满 18 周岁的用户;注册时填写的生日未满 18 周岁的,无法使用本应用。
2. 你用手机号登录即成为本应用用户,请妥善保管手机号与验证码。

二、行为规范
1. 不得发布违法违规、色情低俗、骚扰辱骂、诈骗等内容的资料、照片或消息。
2. 你的昵称、简介与照片可能会经过审核;未通过审核的照片不会对其他用户展示。
3. 其他用户可通过资料卡或聊天页举报违规行为,我们会在核实后处理。

三、违规处理
1. 对违规账号,我们可能采取限制滑卡、封禁账号等措施,并保留相关记录。
2. 你可以拉黑不想继续联系的用户;拉黑后双方互相不可见,你本机的聊天记录会被清除。

四、其他
本协议为开发阶段草稿,最终版本以正式上架时的文本为准。
''';

const String privacyPolicyText = '''
本政策说明「交友 Chat」收集和使用你个人信息的方式。

一、我们收集的信息
1. 手机号:用于注册、登录与账号安全,不会展示给其他用户。
2. 资料信息:昵称、性别、生日、城市、简介、标签与照片,用于向其他用户展示与匹配。
3. 聊天消息:通过腾讯云 IM 传输与存储,用于消息收发与多端同步。

二、我们如何使用信息
1. 资料与照片用于展示、推荐与匹配;照片经过审核后才向其他用户公开。
2. 生日用于确认年满 18 周岁及按年龄偏好推荐。
3. 举报与拉黑记录用于处理违规与保护用户安全。

三、信息共享
除法律法规要求或为提供服务所必需(如短信服务、云服务)外,我们不会向第三方提供你的个人信息。

四、你的权利
你可以在「我的」中查看和修改资料、删除照片,在「设置-黑名单」中管理拉黑关系,也可以退出登录终止使用。

五、联系我们
如对本政策有疑问或需要投诉,请通过应用商店页面提供的联系方式与我们联系。
''';
```

新建 `app/lib/features/legal/legal_gate.dart`:

```dart
import 'package:shared_preferences/shared_preferences.dart';

import 'legal_texts.dart';

const _agreedVersionKey = 'legal.agreed_version';

/// 是否已同意当前版本的协议(文案 bump 版本后会重新弹一次)。
Future<bool> hasAgreedToLegal() async {
  final prefs = await SharedPreferences.getInstance();
  return (prefs.getInt(_agreedVersionKey) ?? 0) >= legalVersion;
}

Future<void> acceptLegal() async {
  final prefs = await SharedPreferences.getInstance();
  await prefs.setInt(_agreedVersionKey, legalVersion);
}
```

新建 `app/lib/features/legal/legal_page.dart`:

```dart
import 'package:flutter/material.dart';

import 'legal_texts.dart';

class LegalPage extends StatelessWidget {
  const LegalPage.agreement({super.key}) : _title = '用户协议', _text = userAgreementText;

  const LegalPage.privacy({super.key}) : _title = '隐私政策', _text = privacyPolicyText;

  final String _title;
  final String _text;

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: Text(_title)),
        body: SingleChildScrollView(
          padding: const EdgeInsets.all(16),
          child: Text(_text, style: const TextStyle(height: 1.6)),
        ),
      );
}
```

新建 `app/lib/features/legal/agreement_dialog.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

/// 首启协议弹窗:不可点外部关闭;同意返回 true,不同意返回 false。
Future<bool?> showAgreementDialog(BuildContext context) => showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (context) => AlertDialog(
        title: const Text('用户协议与隐私政策'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('欢迎使用「交友 Chat」。请阅读并同意以下文件后再开始使用:'),
            TextButton(
              onPressed: () => context.push('/legal/agreement'),
              child: const Text('《用户协议》'),
            ),
            TextButton(
              onPressed: () => context.push('/legal/privacy'),
              child: const Text('《隐私政策》'),
            ),
          ],
        ),
        actions: [
          TextButton(
            key: const Key('agreement.decline'),
            onPressed: () => Navigator.pop(context, false),
            child: const Text('不同意'),
          ),
          FilledButton(
            key: const Key('agreement.accept'),
            onPressed: () => Navigator.pop(context, true),
            child: const Text('同意并继续'),
          ),
        ],
      ),
    );
```

`app/lib/features/auth/splash_page.dart` 全文替换:

```dart
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../legal/agreement_dialog.dart';
import '../legal/legal_gate.dart';
import 'session.dart';

class SplashPage extends ConsumerStatefulWidget {
  const SplashPage({super.key});

  @override
  ConsumerState<SplashPage> createState() => _SplashPageState();
}

class _SplashPageState extends ConsumerState<SplashPage> {
  bool _agreementDeclined = false;

  @override
  void initState() {
    super.initState();
    // 第一步就是 await,状态变更发生在异步之后,initState 里触发是安全的
    _start();
  }

  Future<void> _start() async {
    if (_agreementDeclined) setState(() => _agreementDeclined = false);
    if (!await hasAgreedToLegal()) {
      if (!mounted) return;
      final accepted = await showAgreementDialog(context);
      if (accepted != true) {
        if (!mounted) return;
        setState(() => _agreementDeclined = true);
        if (defaultTargetPlatform == TargetPlatform.android ||
            defaultTargetPlatform == TargetPlatform.iOS) {
          SystemNavigator.pop();   // 移动端直接退出;上面的提示页只是兜底
        }
        return;
      }
      await acceptLegal();
    }
    if (!mounted) return;
    ref.read(sessionProvider.notifier).bootstrap();
  }

  @override
  Widget build(BuildContext context) {
    final session = ref.watch(sessionProvider);
    return Scaffold(
      body: Center(
        child: switch (session) {
          SessionBootFailed(:final message) => Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(message),
                const SizedBox(height: 12),
                FilledButton(
                  onPressed: () => ref.read(sessionProvider.notifier).bootstrap(),
                  child: const Text('重试'),
                ),
              ],
            ),
          _ when _agreementDeclined => Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Text('需要同意《用户协议》与《隐私政策》才能使用本应用'),
                const SizedBox(height: 12),
                FilledButton(
                  key: const Key('splash.reread'),
                  onPressed: _start,
                  child: const Text('重新阅读'),
                ),
              ],
            ),
          _ => const Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                CircularProgressIndicator(),
                SizedBox(height: 12),
                Text('正在启动…'),
              ],
            ),
        },
      ),
    );
  }
}
```

`app/lib/features/settings/settings_page.dart`:ListView 里再加两行(「黑名单」旁边):

```dart
          ListTile(
            leading: const Icon(Icons.description_outlined),
            title: const Text('用户协议'),
            onTap: () => context.push('/legal/agreement'),
          ),
          ListTile(
            leading: const Icon(Icons.privacy_tip_outlined),
            title: const Text('隐私政策'),
            onTap: () => context.push('/legal/privacy'),
          ),
```

`app/lib/router.dart`:import 加 `features/legal/legal_page.dart`;routes 加:

```dart
      GoRoute(path: '/legal/agreement', builder: (context, state) => const LegalPage.agreement()),
      GoRoute(path: '/legal/privacy', builder: (context, state) => const LegalPage.privacy()),
```

redirect 里放行 `/legal`(协议是公开文本,首启弹窗要能打开):

```dart
      switch (session) {
        case SessionLoading() || SessionBootFailed():
          return (location == '/splash' || location.startsWith('/legal')) ? null : '/splash';
        case SessionLoggedOut():
          return (location == '/login' || location.startsWith('/legal')) ? null : '/login';
        case SessionLoggedIn():
          return (location == '/splash' || location == '/login') ? '/home' : null;
      }
```

`app/test/support/harness.dart`:import `package:chatapp_app/features/legal/legal_texts.dart`;`pumpApp` 里改为:

```dart
  final fake = imClient ?? FakeImClient();
  // 默认已同意协议,绝大多数用例直接进 App;协议用例自己传 legal.agreed_version: 0
  SharedPreferences.setMockInitialValues({'legal.agreed_version': legalVersion, ...prefs});
```

- [x] **Step 4: 跑测试确认通过 + 全量回归**

```bash
cd app && ../flutter/bin/flutter.bat test && ../flutter/bin/flutter.bat analyze
```

Expected: 全绿(既有用例因为 harness 默认已同意,不受弹窗影响)。

- [x] **Step 5: Commit**

```bash
git add app/lib app/test
git commit -m "feat(app): agreement gate on first launch + legal pages (M3)"
```

---

### Task 15: 重封禁封禁页(主框架整屏替换)

**Files:**
- Create: `app/lib/features/shell/banned_page.dart`
- Modify: `app/lib/features/shell/home_shell.dart`、`app/lib/features/profile/models.dart`(+banReason)、`app/test/support/sample_data.dart`(profileJson 支持 status/ban_reason)
- Test: `app/test/features/shell/banned_page_test.dart`

**Interfaces:**
- Consumes: `profileProvider`(features/profile/profile_controller.dart)、`GET /users/me` 的 `status`/`ban_reason`(Task 2)、`sessionProvider.logout()`
- Produces: `Profile.banReason`;`BannedPage(profile)`;key `banned.logout`

- [x] **Step 1: 写测试(先让它失败)**

新建 `app/test/features/shell/banned_page_test.dart`:

```dart
import 'package:flutter_test/flutter_test.dart';

import '../../support/harness.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

const _loggedIn = {'auth.access': 'a', 'auth.refresh': 'r', 'auth.user_id': 7};

void main() {
  testWidgets('重封禁用户:主框架换成封禁页,可退出登录', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) =>
          ok(profileJson(status: 'banned_heavy', banReason: '骚扰他人')),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    expect(find.text('账号已被封禁'), findsOneWidget);
    expect(find.text('原因:骚扰他人'), findsOneWidget);
    expect(find.text('发现'), findsNothing);   // 底部 Tab 被整屏替换

    await tester.tap(find.byKey(const Key('banned.logout')));
    await tester.pumpAndSettle();

    expect(find.text('获取验证码'), findsOneWidget);   // 回登录页
  });
}
```

- [x] **Step 2: 跑测试确认失败**

```bash
cd app && ../flutter/bin/flutter.bat test test/features/shell/banned_page_test.dart
```

Expected: FAIL —— `profileJson` 没有 `status`/`banReason` 参数(编译错误);页面也不存在。

- [x] **Step 3: 实现**

`app/test/support/sample_data.dart` 的 `profileJson` 做三处小改(其余保持原样):

1. 参数表最后(`Map<String, dynamic>? preference,` 之后)加两行:

```dart
  String? status,
  String banReason = '',
```

2. 把 `'status': missing.isEmpty ? 'complete' : 'incomplete',` 替换为:

```dart
      'status': status ?? (missing.isEmpty ? 'complete' : 'incomplete'),
      'ban_reason': banReason,
```

`app/lib/features/profile/models.dart` 的 `Profile`:构造函数加 `this.banReason = ''`,字段加 `final String banReason;`,`fromJson` 加 `banReason: (json['ban_reason'] ?? '') as String,`。

新建 `app/lib/features/shell/banned_page.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../auth/session.dart';
import '../discovery/discovery_controller.dart';
import '../profile/models.dart';
import '../profile/profile_controller.dart';

/// 重封禁用户看到的整屏提示(替代主框架):原因 + 退出登录。
class BannedPage extends ConsumerWidget {
  const BannedPage({super.key, required this.profile});

  final Profile profile;

  @override
  Widget build(BuildContext context, WidgetRef ref) => Scaffold(
        body: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(Icons.block, size: 56, color: Colors.red),
                const SizedBox(height: 16),
                const Text('账号已被封禁',
                    style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
                if (profile.banReason.isNotEmpty) ...[
                  const SizedBox(height: 8),
                  Text('原因:${profile.banReason}'),
                ],
                const SizedBox(height: 8),
                const Text('如有疑问请联系客服', style: TextStyle(color: Colors.black54)),
                const SizedBox(height: 24),
                FilledButton(
                  key: const Key('banned.logout'),
                  onPressed: () async {
                    await ref.read(sessionProvider.notifier).logout();
                    ref.invalidate(profileProvider);
                    ref.invalidate(discoveryProvider);
                  },
                  child: const Text('退出登录'),
                ),
              ],
            ),
          ),
        ),
      );
}
```

`app/lib/features/shell/home_shell.dart`:import 加 `banned_page.dart`、`../profile/profile_controller.dart`;build 开头加:

```dart
    final profile = ref.watch(profileProvider).value;
    if (profile != null && profile.status == 'banned_heavy') {
      return BannedPage(profile: profile);
    }
```

- [x] **Step 4: 跑测试确认通过 + 全量回归**

```bash
cd app && ../flutter/bin/flutter.bat test && ../flutter/bin/flutter.bat analyze
```

Expected: PASS + 零告警。

- [x] **Step 5: Commit**

```bash
git add app/lib app/test
git commit -m "feat(app): full-screen banned page for banned_heavy users (M3)"
```

---

## 批次 5:签名打包 + 手测 + 收尾

### Task 16: Android 签名 APK

**Files:**
- Modify: `.gitignore`、`app/android/app/build.gradle.kts`
- Create(本地,不入库):`app/android/key.properties`;keystore 由用户生成并保管

**Interfaces:**
- Produces: `app/build/app/outputs/flutter-apk/app-release.apk`(正式签名);以后所有版本用它更新

- [x] **Step 1: 用户生成 keystore(需要你本人操作)**

先找 keytool(Android Studio 自带的 JDK 里有):

```bash
where keytool 2>/dev/null || ls "$LOCALAPPDATA/Programs/Android Studio/jbr/bin/keytool.exe"
```

然后由**你**在终端跑(交互式输入口令,口令别写进任何文件/命令历史):

```bash
keytool -genkeypair -v -keystore "$USERPROFILE/chatapp-release.jks" -storetype JKS \
  -keyalg RSA -keysize 2048 -validity 10000 -alias chatapp
```

- 口令自定,建议两处备份(密码管理器 + 离线拷贝);**keystore 文件 + 口令丢了,应用就永远无法更新**
- 生成后把 jks 文件复制一份到安全位置

- [x] **Step 2: 配 key.properties + gradle 签名**

`.gitignore` 追加:

```
# Android 签名(密钥与口令永不入库存)
app/android/key.properties
*.jks
```

新建 `app/android/key.properties`(把口令/路径换成你的):

```properties
storePassword=你的口令
keyPassword=你的口令
keyAlias=chatapp
storeFile=C:/Users/you/chatapp-release.jks
```

`app/android/app/build.gradle.kts`:文件顶部(plugins 块之前)加:

```kotlin
import java.io.FileInputStream
import java.util.Properties

val keystoreProperties = Properties()
val keystorePropertiesFile = rootProject.file("key.properties")
if (keystorePropertiesFile.exists()) {
    keystoreProperties.load(FileInputStream(keystorePropertiesFile))
}
```

`android {}` 块里加 `signingConfigs`,并把 release 的 debug 签名换掉:

```kotlin
    signingConfigs {
        create("release") {
            keyAlias = keystoreProperties["keyAlias"] as String
            keyPassword = keystoreProperties["keyPassword"] as String
            storeFile = file(keystoreProperties["storeFile"] as String)
            storePassword = keystoreProperties["storePassword"] as String
        }
    }

    buildTypes {
        release {
            signingConfig = signingConfigs.getByName("release")
        }
    }
```

- [x] **Step 3: 出包**

```bash
cd app && ../flutter/bin/flutter.bat build apk --release --dart-define=API_BASE=http://10.0.2.2:8000/api/v1
```

Expected: 构建成功,产物 `app/build/app/outputs/flutter-apk/app-release.apk`。
(国内源配置已就位;若报 Kotlin 增量缓存错误,确认 `app/android/gradle.properties` 里 `kotlin.incremental=false` 还在)

- [x] **Step 4: 装到模拟器验证**

```bash
"$LOCALAPPDATA/Android/Sdk/platform-tools/adb.exe" devices        # 看两台设备的 id
"$LOCALAPPDATA/Android/Sdk/platform-tools/adb.exe" -s <设备id> install -r build/app/outputs/flutter-apk/app-release.apk
```

打开 App:登录 → 滑卡 → 进会话(核心链路能跑即算通过;详细清单在 Task 17)。真机等你有设备时再补装。

- [x] **Step 5: Commit**

```bash
git add .gitignore app/android/app/build.gradle.kts
git commit -m "chore(android): release signing config (M3)"
```

---

### Task 17: 双端手测 + 文档收尾

**Files:**
- Modify: `CLAUDE.md`、`docs/superpowers/plans/2026-09-11-m3-compliance.md`(本文件,勾 checkbox / 记录差异)

- [x] **Step 1: 起环境(用户参与)**

```bash
# 终端 1:后端(注意只保留一个 runserver 进程,踩过旧进程抢答的坑)
cd chatapp && python manage.py runserver 0.0.0.0:8000
# 若有存量数据,先把测试对重演:
python manage.py dev_reset_pair --a u8 --b u9
# 后台运营账号(没有 superuser 才需要)
python manage.py createsuperuser
```

两台模拟器分别 `flutter run -d <设备id> --dart-define=API_BASE=http://10.0.2.2:8000/api/v1`(或装 Task 16 的 release 包)。

- [ ] **Step 2: 双端手测清单(逐条勾;核心链路已验,其余待补)**

| # | 场景 | 预期 |
|---|---|---|
| 1 | A、B 互滑配对 → 互聊 | 回归正常;配对灰条、会话、未读角标不变 |
| 2 | A 举报 B(资料卡 → 举报,选类型+说明) | 提示「已收到举报」;admin 举报队列出现待处理记录 |
| 3 | admin 处理举报(填备注改「已处理」)| 处理人/时间自动填上 |
| 4 | A 拉黑 B | A 端会话消失、B 端发消息报错(SDK 失败提示);A 看 B 资料卡 404;双方候选互相搜不到;admin Block 页有记录,IM 黑名单已同步(可看后端日志确认无报错) |
| 5 | A 解除拉黑(设置 → 黑名单)| B 发一条消息,会话重新出现在 A 端(聊天记录不恢复) |
| 6 | admin 把 B 封为重封禁(填原因)| B 端重进 App → 整屏封禁页(显示原因);B 的 IM 被踢(日志 `kick` 成功);B 调业务接口全部 403 |
| 7 | admin 解封 B | 审计页出现 UNBAN;B 恢复正常 |
| 8 | 照片审核:`AUTO_APPROVE=0` 重启后端 → A 传张图 | 端上显示「待审核」;admin 通过后角标消失;驳回则显示「已驳回」且资料掉回未完善(候选里消失) |
| 9 | 首启协议:清 App 数据后重开 | 弹协议;同意进 App;设置里能重看全文;不同意退出 |
| 10 | 签名 APK(Task 16 产物)| 安装启动,核心链路可跑 |

- [x] **Step 3: 文档收尾**

- `CLAUDE.md`:
  - 「当前进度」改成 M3 已完成,列出本里程碑内容与测试数(填实际值)
  - 新增「合规与审核(M3)」小节:全局权限类与白名单、`blocked_user_ids` 双向过滤、admin 审核台位置(照片动作/举报队列/封禁动因)、协议版本号机制、IM 黑名单/kick 的调用点与 patch 点、签名打包命令
  - 踩坑:如实测发现 `sns/black_list_*` 或 `kick` 的 identifier 语义与预期不同,如实记录
- 本计划文档:把执行中的偏差、实测结论补进对应 Task 末尾
- 全量回归:后端 `python manage.py test`;前端 `flutter test` + `analyze`

- [x] **Step 4: Commit + 合并**

```bash
git add CLAUDE.md docs/superpowers/plans
git commit -m "docs: M3 wrap-up notes (M3)"
# 用户手测通过后合并(沿用 M2c 节奏:先留分支,验过再合)
git checkout master && git merge --no-ff m3-compliance
```

---

## 附:本计划新增接口一览(手测/联调速查)

| 接口 | 说明 |
|---|---|
| `GET /api/v1/users/{id}` | 公开资料卡;heavy 封禁/双向拉黑 → 404 |
| `POST /api/v1/reports` | `{target_user_id, type, detail?}`;201 新建 / 200 已有待处理(幂等);20/天 |
| `GET /api/v1/blocks` | 我拉黑的人 |
| `POST /api/v1/blocks` | `{target_user_id}`;201/200;后台同步 IM 黑名单 |
| `DELETE /api/v1/blocks/{user_id}` | 204 幂等;后台移除 IM 黑名单 |

后台入口:`/admin/` → 照片(users → 照片,勾选后选动作)、举报队列(moderation → 举报)、封禁(users → 资料,改状态+原因)、只读对账(拉黑/封禁日志)。

---

## 执行记录(2026-09-11)

**进度**:Task 1–16 全部完成并逐 Task 提交;Task 17 的文档收尾已完成;双端手测已验核心链路(登录/互滑/聊天/资料卡/举报入口/拉黑),其余清单项(解封、照片审核、协议、封禁页、安装细节)留待后续补验。

**手测发现并修复的问题(2 个,均已补复现测试)**:
1. **黑名单缓存 bug**:拉黑成功后设置里的黑名单仍显示空——列表 provider 全局缓存没失效。修复:`user_profile_page.dart` 拉黑成功后 `ref.invalidate(blockedUsersProvider)`(commit `cbf802e`)。
2. **所有接口 ~280ms 慢**:根因是每请求新建 MySQL 连接 + TLS 握手 ~250ms(不是资料接口特有)。修复:dev 默认 `DB_SSL_DISABLED=1`(commit `2e5bd1d`),接口降到 ~30ms,后端测试 13s→8.5s。

**执行中的偏差(与计划文本不同处,已在实现中修正)**:
- `users/tests.py` 新测试类插到文件末尾(计划的插入点在 PreferenceTests 中间,会把后续用例卷进新类)
- 黑名单测试断言用 `lastWhere`(reload 的 GET 排在 DELETE 之后——项目老坑)
- 协议用例不能用 `pumpAndSettle`(启动页无限转圈会超时),改有限次 pump
- `splash_page.dart` 需要 `import 'package:flutter/services.dart'`(SystemNavigator 不在 material 里)
- widget 测试里裸 `await provider.future` 会死锁(假时钟),缓存失效用例改成走 UI 路径(预热 → 拉黑 → 回列表)

**实测结论**:`sns/black_list_add|delete` 与 `im_open_login_svc/kick` 用管理员 identifier 均返回成功,重复 add 腾讯侧幂等(见 Task 7 Step 5)。

