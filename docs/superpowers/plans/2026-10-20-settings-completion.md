# 设置页补齐 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking. 本项目全局约定:superpowers 类任务一律内联执行,不派发子 agent。

**Goal:** 补齐设置页的意见反馈、通知设置骨架与关于页,并让反馈真正落库、可被运营处理。

**Architecture:** 新建独立 `feedback` app 承载反馈模型与 `POST /api/v1/feedback`,运营台加只读列表 + 标记已处理;App 与 Web 各自在设置页做三段式重排,新增反馈页、通知骨架页、关于页;版本号由 App 常量 + pubspec 守卫、Web 由 Vite 从 `package.json` 注入。

**Tech Stack:** Django 5.2 + DRF + HTMX 运营台 / Flutter 3.47 + Riverpod + go_router / Vue 3 + TypeScript + Vitest + MSW。

## Global Constraints

- 后端错误一律走现有 DRF 异常契约,不手搓 `Response({"code": ...})`。
- 新增/修改 `.py` 文件必须补模块 docstring 与函数/类 docstring;公开函数带参数必须写 `Args:`(门禁 `CommentCoverageTests`)。
- 新增 `/api/v1` 接口必须在同一次改动内更新 `docs/api/`,否则 `ApiDocsCoverageTests` 红。
- App 端 UI 一律走「心跳」token,禁止裸 hex / 裸字号 / 裸间距。
- 视觉 token 不改,本批不涉及 `tokens.css` 与 Dart theme 的双份同步。
- 反馈只走 `POST /api/v1/feedback`;不新增用户侧列表接口。
- 通知设置只读,不做本地持久化。
- 每个 Task 结束跑对应测试并提交;全部完成后再跑全量门禁。
- 分支:`feat/settings-completion`(已从 master 切出)。

---

### Task 1: 后端 `feedback` app + 提交接口(TDD)

**Files:**
- Create: `chatapp/feedback/__init__.py`
- Create: `chatapp/feedback/apps.py`
- Create: `chatapp/feedback/models.py`
- Create: `chatapp/feedback/serializers.py`
- Create: `chatapp/feedback/views.py`
- Create: `chatapp/feedback/throttles.py`
- Create: `chatapp/feedback/urls.py`
- Create: `chatapp/feedback/tests.py`
- Create: `chatapp/feedback/migrations/__init__.py`
- Create: `chatapp/feedback/migrations/0001_initial.py`(由 `makemigrations` 生成)
- Modify: `chatapp/config/settings.py`
- Modify: `chatapp/config/api_urls.py`

**Interfaces:**
- Produces: `Feedback` / `FeedbackType` / `FeedbackStatus`(`chatapp/feedback/models.py`)
- Produces: `POST /api/v1/feedback` → `201 {id, type, content, contact, created_at}`
- Produces: `FeedbackThrottle`(scope `feedback`)

- [x] **Step 1: 写失败测试**

新建 `chatapp/feedback/tests.py`:

```python
"""意见反馈接口的测试:鉴权、校验、限流与注销级联。"""

from unittest.mock import patch

from django.core.cache import cache
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from users.models import Profile, ProfileStatus

from .models import Feedback, FeedbackStatus


class FeedbackCreateTests(APITestCase):
    """POST /api/v1/feedback:成功落库、边界校验、封禁与限流。"""

    URL = "/api/v1/feedback"

    def setUp(self):
        cache.clear()   # 限流计数在缓存里,用例之间必须清
        self.user = self._make_user("13800138000")
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.user).access_token}")

    def _make_user(self, phone, status=ProfileStatus.COMPLETE):
        """造一个带资料的用户。

        Args:
            phone: 手机号。
            status: 资料状态,默认完善。

        Returns:
            新建的用户实例。
        """
        user = User.objects.create_user(phone=phone)
        Profile.objects.create(user=user, nickname=phone, status=status)
        return user

    def _post(self, **overrides):
        """提交一条反馈,允许覆盖任意字段。

        Args:
            **overrides: 要覆盖的请求字段。

        Returns:
            接口响应。
        """
        payload = {"type": "feature", "content": "希望增加夜间模式开关", "contact": ""}
        payload.update(overrides)
        return self.client.post(self.URL, payload, format="json")

    def test_creates_pending_feedback(self):
        resp = self._post(contact="a@b.com")
        self.assertEqual(resp.status_code, 201)
        body = resp.json()
        self.assertEqual(body["type"], "feature")
        self.assertEqual(body["content"], "希望增加夜间模式开关")
        self.assertEqual(body["contact"], "a@b.com")
        self.assertIn("created_at", body)
        self.assertNotIn("status", body)
        feedback = Feedback.objects.get()
        self.assertEqual(feedback.user, self.user)
        self.assertEqual(feedback.status, FeedbackStatus.PENDING)

    def test_trims_content(self):
        resp = self._post(content="  希望增加夜间模式开关  ")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(Feedback.objects.get().content, "希望增加夜间模式开关")

    def test_rejects_unknown_type(self):
        self.assertEqual(self._post(type="spam").status_code, 400)

    def test_rejects_content_shorter_than_ten(self):
        self.assertEqual(self._post(content="太短了").status_code, 400)

    def test_rejects_content_longer_than_500(self):
        self.assertEqual(self._post(content="x" * 501).status_code, 400)

    def test_rejects_blank_content(self):
        self.assertEqual(self._post(content="   ").status_code, 400)

    def test_rejects_contact_longer_than_64(self):
        self.assertEqual(self._post(contact="x" * 65).status_code, 400)

    def test_requires_auth(self):
        self.client.credentials()
        self.assertEqual(self._post().status_code, 401)

    def test_heavy_banned_forbidden(self):
        self.user.profile.status = ProfileStatus.BANNED_HEAVY
        self.user.profile.save(update_fields=["status"])
        self.assertEqual(self._post().status_code, 403)

    def test_light_banned_can_submit(self):
        self.user.profile.status = ProfileStatus.BANNED_LIGHT
        self.user.profile.save(update_fields=["status"])
        self.assertEqual(self._post().status_code, 201)

    def test_throttled(self):
        from .throttles import FeedbackThrottle
        with patch.object(FeedbackThrottle, "rate", "1/day", create=True):
            self.assertEqual(self._post().status_code, 201)
            self.assertEqual(self._post().status_code, 429)

    def test_deleted_with_account(self):
        self._post()
        self.user.delete()
        self.assertEqual(Feedback.objects.count(), 0)
```

- [x] **Step 2: 跑测试确认失败**

```bash
cd chatapp
python manage.py test feedback
```

Expected: FAIL(`ModuleNotFoundError: No module named 'feedback'`)。

- [x] **Step 3: 建 app 骨架与模型**

新建 `chatapp/feedback/__init__.py`(空文件)、`chatapp/feedback/migrations/__init__.py`(空文件)。

新建 `chatapp/feedback/apps.py`:

```python
"""feedback 应用配置。"""

from django.apps import AppConfig


class FeedbackConfig(AppConfig):
    """意见反馈应用。"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "feedback"
```

新建 `chatapp/feedback/models.py`:

```python
"""用户意见反馈的数据模型。

设计要点:
    反馈与举报分开建模:举报有「被举报人」与处理动作,反馈只有内容与处理状态。
    ``user`` 用 ``CASCADE`` —— 注销账号即删除其全部反馈,与「注销 = 删除全部数据」一致;
    ``handled_by`` 用 ``SET_NULL`` —— 运营账号被删不应连带删除用户反馈。
"""

from django.conf import settings
from django.db import models


class FeedbackType(models.TextChoices):
    """反馈类型。"""

    FEATURE = "feature", "功能建议"
    BUG = "bug", "问题反馈"
    ACCOUNT = "account", "账号问题"
    OTHER = "other", "其他"


class FeedbackStatus(models.TextChoices):
    """反馈处理状态。"""

    PENDING = "pending", "待处理"
    HANDLED = "handled", "已处理"


class Feedback(models.Model):
    """一条用户意见反馈。

    Attributes:
        handled_by: 处理人(运营账号);未处理时为 ``None``。
        handled_at: 首次标记已处理的时间。
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="feedbacks")
    type = models.CharField("类型", max_length=20, choices=FeedbackType.choices)
    content = models.TextField("反馈内容", max_length=500)
    contact = models.CharField("联系方式", max_length=64, blank=True)
    status = models.CharField("状态", max_length=10, choices=FeedbackStatus.choices,
                              default=FeedbackStatus.PENDING)
    handled_note = models.CharField("处理备注", max_length=200, blank=True)
    handled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="feedbacks_handled")
    created_at = models.DateTimeField(auto_now_add=True)
    handled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        """后台与日志中的可读表示。

        Returns:
            ``feedback#主键(用户:类型)``。
        """
        return f"feedback#{self.pk}({self.user_id}:{self.type})"
```

- [x] **Step 4: 注册 app 并生成迁移**

`chatapp/config/settings.py` 的 `INSTALLED_APPS` 末尾追加:

```python
    "feedback",
```

在 `PRESENCE_RATE` 下方追加:

```python
FEEDBACK_RATE = os.getenv("FEEDBACK_RATE", "50/hour" if DEBUG else "5/hour")
```

在 `DEFAULT_THROTTLE_RATES` 中追加:

```python
        "feedback": FEEDBACK_RATE,
```

生成迁移:

```bash
cd chatapp
python manage.py makemigrations feedback
python manage.py migrate
```

- [x] **Step 5: 实现序列化器、限流、视图与路由**

新建 `chatapp/feedback/serializers.py`:

```python
"""意见反馈的序列化器。

设计要点:
    ``content`` 用 ``CharField`` 而不是直接暴露模型字段,借 DRF 的
    ``trim_whitespace`` 与 ``min_length`` / ``max_length`` 一次校验「去空白后 10–500 字」。
"""

from rest_framework import serializers

from .models import Feedback, FeedbackType


class FeedbackCreateSerializer(serializers.ModelSerializer):
    """反馈入参。"""

    type = serializers.ChoiceField(choices=FeedbackType.choices)
    content = serializers.CharField(min_length=10, max_length=500)
    contact = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")

    class Meta:
        model = Feedback
        fields = ["type", "content", "contact"]


class FeedbackSerializer(serializers.ModelSerializer):
    """反馈的对外回执(不回显处理状态与处理人)。"""

    class Meta:
        model = Feedback
        fields = ["id", "type", "content", "contact", "created_at"]
```

新建 `chatapp/feedback/throttles.py`:

```python
"""意见反馈接口的限流。"""

from rest_framework.throttling import SimpleRateThrottle


class FeedbackThrottle(SimpleRateThrottle):
    """按用户限流提交反馈;额度在 settings.DEFAULT_THROTTLE_RATES["feedback"]。"""

    scope = "feedback"

    def get_cache_key(self, request, view):
        """按用户 id 生成限流缓存键。

        Args:
            request: DRF 请求对象。
            view: 当前视图。

        Returns:
            缓存键;未登录返回 ``None``(鉴权会先拦下)。
        """
        if not request.user or not request.user.is_authenticated:
            return None
        return self.cache_format % {"scope": self.scope, "ident": request.user.pk}
```

新建 `chatapp/feedback/views.py`:

```python
"""意见反馈接口。

关联文档:
    - 接口契约:docs/api/feedback.md
"""

from rest_framework.decorators import api_view, throttle_classes
from rest_framework.response import Response

from .serializers import FeedbackCreateSerializer, FeedbackSerializer
from .throttles import FeedbackThrottle


@api_view(["POST"])
@throttle_classes([FeedbackThrottle])
def create_feedback(request):
    """提交意见反馈(POST /api/v1/feedback)。

    Args:
        request: DRF 请求对象,body 需带 ``type`` / ``content`` / 可选 ``contact``。

    Returns:
        201 + 反馈回执(``id`` / ``type`` / ``content`` / ``contact`` / ``created_at``)。
    """
    serializer = FeedbackCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    feedback = serializer.save(user=request.user)
    return Response(FeedbackSerializer(feedback).data, status=201)
```

新建 `chatapp/feedback/urls.py`:

```python
"""意见反馈的路由表。"""

from django.urls import path

from . import views

urlpatterns = [
    path("feedback", views.create_feedback),
]
```

`chatapp/config/api_urls.py` 的 `urlpatterns` 中追加:

```python
    path("", include("feedback.urls")),
```

- [x] **Step 6: 跑测试确认通过**

```bash
cd chatapp
python manage.py test feedback
```

Expected: PASS(12 条)。

- [x] **Step 7: 提交**

```bash
git add chatapp/feedback chatapp/config/settings.py chatapp/config/api_urls.py
git commit -m "feat(feedback): 意见反馈模型与提交接口"
```

---

### Task 2: 接口文档同步

**Files:**
- Create: `docs/api/feedback.md`
- Modify: `docs/api/README.md`
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: Task 1 的 `POST /api/v1/feedback`。

- [x] **Step 1: 新建 `docs/api/feedback.md`**

```markdown
# 意见反馈

> 本分册记录用户意见反馈接口。反馈与举报相互独立:举报针对具体用户或动态,反馈面向产品与运营。

---

## 1. 提交反馈

### 1.1 提交意见反馈

> `POST` `/api/v1/feedback` · 需要鉴权 · 限流 5 次/小时(按用户)

**接口描述**

提交一条意见反馈,落库为「待处理」,由运营在审核台查看并标记已处理。

- 内容去首尾空白后必须为 10–500 字;
- 联系方式选填,最多 64 字;
- 轻封禁账号可提交;重封禁返回 `403`;
- 反馈随账号注销一并删除。

**请求参数**(Body,`application/json`)

| 参数名称 | 必填 | 类型 | 描述 |
|---|---|---|---|
| type | 是 | String | `feature` 功能建议 / `bug` 问题反馈 / `account` 账号问题 / `other` 其他 |
| content | 是 | String | 反馈内容,10–500 字 |
| contact | 否 | String | 联系方式(手机号 / 邮箱 / 微信),≤64 字 |

**响应参数**

| 参数名称 | 类型 | 描述 |
|---|---|---|
| id | Integer | 反馈 ID |
| type | String | 反馈类型 |
| content | String | 反馈内容(已去首尾空白) |
| contact | String | 联系方式;未填为空串 |
| created_at | String | 提交时间(UTC,ISO 8601) |

**请求示例**

```bash
curl -X POST "http://<域名>/api/v1/feedback" \
  -H "Authorization: Bearer <access>" \
  -H "Content-Type: application/json" \
  -d '{"type":"feature","content":"希望增加夜间模式开关","contact":"a@b.com"}'
```

**响应示例**

```json
{
  "id": 12,
  "type": "feature",
  "content": "希望增加夜间模式开关",
  "contact": "a@b.com",
  "created_at": "2026-10-20T03:20:00.000000Z"
}
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|---|---|---|---|
| 400 | 400 | 类型非法 / 内容不足 10 字 / 超过 500 字 / 联系方式超过 64 字 | 按提示修正后重试 |
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |
| 403 | 403 | 账号已被封禁(重封禁) | 提示用户账号受限 |
| 429 | 429 | 提交过于频繁(5 次/小时) | 稍后再试 |
```

- [x] **Step 2: 更新 `docs/api/README.md`**

目录表在 `moderation.md` 后插入:

```markdown
| [feedback.md](feedback.md) | 意见反馈 |
```

「共 **34** 个接口」改为「共 **35** 个接口」,并在 `POST /api/v1/reports` 行后插入:

```markdown
| POST | `/api/v1/feedback` | 提交意见反馈 | [feedback](feedback.md) |
```

- [x] **Step 3: 更新 `CLAUDE.md` 接口表**

在 `/posts` 系列那行前插入:

```markdown
| `POST /feedback` | 意见反馈(10–500 字 + 可选联系方式;限流 5/小时) |
```

- [x] **Step 4: 跑文档门禁**

```bash
cd chatapp
python manage.py test config.tests.ApiDocsCoverageTests
```

Expected: PASS。

- [x] **Step 5: 提交**

```bash
git add docs/api/feedback.md docs/api/README.md CLAUDE.md
git commit -m "docs(api): 补意见反馈接口"
```

---

### Task 3: 运营台反馈列表与处理

**Files:**
- Modify: `chatapp/ops/views.py`
- Modify: `chatapp/ops/urls.py`
- Modify: `chatapp/ops/context_processors.py`
- Modify: `chatapp/ops/templates/ops/base.html`
- Create: `chatapp/ops/templates/ops/feedback.html`
- Create: `chatapp/ops/templates/ops/partials/feedback_table.html`
- Test: `chatapp/ops/tests.py`

**Interfaces:**
- Consumes: Task 1 的 `Feedback` / `FeedbackStatus` / `FeedbackType`。
- Produces: `GET /ops/feedback/`、`POST /ops/feedback/<id>/handle`、`pending_feedback_count`。

- [x] **Step 1: 写失败测试**

在 `chatapp/ops/tests.py` 末尾追加(顶部导入补 `from feedback.models import Feedback, FeedbackStatus, FeedbackType`):

```python
class FeedbackOpsTests(TestCase):
    """意见反馈队列:默认待处理、筛选、标记已处理与权限。"""

    def setUp(self):
        self.staff = make_staff("13700137001")
        self.client.force_login(self.staff)
        self.user = User.objects.create_user(phone="13800138000")
        Profile.objects.create(user=self.user, nickname="反馈用户")
        self.pending = Feedback.objects.create(
            user=self.user, type=FeedbackType.FEATURE, content="希望增加夜间模式开关",
            contact="a@b.com")
        self.handled = Feedback.objects.create(
            user=self.user, type=FeedbackType.BUG, content="消息偶尔重复",
            status=FeedbackStatus.HANDLED)

    def test_lists_pending_by_default(self):
        resp = self.client.get("/ops/feedback/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "希望增加夜间模式开关")
        self.assertNotContains(resp, "消息偶尔重复")

    def test_filters_by_status_and_type(self):
        resp = self.client.get("/ops/feedback/?status=handled")
        self.assertContains(resp, "消息偶尔重复")
        resp = self.client.get("/ops/feedback/?status=all&type=feature")
        self.assertContains(resp, "希望增加夜间模式开关")
        self.assertNotContains(resp, "消息偶尔重复")

    def test_handle_marks_handled(self):
        resp = self.client.post(f"/ops/feedback/{self.pending.id}/handle",
                                {"note": "已记录"})
        self.assertEqual(resp.status_code, 200)
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, FeedbackStatus.HANDLED)
        self.assertEqual(self.pending.handled_note, "已记录")
        self.assertEqual(self.pending.handled_by, self.staff)
        self.assertIsNotNone(self.pending.handled_at)

    def test_handle_is_idempotent(self):
        self.client.post(f"/ops/feedback/{self.pending.id}/handle", {"note": "第一次"})
        self.client.post(f"/ops/feedback/{self.pending.id}/handle", {"note": "第二次"})
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.handled_note, "第一次")

    def test_non_staff_forbidden(self):
        self.client.force_login(User.objects.create_user(phone="13900139000"))
        self.assertEqual(self.client.get("/ops/feedback/").status_code, 403)
```

- [x] **Step 2: 跑测试确认失败**

```bash
cd chatapp
python manage.py test ops.tests.FeedbackOpsTests
```

Expected: FAIL(404)。

- [x] **Step 3: 实现视图与路由**

`chatapp/ops/views.py` 顶部补导入:

```python
from feedback.models import Feedback, FeedbackStatus, FeedbackType
```

文件末尾追加:

```python
def _feedback_queryset(request):
    """按筛选参数取反馈列表(列表页与 HTMX 局部共用)。

    Args:
        request: Django 请求对象,支持 ``status`` 与 ``type``。

    Returns:
        ``(queryset, status, ftype)``;``status=all`` 时不按状态过滤。
    """
    status = request.GET.get("status", FeedbackStatus.PENDING)
    ftype = request.GET.get("type", "")
    qs = Feedback.objects.select_related("user__profile", "handled_by")
    if status in FeedbackStatus.values:
        qs = qs.filter(status=status)
    if ftype in FeedbackType.values:
        qs = qs.filter(type=ftype)
    return qs.order_by("-created_at")[:200], status, ftype


@staff_required
def feedback_list(request):
    """意见反馈列表页,默认只看待处理。

    Args:
        request: Django 请求对象,支持 ``status`` 与 ``type`` 查询参数。

    Returns:
        渲染后的反馈列表页;最多展示 200 条。
    """
    qs, status, ftype = _feedback_queryset(request)
    return render(request, "ops/feedback.html", {
        "feedbacks": qs, "status": status, "ftype": ftype,
        "types": FeedbackType.choices,
    })


@require_POST
@staff_required
def feedback_handle(request, feedback_id):
    """把一条反馈标记为已处理。

    已处理的反馈不会重复改写备注与处理人。

    Args:
        request: Django 请求对象,POST 可带 ``note`` 作为处理备注。

    Returns:
        反馈表格的 HTMX 局部片段。
    """
    feedback = get_object_or_404(Feedback, pk=feedback_id)
    if feedback.status == FeedbackStatus.PENDING:
        feedback.status = FeedbackStatus.HANDLED
        feedback.handled_note = request.POST.get("note", "").strip()[:200]
        feedback.handled_by = request.user
        feedback.handled_at = timezone.now()
        feedback.save(update_fields=["status", "handled_note", "handled_by", "handled_at"])
    qs, status, ftype = _feedback_queryset(request)
    return render(request, "ops/partials/feedback_table.html", {
        "feedbacks": qs, "status": status, "ftype": ftype,
    })
```

`chatapp/ops/urls.py` 在 `logs/` 前追加:

```python
    path("feedback/", views.feedback_list, name="feedback"),
    path("feedback/<int:feedback_id>/handle", views.feedback_handle,
         name="feedback_handle"),
```

- [x] **Step 4: 实现角标与模板**

`chatapp/ops/context_processors.py` 顶部导入:

```python
from feedback.models import Feedback, FeedbackStatus
```

返回值追加:

```python
        "pending_feedback_count": Feedback.objects.filter(
            status=FeedbackStatus.PENDING).count(),
```

`chatapp/ops/templates/ops/base.html` 在「用户」链接前插入:

```html
      <a href="{% url 'ops:feedback' %}" class="{% if '/ops/feedback' in request.path %}active{% endif %}">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
             stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
        意见反馈{% if pending_feedback_count %}<span class="ops-badge">{{ pending_feedback_count }}</span>{% endif %}
      </a>
```

新建 `chatapp/ops/templates/ops/feedback.html`:

```html
{% extends "ops/base.html" %}
{% block page_title %}意见反馈{% endblock %}
{% block content %}
<p class="ops-tabs">
  <a href="?status=pending" class="{% if status == 'pending' %}active{% endif %}">待处理</a>
  <a href="?status=handled" class="{% if status == 'handled' %}active{% endif %}">已处理</a>
  <a href="?status=all" class="{% if status == 'all' %}active{% endif %}">全部</a>
  <span class="ops-tabs-sep">|</span>
  {% for value, label in types %}
    <a href="?status={{ status }}&type={{ value }}" class="{% if ftype == value %}active{% endif %}">{{ label }}</a>
  {% endfor %}
</p>
{% include "ops/partials/feedback_table.html" %}
{% endblock %}
```

新建 `chatapp/ops/templates/ops/partials/feedback_table.html`:

```html
<article>
<table id="feedback-table">
  <thead><tr><th>时间</th><th>用户</th><th>类型</th><th>内容</th><th>联系方式</th><th>状态</th><th></th></tr></thead>
  <tbody>
  {% for f in feedbacks %}
    <tr>
      <td>{{ f.created_at|date:"m-d H:i" }}</td>
      <td>{{ f.user.phone }}{% if f.user.profile.nickname %}({{ f.user.profile.nickname }}){% endif %}</td>
      <td>{{ f.get_type_display }}</td>
      <td>{{ f.content }}</td>
      <td>{{ f.contact|default:"—" }}</td>
      <td>
        {% if f.status == 'pending' %}
          <span class="tag tag-orange">待处理</span>
        {% else %}
          <span class="tag tag-green">已处理</span>
          {% if f.handled_note %}({{ f.handled_note }}){% endif %}
        {% endif %}
      </td>
      <td>
        {% if f.status == 'pending' %}
        <form hx-post="{% url 'ops:feedback_handle' f.id %}?status={{ status }}{% if ftype %}&type={{ ftype }}{% endif %}"
              hx-target="#feedback-table" hx-swap="outerHTML" style="display:inline">
          <input type="text" name="note" maxlength="200" placeholder="备注(可选)">
          <button type="submit" class="secondary">标记已处理</button>
        </form>
        {% endif %}
      </td>
    </tr>
  {% empty %}
    <tr><td colspan="7">没有符合条件的反馈</td></tr>
  {% endfor %}
  </tbody>
</table>
</article>
```

- [x] **Step 5: 跑测试确认通过**

```bash
cd chatapp
python manage.py test ops.tests.FeedbackOpsTests
```

Expected: PASS(5 条)。

- [x] **Step 6: 提交**

```bash
git add chatapp/ops
git commit -m "feat(ops): 意见反馈队列与标记已处理"
```

---

### Task 4: App 版本常量 + 设置页三段式 + 通知/关于页

**Files:**
- Create: `app/lib/core/app_info.dart`
- Create: `app/lib/features/settings/notification_settings_page.dart`
- Create: `app/lib/features/settings/about_page.dart`
- Modify: `app/lib/features/settings/settings_page.dart`
- Modify: `app/lib/router.dart`
- Test: `app/test/core/app_info_test.dart`
- Test: `app/test/features/settings/notification_settings_page_test.dart`
- Test: `app/test/features/settings/about_page_test.dart`
- Test: `app/test/features/settings/settings_page_test.dart`(追加入口断言)

**Interfaces:**
- Produces: `appDisplayName` / `appVersion` / `appIcpNumber`
- Produces: 路由 `/settings/notifications`、`/settings/about`;设置页 key `settings.row.notifications` / `settings.row.feedback` / `settings.row.about`

- [x] **Step 1: 写失败测试**

新建 `app/test/core/app_info_test.dart`:

```dart
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/app_info.dart';

void main() {
  test('appVersion 与 pubspec.yaml 保持一致', () {
    final pubspec = File('pubspec.yaml').readAsStringSync();
    final match = RegExp(r'^version:\s*([^\s]+)', multiLine: true).firstMatch(pubspec);

    expect(match, isNotNull, reason: 'pubspec.yaml 必须有 version 行');
    expect(match!.group(1)!.split('+').first, appVersion);
  });
}
```

新建 `app/test/features/settings/notification_settings_page_test.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/features/settings/notification_settings_page.dart';

void main() {
  testWidgets('两个提醒开关都禁用,并标注即将上线', (tester) async {
    await tester.pumpWidget(const MaterialApp(home: NotificationSettingsPage()));

    expect(find.text('新配对提醒'), findsOneWidget);
    expect(find.text('新消息提醒'), findsOneWidget);
    expect(find.text('即将上线'), findsNWidgets(2));

    final switches = tester.widgetList<Switch>(find.byType(Switch)).toList();
    expect(switches, hasLength(2));
    expect(switches.every((item) => item.onChanged == null), isTrue);
  });
}
```

新建 `app/test/features/settings/about_page_test.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/features/settings/about_page.dart';

void main() {
  testWidgets('展示应用名、版本与协议入口', (tester) async {
    await tester.pumpWidget(const MaterialApp(home: AboutPage()));

    expect(find.text('心跳'), findsOneWidget);
    expect(find.byKey(const Key('about.version')), findsOneWidget);
    expect(find.text('版本 1.0.0'), findsOneWidget);
    expect(find.byKey(const Key('about.agreement')), findsOneWidget);
    expect(find.byKey(const Key('about.privacy')), findsOneWidget);
  });
}
```

在 `app/test/features/settings/settings_page_test.dart` 第一个用例的入口断言处追加:

```dart
    expect(find.byKey(const Key('settings.row.notifications')), findsOneWidget);
    expect(find.byKey(const Key('settings.row.about')), findsOneWidget);
```

- [x] **Step 2: 跑测试确认失败**

```bash
cd app
../flutter/bin/flutter.bat test test/core/app_info_test.dart test/features/settings/notification_settings_page_test.dart test/features/settings/about_page_test.dart
```

Expected: FAIL(`app_info.dart` / 页面不存在)。

- [x] **Step 3: 实现版本常量与两个静态页**

新建 `app/lib/core/app_info.dart`:

```dart
/// 应用展示信息:关于页与测试共用。
///
/// 版本号必须与 `pubspec.yaml` 的 `version:` 前缀一致,
/// `test/core/app_info_test.dart` 会读取 pubspec 做守卫。
const appDisplayName = '心跳';
const appVersion = '1.0.0';

/// 备案号;为空串时关于页不展示该行。
const appIcpNumber = '';
```

新建 `app/lib/features/settings/notification_settings_page.dart`:

```dart
import 'package:flutter/material.dart';

import '../../core/theme/app_colors.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/theme/app_typography.dart';
import '../../core/widgets/app_list_row.dart';
import '../../core/widgets/app_row_group.dart';
import '../../core/widgets/app_sub_page_bar.dart';

/// 通知设置骨架:推送尚未上线,开关只读并明确标注。
class NotificationSettingsPage extends StatelessWidget {
  const NotificationSettingsPage({super.key});

  @override
  Widget build(BuildContext context) => Scaffold(
        backgroundColor: AppColors.bgPage,
        body: SafeArea(
          bottom: false,
          child: Column(
            children: [
              const AppSubPageBar(title: '通知设置'),
              Expanded(
                child: ListView(
                  padding: const EdgeInsets.fromLTRB(AppSpacing.pageH,
                      AppSpacing.md, AppSpacing.pageH, AppSpacing.xxl),
                  children: [
                    AppRowGroup(
                      children: [
                        _NotifyRow(
                          key: const Key('notifications.match'),
                          icon: Icons.favorite_rounded,
                          title: '新配对提醒',
                          subtitle: '有人和你互相喜欢时提醒你',
                        ),
                        _NotifyRow(
                          key: const Key('notifications.message'),
                          icon: Icons.chat_bubble_rounded,
                          title: '新消息提醒',
                          subtitle: '收到新消息时提醒你',
                        ),
                      ],
                    ),
                    const SizedBox(height: AppSpacing.lg),
                    Text(
                      '推送功能将在后续版本上线,届时可以分别控制这两类提醒。当前开关仅为占位,不会保存任何设置。',
                      style: AppText.caption.copyWith(color: AppColors.text3),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      );
}

class _NotifyRow extends StatelessWidget {
  const _NotifyRow({
    super.key,
    required this.icon,
    required this.title,
    required this.subtitle,
  });

  final IconData icon;
  final String title;
  final String subtitle;

  @override
  Widget build(BuildContext context) => AppListRow(
        icon: icon,
        title: title,
        subtitle: subtitle,
        showChevron: false,
        trailing: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text('即将上线',
                style: AppText.micro.copyWith(color: AppColors.text3)),
            const SizedBox(width: AppSpacing.xs),
            Switch.adaptive(value: false, onChanged: null),
          ],
        ),
      );
}
```

新建 `app/lib/features/settings/about_page.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../core/app_info.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/theme/app_typography.dart';
import '../../core/widgets/app_brand_mark.dart';
import '../../core/widgets/app_list_row.dart';
import '../../core/widgets/app_row_group.dart';
import '../../core/widgets/app_sub_page_bar.dart';

/// 关于页:应用名、版本、协议入口与版权。
class AboutPage extends StatelessWidget {
  const AboutPage({super.key});

  @override
  Widget build(BuildContext context) => Scaffold(
        backgroundColor: AppColors.bgPage,
        body: SafeArea(
          bottom: false,
          child: Column(
            children: [
              const AppSubPageBar(title: '关于'),
              Expanded(
                child: ListView(
                  padding: const EdgeInsets.fromLTRB(AppSpacing.pageH,
                      AppSpacing.xxl, AppSpacing.pageH, AppSpacing.xxl),
                  children: [
                    const Center(child: AppBrandMark(size: 72)),
                    const SizedBox(height: AppSpacing.md),
                    Center(
                      child: Text(appDisplayName,
                          style: AppText.title.copyWith(color: AppColors.text1)),
                    ),
                    const SizedBox(height: AppSpacing.xs),
                    Center(
                      child: Text(
                        '版本 $appVersion',
                        key: const Key('about.version'),
                        style: AppText.caption.copyWith(color: AppColors.text3),
                      ),
                    ),
                    const SizedBox(height: AppSpacing.xxl),
                    AppRowGroup(
                      children: [
                        AppListRow(
                          key: const Key('about.agreement'),
                          icon: Icons.description_rounded,
                          title: '用户协议',
                          onTap: () => context.push('/legal/agreement'),
                        ),
                        AppListRow(
                          key: const Key('about.privacy'),
                          icon: Icons.privacy_tip_rounded,
                          title: '隐私政策',
                          onTap: () => context.push('/legal/privacy'),
                        ),
                      ],
                    ),
                    const SizedBox(height: AppSpacing.xxl),
                    if (appIcpNumber.isNotEmpty)
                      Center(
                        child: Text(appIcpNumber,
                            style: AppText.micro.copyWith(color: AppColors.text3)),
                      ),
                    Center(
                      child: Text('© 2026 $appDisplayName',
                          style: AppText.micro.copyWith(color: AppColors.text3)),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      );
}
```

- [x] **Step 4: 设置页重排与路由**

`app/lib/features/settings/settings_page.dart` 的第一张 `AppRowGroup` 改为:

```dart
                    AppRowGroup(
                      children: [
                        AppListRow(
                          key: const Key('settings.row.blocks'),
                          icon: Icons.block_rounded,
                          title: '黑名单',
                          onTap: () => context.push('/settings/blocks'),
                        ),
                        AppListRow(
                          key: const Key('settings.row.notifications'),
                          icon: Icons.notifications_rounded,
                          title: '通知设置',
                          onTap: () => context.push('/settings/notifications'),
                        ),
                      ],
                    ),
                    const SizedBox(height: AppSpacing.cardGap),
                    AppRowGroup(
                      children: [
                        AppListRow(
                          key: const Key('settings.row.about'),
                          icon: Icons.info_rounded,
                          title: '关于',
                          onTap: () => context.push('/settings/about'),
                        ),
                        AppListRow(
                          key: const Key('settings.row.agreement'),
                          icon: Icons.description_rounded,
                          title: '用户协议',
                          onTap: () => context.push('/legal/agreement'),
                        ),
                        AppListRow(
                          key: const Key('settings.row.privacy'),
                          icon: Icons.privacy_tip_rounded,
                          title: '隐私政策',
                          onTap: () => context.push('/legal/privacy'),
                        ),
                      ],
                    ),
```

`app/lib/router.dart` 补导入与路由:

```dart
import 'features/settings/about_page.dart';
import 'features/settings/notification_settings_page.dart';
```

```dart
      GoRoute(path: '/settings/notifications',
          builder: (context, state) => const NotificationSettingsPage()),
      GoRoute(path: '/settings/about', builder: (context, state) => const AboutPage()),
```

> `FeedbackPage` 与反馈入口在 Task 5 加入;本 Task 只做通知与关于,保证每个 Task 结束时能编译、能跑通。

- [x] **Step 5: 跑测试确认通过**

```bash
cd app
../flutter/bin/flutter.bat test test/core/app_info_test.dart test/features/settings/notification_settings_page_test.dart test/features/settings/about_page_test.dart test/features/settings/settings_page_test.dart
```

Expected: PASS。

- [x] **Step 6: 提交**

```bash
git add app/lib/core/app_info.dart app/lib/features/settings/notification_settings_page.dart app/lib/features/settings/about_page.dart app/lib/features/settings/settings_page.dart app/lib/router.dart app/test/core/app_info_test.dart app/test/features/settings/notification_settings_page_test.dart app/test/features/settings/about_page_test.dart app/test/features/settings/settings_page_test.dart
git commit -m "feat(app): 设置页三段式 + 通知骨架 + 关于页"
```

---

### Task 5: App 意见反馈页

**Files:**
- Modify: `app/lib/features/settings/settings_repository.dart`
- Modify: `app/lib/features/settings/settings_page.dart`
- Create: `app/lib/features/settings/feedback_page.dart`
- Modify: `app/lib/router.dart`
- Test: `app/test/features/settings/settings_repository_test.dart`(追加)
- Test: `app/test/features/settings/settings_page_test.dart`(追加入口断言)
- Test: `app/test/features/settings/feedback_page_test.dart`

**Interfaces:**
- Consumes: `SettingsRepository`(`apiClientProvider`)。
- Produces: `SettingsRepository.submitFeedback({required String type, required String content, String contact})`
- Produces: `FeedbackPage` / 路由 `/settings/feedback`

- [x] **Step 1: 写失败测试**

在 `app/test/features/settings/settings_repository_test.dart` 末尾追加:

```dart
  test('submitFeedback 提交类型/内容/联系方式', () async {
    adapter.routes['POST /feedback'] = (options) => ok({'id': 1}, status: 201);

    await makeContainer().read(settingsRepositoryProvider).submitFeedback(
          type: 'bug', content: '消息偶尔重复', contact: 'a@b.com');

    final request = adapter.log.single;
    expect(request.method, 'POST');
    expect(request.path, '/feedback');
    expect(request.data, {
      'type': 'bug',
      'content': '消息偶尔重复',
      'contact': 'a@b.com',
    });
  });

  test('submitFeedback 联系方式为空时不传 contact', () async {
    adapter.routes['POST /feedback'] = (options) => ok({'id': 1}, status: 201);

    await makeContainer()
        .read(settingsRepositoryProvider)
        .submitFeedback(type: 'feature', content: '希望增加夜间模式开关');

    expect(adapter.log.single.data, {
      'type': 'feature',
      'content': '希望增加夜间模式开关',
    });
  });
```

新建 `app/test/features/settings/feedback_page_test.dart`:

```dart
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/core/widgets/app_button.dart';
import 'package:chatapp_app/features/settings/feedback_page.dart';

import '../../support/harness.dart';
import '../../support/scripted_adapter.dart';

void main() {
  late ScriptedAdapter adapter;

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    adapter = ScriptedAdapter({});
  });

  Future<void> pumpPage(WidgetTester tester) async {
    final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))
      ..httpClientAdapter = adapter;
    final container = ProviderContainer(overrides: [
      baseDioProvider.overrideWithValue(dio),
      refreshDioProvider.overrideWithValue(dio),
    ]);
    addTearDown(container.dispose);
    await tester.pumpWidget(UncontrolledProviderScope(
      container: container,
      child: const MaterialApp(home: FeedbackPage()),
    ));
    await tester.pumpAndSettle();
  }

  testWidgets('内容不足 10 字时提交按钮禁用', (tester) async {
    await pumpPage(tester);

    final button = tester.widget<AppButton>(find.byKey(const Key('feedback.submit')));
    expect(button.onPressed, isNull);

    await tester.enterText(find.byKey(const Key('feedback.content')), '太短了');
    await tester.pumpAndSettle();

    final stillDisabled =
        tester.widget<AppButton>(find.byKey(const Key('feedback.submit')));
    expect(stillDisabled.onPressed, isNull);
  });

  testWidgets('选择类型并提交,成功后弹 Toast', (tester) async {
    adapter.routes['POST /feedback'] = (options) => ok({'id': 1}, status: 201);
    await pumpPage(tester);

    await tester.tap(find.text('问题反馈'));
    await tester.pumpAndSettle();
    await tester.enterText(
        find.byKey(const Key('feedback.content')), '消息偶尔重复出现两次');
    await tester.enterText(find.byKey(const Key('feedback.contact')), 'a@b.com');
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('feedback.submit')));
    await tester.pumpAndSettle();

    expect(find.text('反馈已提交,谢谢你'), findsOneWidget);
    final request = adapter.log.single;
    expect(request.path, '/feedback');
    expect(request.data, {
      'type': 'bug',
      'content': '消息偶尔重复出现两次',
      'contact': 'a@b.com',
    });

    await drainToast(tester);
  });

  testWidgets('提交失败保留输入并弹后端文案', (tester) async {
    adapter.routes['POST /feedback'] =
        (options) => jsonError(429, '操作太快了,休息一下吧');
    await pumpPage(tester);

    await tester.enterText(
        find.byKey(const Key('feedback.content')), '消息偶尔重复出现两次');
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('feedback.submit')));
    await tester.pumpAndSettle();

    expect(find.text('操作太快了,休息一下吧'), findsOneWidget);
    expect(find.text('消息偶尔重复出现两次'), findsOneWidget);

    await drainToast(tester);
  });
}
```

- [x] **Step 2: 跑测试确认失败**

```bash
cd app
../flutter/bin/flutter.bat test test/features/settings/feedback_page_test.dart test/features/settings/settings_repository_test.dart
```

Expected: FAIL(`FeedbackPage` / `submitFeedback` 未定义)。

- [x] **Step 3: 实现仓库方法与页面**

`app/lib/features/settings/settings_repository.dart` 追加:

```dart
  /// 提交意见反馈;``type`` 取 feature / bug / account / other。
  Future<void> submitFeedback({
    required String type,
    required String content,
    String contact = '',
  }) async {
    await _api.post('/feedback', data: {
      'type': type,
      'content': content,
      if (contact.isNotEmpty) 'contact': contact,
    });
  }
```

新建 `app/lib/features/settings/feedback_page.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_exception.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/theme/app_typography.dart';
import '../../core/widgets/app_button.dart';
import '../../core/widgets/app_option_group.dart';
import '../../core/widgets/app_sub_page_bar.dart';
import '../../core/widgets/app_text_field.dart';
import '../../core/widgets/app_toast.dart';
import 'settings_repository.dart';

/// 意见反馈页:类型 + 内容 + 可选联系方式。
class FeedbackPage extends ConsumerStatefulWidget {
  const FeedbackPage({super.key});

  @override
  ConsumerState<FeedbackPage> createState() => _FeedbackPageState();
}

class _FeedbackPageState extends ConsumerState<FeedbackPage> {
  static const _types = [
    AppOption(value: 'feature', label: '功能建议'),
    AppOption(value: 'bug', label: '问题反馈'),
    AppOption(value: 'account', label: '账号问题'),
    AppOption(value: 'other', label: '其他'),
  ];

  final _content = TextEditingController();
  final _contact = TextEditingController();
  var _type = 'feature';
  var _submitting = false;

  bool get _canSubmit => !_submitting && _content.text.trim().length >= 10;

  @override
  void dispose() {
    _content.dispose();
    _contact.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    setState(() => _submitting = true);
    try {
      await ref.read(settingsRepositoryProvider).submitFeedback(
            type: _type,
            content: _content.text.trim(),
            contact: _contact.text.trim(),
          );
      if (!mounted) return;
      AppToast.show(context, '反馈已提交,谢谢你');
      await Navigator.of(context).maybePop();
    } on ApiException catch (error) {
      if (mounted) AppToast.show(context, error.message);
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        backgroundColor: AppColors.bgPage,
        body: SafeArea(
          bottom: false,
          child: Column(
            children: [
              const AppSubPageBar(title: '意见反馈'),
              Expanded(
                child: ListView(
                  padding: const EdgeInsets.fromLTRB(AppSpacing.pageH,
                      AppSpacing.md, AppSpacing.pageH, AppSpacing.xxl),
                  children: [
                    Text('反馈类型',
                        style: AppText.caption.copyWith(color: AppColors.text2)),
                    const SizedBox(height: AppSpacing.xs),
                    AppOptionGroup<String>(
                      key: const Key('feedback.type'),
                      options: _types,
                      value: _type,
                      onChanged: (value) => setState(() => _type = value),
                    ),
                    const SizedBox(height: AppSpacing.lg),
                    AppTextField(
                      key: const Key('feedback.content'),
                      controller: _content,
                      label: '反馈内容',
                      hint: '说说遇到了什么,或希望我们做什么(至少 10 字)',
                      maxLines: 6,
                      minLines: 6,
                      maxLength: 500,
                      counterKey: const Key('feedback.content.counter'),
                      onChanged: (_) => setState(() {}),
                    ),
                    const SizedBox(height: AppSpacing.lg),
                    AppTextField(
                      key: const Key('feedback.contact'),
                      controller: _contact,
                      label: '联系方式(选填)',
                      hint: '手机号 / 邮箱 / 微信,方便我们回复你',
                      maxLength: 64,
                    ),
                    const SizedBox(height: AppSpacing.xl),
                    AppButton(
                      key: const Key('feedback.submit'),
                      label: _submitting ? '提交中' : '提交反馈',
                      onPressed: _canSubmit ? _submit : null,
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      );
}
```

`app/lib/router.dart` 补导入与路由:

```dart
import 'features/settings/feedback_page.dart';
```

```dart
      GoRoute(path: '/settings/feedback',
          builder: (context, state) => const FeedbackPage()),
```

`app/lib/features/settings/settings_page.dart` 的「帮助与关于」组第一行插入:

```dart
                        AppListRow(
                          key: const Key('settings.row.feedback'),
                          icon: Icons.feedback_rounded,
                          title: '意见反馈',
                          onTap: () => context.push('/settings/feedback'),
                        ),
```

并在 `app/test/features/settings/settings_page_test.dart` 的入口断言处补:

```dart
    expect(find.byKey(const Key('settings.row.feedback')), findsOneWidget);
```

- [x] **Step 4: 跑测试确认通过**

```bash
cd app
../flutter/bin/flutter.bat test test/features/settings/feedback_page_test.dart test/features/settings/settings_repository_test.dart
```

Expected: PASS。

- [x] **Step 5: 提交**

```bash
git add app/lib/features/settings/settings_repository.dart app/lib/features/settings/feedback_page.dart app/lib/features/settings/settings_page.dart app/lib/router.dart app/test/features/settings/feedback_page_test.dart app/test/features/settings/settings_repository_test.dart app/test/features/settings/settings_page_test.dart
git commit -m "feat(app): 意见反馈页与提交仓库方法"
```

---

### Task 6: Web 版本注入 + 设置页三段式 + 通知/关于页

**Files:**
- Modify: `web/package.json`
- Modify: `web/vite.config.ts`
- Modify: `web/vitest.config.ts`
- Modify: `web/src/vite-env.d.ts`
- Create: `web/src/features/settings/appInfo.ts`
- Create: `web/src/features/settings/NotificationSettingsPage.vue`
- Create: `web/src/features/settings/AboutPage.vue`
- Modify: `web/src/features/settings/SettingsPage.vue`
- Modify: `web/src/router/routes.ts`
- Test: `web/tests/component/settings-page.spec.ts`(改)
- Test: `web/tests/component/notification-settings-page.spec.ts`
- Test: `web/tests/component/about-page.spec.ts`

**Interfaces:**
- Produces: `APP_NAME` / `APP_VERSION` / `APP_ICP`
- Produces: 路由 `settings-notifications`、`settings-about`

- [x] **Step 1: 写失败测试**

新建 `web/tests/component/notification-settings-page.spec.ts`:

```ts
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import NotificationSettingsPage from '@/features/settings/NotificationSettingsPage.vue'

describe('NotificationSettingsPage', () => {
  it('两个开关都禁用并标注即将上线', () => {
    const w = mount(NotificationSettingsPage, {
      global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })

    expect(w.text()).toContain('新配对提醒')
    expect(w.text()).toContain('新消息提醒')
    expect(w.findAll('.notify__soon')).toHaveLength(2)

    const switches = w.findAll('.notify__switch')
    expect(switches).toHaveLength(2)
    for (const item of switches) expect(item.attributes('disabled')).toBeDefined()
  })
})
```

新建 `web/tests/component/about-page.spec.ts`:

```ts
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AboutPage from '@/features/settings/AboutPage.vue'

describe('AboutPage', () => {
  it('展示应用名、版本与协议入口', () => {
    const w = mount(AboutPage, {
      global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })

    expect(w.text()).toContain('心跳')
    expect(w.find('.about__version').text()).toContain('1.0.0')
    expect(w.find('.about__agreement').text()).toContain('用户协议')
    expect(w.find('.about__privacy').text()).toContain('隐私政策')
  })
})
```

`web/tests/component/settings-page.spec.ts` 的「列出全部设置入口」改为:

```ts
  it('列出全部设置入口', async () => {
    stubIm()
    const { w } = await mountPage()
    for (const label of [
      '编辑资料',
      '想找的人',
      '黑名单',
      '我的动态',
      '通知设置',
      '关于',
      '用户协议',
      '隐私政策',
    ]) {
      expect(w.text()).toContain(label)
    }
  })
```

- [x] **Step 2: 跑测试确认失败**

```bash
cd web
npm run test:run -- tests/component/notification-settings-page.spec.ts tests/component/about-page.spec.ts
```

Expected: FAIL(组件不存在)。

- [x] **Step 3: 版本注入**

`web/package.json` 的 `"version"` 改为 `"1.0.0"`。

`web/vite.config.ts` 顶部补:

```ts
import { readFileSync } from 'node:fs'

const pkg = JSON.parse(
  readFileSync(fileURLToPath(new URL('./package.json', import.meta.url)), 'utf-8'),
) as { version: string }
```

`defineConfig({` 内补:

```ts
  define: { __APP_VERSION__: JSON.stringify(pkg.version) },
```

`web/vitest.config.ts` 同样补(测试用独立配置,不加会在 Vitest 里报 `__APP_VERSION__ is not defined`):

```ts
import { readFileSync } from 'node:fs'

const pkg = JSON.parse(
  readFileSync(fileURLToPath(new URL('./package.json', import.meta.url)), 'utf-8'),
) as { version: string }

export default defineConfig({
  plugins: [vue()],
  define: { __APP_VERSION__: JSON.stringify(pkg.version) },
  // ...原有配置
```

`web/src/vite-env.d.ts` 末尾追加:

```ts
/** 构建期注入的应用版本(来源:web/package.json)。 */
declare const __APP_VERSION__: string
```

新建 `web/src/features/settings/appInfo.ts`:

```ts
/** 设置页与关于页共用的应用展示信息。 */
export const APP_NAME = '心跳'
export const APP_VERSION = __APP_VERSION__

/** 备案号;为空串时关于页不展示。 */
export const APP_ICP = ''
```

- [x] **Step 4: 实现两个静态页**

新建 `web/src/features/settings/NotificationSettingsPage.vue`:

```vue
<script setup lang="ts">
import { RouterLink } from 'vue-router'

const rows = [
  { title: '新配对提醒', desc: '有人和你互相喜欢时提醒你' },
  { title: '新消息提醒', desc: '收到新消息时提醒你' },
]
</script>

<template>
  <section class="notify">
    <header class="notify__header">
      <RouterLink class="notify__back" :to="{ name: 'settings' }">← 返回</RouterLink>
      <h1 class="notify__title">通知设置</h1>
    </header>

    <ul class="notify__list">
      <li v-for="row in rows" :key="row.title" class="notify__row">
        <span class="notify__meta">
          <span class="notify__name">{{ row.title }}</span>
          <span class="notify__desc">{{ row.desc }}</span>
        </span>
        <span class="notify__soon">即将上线</span>
        <button type="button" class="notify__switch" role="switch" aria-checked="false" disabled>
          <span class="notify__knob" />
        </button>
      </li>
    </ul>

    <p class="notify__hint">
      推送功能将在后续版本上线,届时可以分别控制这两类提醒。当前开关仅为占位,不会保存任何设置。
    </p>
  </section>
</template>

<style scoped>
.notify {
  display: flex;
  flex-direction: column;
  gap: var(--space-lg);
  max-width: var(--form-card-max);
  margin: 0 auto;
  padding: var(--space-xl) var(--space-section-gap);
}
.notify__header {
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
}
.notify__back {
  align-self: flex-start;
  color: var(--color-text2);
  font-size: var(--text-caption);
  text-decoration: none;
}
.notify__title {
  margin: 0;
  font-size: var(--text-display);
  font-weight: var(--weight-extrabold);
}
.notify__list {
  display: flex;
  flex-direction: column;
  margin: 0;
  padding: 0;
  list-style: none;
  border-radius: var(--radius-card);
  background: var(--color-bg-card);
  box-shadow: var(--shadow-card);
}
.notify__row {
  display: flex;
  align-items: center;
  gap: var(--space-md);
  padding: var(--space-md) var(--space-lg);
  border-bottom: 1px solid var(--color-divider);
}
.notify__row:last-child {
  border-bottom: none;
}
.notify__meta {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 2px;
}
.notify__name {
  color: var(--color-text1);
  font-size: var(--text-body);
}
.notify__desc {
  color: var(--color-text2);
  font-size: var(--text-caption);
}
.notify__soon {
  color: var(--color-text3);
  font-size: var(--text-micro);
}
.notify__switch {
  position: relative;
  width: 44px;
  height: 26px;
  padding: 0;
  border: none;
  border-radius: var(--radius-full);
  background: var(--color-divider);
  cursor: not-allowed;
}
.notify__knob {
  position: absolute;
  top: 3px;
  left: 3px;
  width: 20px;
  height: 20px;
  border-radius: var(--radius-full);
  background: var(--color-bg-card);
}
.notify__hint {
  margin: 0;
  color: var(--color-text3);
  font-size: var(--text-caption);
  line-height: 1.6;
}
</style>
```

新建 `web/src/features/settings/AboutPage.vue`:

```vue
<script setup lang="ts">
import { RouterLink } from 'vue-router'
import { APP_ICP, APP_NAME, APP_VERSION } from './appInfo'
</script>

<template>
  <section class="about">
    <header class="about__header">
      <RouterLink class="about__back" :to="{ name: 'settings' }">← 返回</RouterLink>
      <h1 class="about__title">关于</h1>
    </header>

    <div class="about__brand">
      <span class="about__mark" aria-hidden="true">♥</span>
      <span class="about__name">{{ APP_NAME }}</span>
      <span class="about__version">版本 {{ APP_VERSION }}</span>
    </div>

    <ul class="about__links">
      <li>
        <RouterLink class="about__agreement" :to="{ name: 'legal-agreement' }">用户协议</RouterLink>
      </li>
      <li>
        <RouterLink class="about__privacy" :to="{ name: 'legal-privacy' }">隐私政策</RouterLink>
      </li>
    </ul>

    <p v-if="APP_ICP" class="about__icp">{{ APP_ICP }}</p>
    <p class="about__copyright">© 2026 {{ APP_NAME }}</p>
  </section>
</template>

<style scoped>
.about {
  display: flex;
  flex-direction: column;
  gap: var(--space-lg);
  max-width: var(--form-card-max);
  margin: 0 auto;
  padding: var(--space-xl) var(--space-section-gap);
}
.about__header {
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
}
.about__back {
  align-self: flex-start;
  color: var(--color-text2);
  font-size: var(--text-caption);
  text-decoration: none;
}
.about__title {
  margin: 0;
  font-size: var(--text-display);
  font-weight: var(--weight-extrabold);
}
.about__brand {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-sm);
  padding: var(--space-xl) 0;
}
.about__mark {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 72px;
  height: 72px;
  border-radius: var(--radius-sheet);
  background: var(--gradient-heart);
  color: var(--color-bg-card);
  font-size: 32px;
}
.about__name {
  color: var(--color-text1);
  font-size: var(--text-title);
  font-weight: var(--weight-bold);
}
.about__version {
  color: var(--color-text3);
  font-size: var(--text-caption);
}
.about__links {
  display: flex;
  flex-direction: column;
  margin: 0;
  padding: 0;
  list-style: none;
  border-radius: var(--radius-card);
  background: var(--color-bg-card);
  box-shadow: var(--shadow-card);
}
.about__links li {
  border-bottom: 1px solid var(--color-divider);
}
.about__links li:last-child {
  border-bottom: none;
}
.about__agreement,
.about__privacy {
  display: flex;
  align-items: center;
  height: 48px;
  padding: 0 var(--space-lg);
  color: var(--color-text1);
  text-decoration: none;
}
.about__icp,
.about__copyright {
  margin: 0;
  color: var(--color-text3);
  font-size: var(--text-micro);
  text-align: center;
}
</style>
```

- [x] **Step 5: 设置页重排与路由**

`web/src/features/settings/SettingsPage.vue` 把 `entries` 替换为:

```ts
const groups = [
  {
    title: '账号与隐私',
    entries: [
      { name: 'profile-edit', label: '编辑资料' },
      { name: 'preference', label: '想找的人' },
      { name: 'my-posts', label: '我的动态' },
      { name: 'settings-blocks', label: '黑名单' },
      { name: 'settings-notifications', label: '通知设置' },
    ],
  },
  {
    title: '帮助与关于',
    entries: [
      { name: 'settings-about', label: '关于' },
      { name: 'legal-agreement', label: '用户协议' },
      { name: 'legal-privacy', label: '隐私政策' },
    ],
  },
] as const
```

> 「意见反馈」入口在 Task 7 与页面、路由一起加入,避免中间态出现死链。

模板中原来的单张 `AppCard` 改为:

```vue
    <AppCard v-for="group in groups" :key="group.title" padding="lg">
      <h2 class="settings__group">{{ group.title }}</h2>
      <ul class="settings__list">
        <li v-for="entry in group.entries" :key="entry.name">
          <RouterLink class="settings__item" :to="{ name: entry.name }">
            {{ entry.label }}
          </RouterLink>
        </li>
      </ul>
    </AppCard>
```

样式补:

```css
.settings__group {
  margin: 0 0 var(--space-xs);
  color: var(--color-text3);
  font-size: var(--text-caption);
  font-weight: var(--weight-medium);
}
```

`web/src/router/routes.ts` 在 `settings-blocks` 后追加:

```ts
  {
    path: '/settings/notifications',
    name: 'settings-notifications',
    component: () => import('@/features/settings/NotificationSettingsPage.vue'),
  },
  {
    path: '/settings/about',
    name: 'settings-about',
    component: () => import('@/features/settings/AboutPage.vue'),
  },
```

> 「意见反馈」路由在 Task 7 加入,保证本 Task 结束时可编译、无死链。

- [x] **Step 6: 跑测试确认通过**

```bash
cd web
npm run test:run -- tests/component/notification-settings-page.spec.ts tests/component/about-page.spec.ts tests/component/settings-page.spec.ts
```

Expected: PASS。

- [x] **Step 7: 提交**

```bash
git add web/package.json web/vite.config.ts web/src/vite-env.d.ts web/src/features/settings/appInfo.ts web/src/features/settings/NotificationSettingsPage.vue web/src/features/settings/AboutPage.vue web/src/features/settings/SettingsPage.vue web/src/router/routes.ts web/tests/component/notification-settings-page.spec.ts web/tests/component/about-page.spec.ts web/tests/component/settings-page.spec.ts
git commit -m "feat(web): 设置页三段式 + 通知骨架 + 关于页"
```

---

### Task 7: Web 意见反馈页

**Files:**
- Create: `web/src/api/settings.ts`
- Create: `web/src/features/settings/FeedbackPage.vue`
- Modify: `web/src/router/routes.ts`
- Test: `web/tests/component/feedback-page.spec.ts`

**Interfaces:**
- Consumes: `http`、`parseApiError`。
- Produces: `submitFeedback(payload)` / 路由 `settings-feedback`

- [x] **Step 1: 写失败测试**

新建 `web/tests/component/feedback-page.spec.ts`:

```ts
import { flushPromises, mount } from '@vue/test-utils'
import { HttpResponse, http as mswHttp } from 'msw'
import { createMemoryHistory, createRouter } from 'vue-router'
import { describe, expect, it } from 'vitest'
import FeedbackPage from '@/features/settings/FeedbackPage.vue'
import { server } from '../support/server'

async function mountPage() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div/>' } },
      { path: '/settings', name: 'settings', component: { template: '<div/>' } },
    ],
  })
  await router.push('/')
  await router.isReady()
  const w = mount(FeedbackPage, {
    global: {
      plugins: [router],
      stubs: { RouterLink: { template: '<a><slot /></a>' } },
    },
  })
  await flushPromises()
  return { w, router }
}

describe('FeedbackPage', () => {
  it('内容不足 10 字时提交禁用', async () => {
    const { w } = await mountPage()

    expect(w.find('.feedback__submit').attributes('disabled')).toBeDefined()
    await w.find('.feedback__content').setValue('太短了')
    expect(w.find('.feedback__submit').attributes('disabled')).toBeDefined()
  })

  it('选类型 + 填内容 + 提交成功后切成功态', async () => {
    let body: unknown = null
    server.use(
      mswHttp.post('/api/v1/feedback', async ({ request }) => {
        body = await request.json()
        return HttpResponse.json({ id: 1 }, { status: 201 })
      }),
    )
    const { w } = await mountPage()

    await w.findAll('.feedback__type')[1].trigger('click')
    await w.find('.feedback__content').setValue('消息偶尔重复出现两次')
    await w.find('.feedback__contact input').setValue('a@b.com')
    await w.find('.feedback__submit').trigger('click')
    await flushPromises()

    expect(body).toEqual({
      type: 'bug',
      content: '消息偶尔重复出现两次',
      contact: 'a@b.com',
    })
    expect(w.find('.feedback--done').exists()).toBe(true)
    expect(w.text()).toContain('已收到你的反馈')
  })

  it('提交失败展示后端文案并保留输入', async () => {
    server.use(
      mswHttp.post('/api/v1/feedback', () =>
        HttpResponse.json(
          { code: 429, message: '操作太快了', request_id: 'r' },
          { status: 429 },
        ),
      ),
    )
    const { w } = await mountPage()

    await w.find('.feedback__content').setValue('消息偶尔重复出现两次')
    await w.find('.feedback__submit').trigger('click')
    await flushPromises()

    expect(w.find('.feedback__error').text()).toContain('操作太快了')
    expect((w.find('.feedback__content').element as HTMLTextAreaElement).value).toBe(
      '消息偶尔重复出现两次',
    )
  })
})
```

- [x] **Step 2: 跑测试确认失败**

```bash
cd web
npm run test:run -- tests/component/feedback-page.spec.ts
```

Expected: FAIL(`FeedbackPage.vue` 不存在)。

- [x] **Step 3: 实现 api 与页面**

新建 `web/src/api/settings.ts`:

```ts
import { http } from './http'

/** 反馈类型,与后端 FeedbackType 一一对应(feedback.md)。 */
export type FeedbackType = 'feature' | 'bug' | 'account' | 'other'

export interface FeedbackPayload {
  type: FeedbackType
  content: string
  contact?: string
}

/** 提交意见反馈;成功时后端返回 201。 */
export async function submitFeedback(payload: FeedbackPayload): Promise<void> {
  await http.post('/feedback', payload)
}
```

新建 `web/src/features/settings/FeedbackPage.vue`:

```vue
<script setup lang="ts">
import { computed, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import AppButton from '@/components/AppButton.vue'
import AppInput from '@/components/AppInput.vue'
import { parseApiError } from '@/api/error'
import { submitFeedback, type FeedbackType } from '@/api/settings'

const router = useRouter()
const TYPES: { value: FeedbackType; label: string }[] = [
  { value: 'feature', label: '功能建议' },
  { value: 'bug', label: '问题反馈' },
  { value: 'account', label: '账号问题' },
  { value: 'other', label: '其他' },
]

const type = ref<FeedbackType>('feature')
const content = ref('')
const contact = ref('')
const submitting = ref(false)
const error = ref('')
const submitted = ref(false)

const canSubmit = computed(
  () => !submitting.value && content.value.trim().length >= 10,
)

async function onSubmit() {
  if (!canSubmit.value) return
  submitting.value = true
  error.value = ''
  try {
    await submitFeedback({
      type: type.value,
      content: content.value.trim(),
      ...(contact.value.trim() ? { contact: contact.value.trim() } : {}),
    })
    submitted.value = true
  } catch (e) {
    error.value = parseApiError(e).message
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <section v-if="submitted" class="feedback feedback--done">
    <span class="feedback__check" aria-hidden="true">✓</span>
    <h1 class="feedback__done-title">已收到你的反馈</h1>
    <p class="feedback__done-desc">我们会认真看每一条建议,感谢你帮助心跳变得更好。</p>
    <AppButton block size="lg" @click="router.push({ name: 'settings' })">返回设置</AppButton>
  </section>

  <section v-else class="feedback">
    <header class="feedback__header">
      <RouterLink class="feedback__back" :to="{ name: 'settings' }">← 返回</RouterLink>
      <h1 class="feedback__title">意见反馈</h1>
    </header>

    <div class="feedback__types">
      <button
        v-for="item in TYPES"
        :key="item.value"
        type="button"
        class="feedback__type"
        :class="{ 'feedback__type--active': type === item.value }"
        @click="type = item.value"
      >
        {{ item.label }}
      </button>
    </div>

    <label class="feedback__label">反馈内容</label>
    <textarea
      v-model="content"
      class="feedback__content"
      maxlength="500"
      rows="6"
      placeholder="说说遇到了什么,或希望我们做什么(至少 10 字)"
    />
    <span class="feedback__count">{{ content.length }}/500</span>

    <label class="feedback__label">联系方式(选填)</label>
    <div class="feedback__contact">
      <AppInput
        v-model="contact"
        :maxlength="64"
        placeholder="手机号 / 邮箱 / 微信,方便我们回复你"
      />
    </div>

    <p v-if="error" class="feedback__error">{{ error }}</p>

    <AppButton
      class="feedback__submit"
      block
      size="lg"
      :disabled="!canSubmit"
      :loading="submitting"
      @click="onSubmit"
    >
      提交反馈
    </AppButton>
  </section>
</template>

<style scoped>
.feedback {
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
  max-width: var(--form-card-max);
  margin: 0 auto;
  padding: var(--space-xl) var(--space-section-gap);
}
.feedback--done {
  align-items: center;
  gap: var(--space-lg);
  padding-top: var(--space-xxl);
  text-align: center;
}
.feedback__header {
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
}
.feedback__back {
  align-self: flex-start;
  color: var(--color-text2);
  font-size: var(--text-caption);
  text-decoration: none;
}
.feedback__title {
  margin: 0;
  font-size: var(--text-display);
  font-weight: var(--weight-extrabold);
}
.feedback__types {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--space-sm);
}
.feedback__type {
  height: 44px;
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-input);
  background: var(--color-bg-card);
  color: var(--color-text1);
  font-size: var(--text-body);
  cursor: pointer;
}
.feedback__type--active {
  border-color: var(--color-brand);
  color: var(--color-brand);
}
.feedback__label {
  color: var(--color-text2);
  font-size: var(--text-caption);
}
.feedback__content {
  width: 100%;
  padding: var(--space-md);
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-input);
  background: var(--color-bg-card);
  color: var(--color-text1);
  font-family: var(--font-latin);
  font-size: var(--text-body);
  line-height: 1.6;
  resize: vertical;
}
.feedback__content:focus {
  border-color: var(--color-brand);
  outline: none;
  box-shadow: var(--focus-glow);
}
.feedback__count {
  align-self: flex-end;
  color: var(--color-text3);
  font-size: var(--text-micro);
}
.feedback__error {
  margin: 0;
  color: var(--color-danger);
  font-size: var(--text-caption);
}
.feedback__check {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 64px;
  height: 64px;
  border-radius: var(--radius-full);
  background: var(--gradient-heart);
  color: var(--color-bg-card);
  font-size: 28px;
}
.feedback__done-title {
  margin: 0;
  font-size: var(--text-title);
  font-weight: var(--weight-bold);
}
.feedback__done-desc {
  margin: 0;
  color: var(--color-text2);
  font-size: var(--text-body);
  line-height: 1.6;
}
</style>
```

`web/src/router/routes.ts` 补:

```ts
  {
    path: '/settings/feedback',
    name: 'settings-feedback',
    component: () => import('@/features/settings/FeedbackPage.vue'),
  },
```

`web/src/features/settings/SettingsPage.vue` 的「帮助与关于」组第一行插入:

```ts
      { name: 'settings-feedback', label: '意见反馈' },
```

`web/tests/component/settings-page.spec.ts` 的入口断言补:

```ts
      '意见反馈',
```

- [x] **Step 4: 跑测试确认通过**

```bash
cd web
npm run test:run -- tests/component/feedback-page.spec.ts
```

Expected: PASS。

- [x] **Step 5: 提交**

```bash
git add web/src/api/settings.ts web/src/features/settings/FeedbackPage.vue web/src/router/routes.ts web/tests/component/feedback-page.spec.ts
git commit -m "feat(web): 意见反馈页与提交 api"
```

---

### Task 8: 全量验证 + 计划回填

**Files:**
- Modify: `docs/superpowers/plans/2026-10-20-settings-completion.md`(勾选全部 checkbox,补执行记录)

- [x] **Step 1: 后端全量**

```bash
cd chatapp
python manage.py test
```

Expected: 全绿(前置:Redis 在跑)。

- [x] **Step 2: App 门禁**

```bash
cd app
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test
```

Expected:`No issues found!` + `All tests passed!`。

- [x] **Step 3: Web 门禁**

```bash
cd web
npm run type-check
npm run lint
npm run test:run
```

Expected:零错误、零告警、全绿。

- [x] **Step 4: 回填计划并提交**

## 执行记录

- 2026-10-20:反馈后端 + 运营台 + App/Web 双端设置页补齐;三端门禁通过。
- 后端:`python manage.py test` → `Ran 409 tests in 34.188s` / `OK`(新增 12 条 feedback + 5 条 ops)。
- App:`flutter analyze` → `No issues found!`;`flutter test` → `All tests passed! (+355)`(新增 8 条)。
- Web:`vue-tsc` 零错误;`eslint --max-warnings 0` 零告警;`vitest run` → `68 files / 320 tests passed`(新增 5 条)。
- 说明:本机 Redis 容器映射在 `16379`,后端测试用 `TEST_REDIS_PORT=16379`;本批未新增 Playwright 端到端(需真后端 + Redis + Celery),反馈链路由接口测试 + 双端组件测试覆盖。

```bash
git add docs/superpowers/plans/2026-10-20-settings-completion.md
git commit -m "docs(plan): 设置页补齐执行记录与 checkbox 回填"
```

---

## 自检清单(计划写完后逐条核对)

- [x] spec §3 模型/接口/ops → Task 1/2/3;
- [x] spec §4 App 三段式/三页/版本守卫 → Task 4/5;
- [x] spec §5 Web 三段式/三页/版本注入 → Task 6/7;
- [x] spec §6 边界(空白/超长/重复/限流/封禁/注销/备案号)→ Task 1/5/7;
- [x] spec §7 测试与门禁 → 每个 Task 的测试步骤 + Task 8;
- [x] 无 TBD / TODO /「类似 Task N」;
- [x] 名称一致:`Feedback` / `FeedbackType` / `FeedbackStatus` / `submitFeedback` / `FeedbackPage` / `APP_VERSION` / `appVersion`。


