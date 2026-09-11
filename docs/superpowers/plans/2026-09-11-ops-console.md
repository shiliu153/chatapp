# 运营审核台(Moderation Console)实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新 Django app `ops`,在 `/ops/` 提供产品级运营审核台(举报处理、照片审核、用户封禁、操作日志),替代日常使用 Django admin。

**Architecture:** 与现有 Django 后端同工程:服务端渲染模板 + HTMX 局部刷新,静态资源(Pico.css/htmx)vendored 进工程不依赖 CDN。所有写操作复用现有 services(`log_ban_change`、新抽出的 `review_photos`),与 admin 行为同源。权限判据 `is_staff`。

**Tech Stack:** Django 5.2(模板 + TestCase client)、HTMX 1.9.12、Pico.css 2.0.6(vendored 静态文件)

**Spec:** `docs/superpowers/specs/2026-09-11-moderation-console-design.md`

## Global Constraints

- 所有命令默认 cwd = `chatapp/`(manage.py 所在层);Python 用 anaconda `Django` 环境
- **测试纪律:任何会触发 IM 的路径必须 mock `moderation.services._dispatch_async`**(不许真打腾讯云)
- **App 端 `/api/v1/` 行为零改动**;本计划只加 `/ops/` 路由
- 除登录页外,所有 ops 视图必须挂 `@staff_required`;所有写操作 `POST` + CSRF
- 界面文案全中文;不引入任何第三方依赖(pip/npm),静态资源下载后入库
- 权限判据 `is_staff`;admin 功能保持不变(照片审核 action 仍可用,行为只是多落审计字段)
- 每个 Task 独立提交,提交信息风格:`feat(ops): ...`

---

### Task 1: ops app 骨架 + 登录/权限 + 举报队列列表

**Files:**
- Create: `chatapp/ops/__init__.py`、`chatapp/ops/apps.py`、`chatapp/ops/decorators.py`、`chatapp/ops/forms.py`、`chatapp/ops/context_processors.py`、`chatapp/ops/urls.py`、`chatapp/ops/views.py`、`chatapp/ops/tests.py`
- Create: `chatapp/ops/templates/ops/base.html`、`templates/ops/login.html`、`templates/ops/reports_list.html`
- Create: `chatapp/ops/static/ops/ops.css`、`static/ops/vendor/htmx.min.js`、`static/ops/vendor/pico.min.css`
- Modify: `chatapp/config/settings.py`(INSTALLED_APPS、TEMPLATES context_processors、LOGIN_REDIRECT_URL)、`chatapp/config/urls.py`

**Interfaces:**
- Consumes: `moderation.models.Report/ReportStatus/ReportType`、`accounts.models.User`(USERNAME_FIELD=phone,`create_user` 不设密码)
- Produces: `ops.decorators.staff_required`(其他所有 Task 用)、`ops.context_processors.ops_badges`(提供 `pending_report_count`/`pending_photo_count`)、URL 命名空间 `ops`(`ops:reports` 等)

- [ ] **Step 1: 建分支 + app 骨架 + 环境接线**

```bash
cd D:/pycharmproject/chat_app
git checkout -b ops-console
mkdir -p chatapp/ops/templates/ops/partials chatapp/ops/static/ops/vendor
touch chatapp/ops/__init__.py
```

`chatapp/ops/apps.py`:

```python
from django.apps import AppConfig


class OpsConfig(AppConfig):
    name = "ops"
    verbose_name = "运营审核台"
```

下载 vendored 静态资源(国内 npmmirror;若失败可换 jsdelivr/unpkg 同版本):

```bash
curl -L -o chatapp/ops/static/ops/vendor/htmx.min.js \
  https://registry.npmmirror.com/htmx.org/1.9.12/files/dist/htmx.min.js
curl -L -o chatapp/ops/static/ops/vendor/pico.min.css \
  https://registry.npmmirror.com/@picocss/pico/2.0.6/files/css/pico.min.css
# 验证:两个文件都应 > 20KB,且开头不是 HTML(不是错误页)
ls -la chatapp/ops/static/ops/vendor/
head -c 200 chatapp/ops/static/ops/vendor/htmx.min.js
```

`config/settings.py` 三处修改:

```python
# INSTALLED_APPS 业务 app 列表末尾加:
    "moderation",
    "ops",

# TEMPLATES OPTIONS context_processors 列表末尾加:
            "ops.context_processors.ops_badges",

# 文件末尾(MEDIA 配置附近)加:
LOGIN_REDIRECT_URL = "/ops/reports/"
```

`config/urls.py`:

```python
urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("config.api_urls")),
    path("ops/", include("ops.urls")),
]
```

- [ ] **Step 2: 写失败测试**

`chatapp/ops/tests.py`:

```python
from django.test import TestCase

from accounts.models import User
from moderation.models import Report, ReportStatus, ReportType
from users.models import Profile


def make_staff(phone="13700137000", password="ops-pass-123"):
    """运营账号 = is_staff 用户(create_user 默认不设密码,必须显式 set_password)。"""
    user = User.objects.create_user(phone=phone, is_staff=True)
    user.set_password(password)
    user.save(update_fields=["password"])
    return user


class OpsAuthTests(TestCase):
    def setUp(self):
        self.staff = make_staff()
        self.plain = User.objects.create_user(phone="13800138001")
        self.plain.set_password("pw-123456")
        self.plain.save(update_fields=["password"])

    def test_anonymous_redirected_to_login(self):
        resp = self.client.get("/ops/reports/")
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.url.startswith("/ops/login/"))

    def test_non_staff_forbidden(self):
        self.client.force_login(self.plain)
        resp = self.client.get("/ops/reports/")
        self.assertEqual(resp.status_code, 403)

    def test_staff_can_open_reports(self):
        self.client.force_login(self.staff)
        resp = self.client.get("/ops/reports/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "举报队列")

    def test_login_rejects_non_staff(self):
        resp = self.client.post("/ops/login/",
                                {"username": "13800138001", "password": "pw-123456"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "该账号无运营权限")

    def test_login_accepts_staff(self):
        resp = self.client.post("/ops/login/",
                                {"username": "13700137000", "password": "ops-pass-123"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, "/ops/reports/")


class ReportListTests(TestCase):
    def setUp(self):
        self.client.force_login(make_staff())
        self.a = User.objects.create_user(phone="13800138000")
        self.b = User.objects.create_user(phone="13900139000")
        # 用昵称区分两行(类型标签在筛选 tab 里也会出现,不能拿来断言行内容)
        Profile.objects.create(user=self.a, nickname="被举报甲")
        Profile.objects.create(user=self.b, nickname="被举报乙")
        Report.objects.create(reporter=self.a, target=self.b,
                              type=ReportType.HARASSMENT, detail="骚扰")   # pending → 乙
        Report.objects.create(reporter=self.b, target=self.a,
                              type=ReportType.OTHER, status=ReportStatus.HANDLED)  # → 甲

    def test_default_shows_pending_only(self):
        resp = self.client.get("/ops/reports/")
        self.assertContains(resp, "被举报乙")
        self.assertNotContains(resp, "被举报甲")

    def test_handled_filter(self):
        resp = self.client.get("/ops/reports/", {"status": "handled"})
        self.assertContains(resp, "被举报甲")
        self.assertNotContains(resp, "被举报乙")
```

- [ ] **Step 3: 跑测试确认失败**

Run: `python manage.py test ops`
Expected: FAIL —— `ModuleNotFoundError: No module named 'ops.urls'`(urls/views 还没写)

- [ ] **Step 4: 实现 decorator / 表单 / 上下文处理器 / 视图 / 模板**

`chatapp/ops/decorators.py`:

```python
from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponseForbidden
from django.urls import reverse


def staff_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), reverse("ops:login"))
        if not request.user.is_staff:
            return HttpResponseForbidden("该账号无运营权限")
        return view(request, *args, **kwargs)
    return wrapper
```

`chatapp/ops/forms.py`:

```python
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError


class OpsLoginForm(AuthenticationForm):
    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not user.is_staff:
            raise ValidationError("该账号无运营权限", code="no_staff")
```

`chatapp/ops/context_processors.py`:

```python
from moderation.models import Report, ReportStatus
from users.models import Photo, PhotoStatus


def ops_badges(request):
    if not (request.user.is_authenticated and request.user.is_staff):
        return {}
    return {
        "pending_report_count": Report.objects.filter(status=ReportStatus.PENDING).count(),
        "pending_photo_count": Photo.objects.filter(status=PhotoStatus.PENDING).count(),
    }
```

`chatapp/ops/views.py`(本 Task 只到举报列表;后续 Task 在此文件追加):

```python
from django.db.models import Count
from django.shortcuts import redirect, render

from moderation.models import Report, ReportStatus, ReportType

from .decorators import staff_required


@staff_required
def home(request):
    return redirect("ops:reports")


@staff_required
def reports_list(request):
    status = request.GET.get("status", ReportStatus.PENDING)
    rtype = request.GET.get("type", "")
    qs = (Report.objects.select_related("reporter__profile", "target__profile")
          .annotate(target_report_count=Count("target__reports_received", distinct=True)))
    if status in ReportStatus.values:
        qs = qs.filter(status=status)
    if rtype in ReportType.values:
        qs = qs.filter(type=rtype)
    # -status:字符串降序让 "pending" 排在 "handled" 前(与 admin 审核台同款)
    qs = qs.order_by("-status", "-created_at")[:200]
    return render(request, "ops/reports_list.html", {
        "reports": qs, "status": status, "rtype": rtype, "types": ReportType.choices,
    })
```

`chatapp/ops/urls.py`(本 Task 先建已有路由;每个后续 Task 在此追加自己那条):

```python
from django.contrib.auth import views as auth_views
from django.urls import path

from . import views
from .forms import OpsLoginForm

app_name = "ops"

urlpatterns = [
    path("", views.home, name="home"),
    path("login/", auth_views.LoginView.as_view(
        template_name="ops/login.html",
        authentication_form=OpsLoginForm,
        redirect_authenticated_user=True,
    ), name="login"),
    path("logout/", auth_views.LogoutView.as_view(next_page="ops:login"), name="logout"),
    path("reports/", views.reports_list, name="reports"),
]
```

`chatapp/ops/templates/ops/base.html`(导航条随 Task 递增,先只有「举报」):

```html
{% load static %}
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}运营审核台{% endblock %}</title>
  <link rel="stylesheet" href="{% static 'ops/vendor/pico.min.css' %}">
  <link rel="stylesheet" href="{% static 'ops/ops.css' %}">
  <script src="{% static 'ops/vendor/htmx.min.js' %}"></script>
</head>
<body hx-headers='{"X-CSRFToken": "{{ csrf_token }}"}'>
<nav class="container ops-nav">
  <strong>运营审核台</strong>
  <a href="{% url 'ops:reports' %}">举报{% if pending_report_count %} <span class="ops-badge">{{ pending_report_count }}</span>{% endif %}</a>
  {% if user.is_authenticated %}
  <form method="post" action="{% url 'ops:logout' %}" class="ops-logout">
    {% csrf_token %}
    <span>{{ user.phone }}</span>
    <button type="submit" class="secondary outline">退出</button>
  </form>
  {% endif %}
</nav>
<main class="container">
  {% block content %}{% endblock %}
</main>
</body>
</html>
```

`chatapp/ops/templates/ops/login.html`:

```html
{% extends "ops/base.html" %}
{% block title %}登录 · 运营审核台{% endblock %}
{% block content %}
<article class="ops-login">
  <h2>运营审核台</h2>
  <form method="post">
    {% csrf_token %}
    {% if form.non_field_errors %}<p class="ops-error">{{ form.non_field_errors.0 }}</p>{% endif %}
    <label>手机号<input type="text" name="username" autofocus autocomplete="username"></label>
    <label>密码<input type="password" name="password" autocomplete="current-password"></label>
    <button type="submit">登录</button>
  </form>
</article>
{% endblock %}
```

`chatapp/ops/templates/ops/reports_list.html`:

```html
{% extends "ops/base.html" %}
{% block content %}
<h2>举报队列</h2>
<p class="ops-tabs">
  <a href="?status=pending" class="{% if status == 'pending' %}active{% endif %}">待处理</a>
  <a href="?status=handled" class="{% if status == 'handled' %}active{% endif %}">已处理</a>
  <a href="?status=all" class="{% if status == 'all' %}active{% endif %}">全部</a>
  <span class="ops-tabs-sep">|</span>
  {% for value, label in types %}
    <a href="?status={{ status }}&type={{ value }}" class="{% if rtype == value %}active{% endif %}">{{ label }}</a>
  {% endfor %}
</p>
<table>
  <thead><tr><th>时间</th><th>类型</th><th>举报人</th><th>被举报人</th><th>被举报次数</th><th></th></tr></thead>
  <tbody>
  {% for r in reports %}
    <tr>
      <td>{{ r.created_at|date:"m-d H:i" }}</td>
      <td>{{ r.get_type_display }}</td>
      <td>{{ r.reporter.phone }}</td>
      <td>{{ r.target.phone }}{% if r.target.profile.nickname %}({{ r.target.profile.nickname }}){% endif %}</td>
      <td>{{ r.target_report_count }}</td>
      <td><a href="{% url 'ops:report_detail' r.id %}">查看</a></td>
    </tr>
  {% empty %}
    <tr><td colspan="6">没有符合条件的举报</td></tr>
  {% endfor %}
  </tbody>
</table>
{% endblock %}
```

注:此模板引用了 `ops:report_detail`(Task 2 才建)。把该链接行从本 Task 模板里先去掉(改成 `<td></td>`),Task 2 再补上;避免本 Task 模板渲染报 NoReverseMatch。

`chatapp/ops/static/ops/ops.css`:

```css
.ops-nav { display: flex; gap: 1rem; align-items: center; padding-top: 1rem; }
.ops-nav .ops-badge { background: #d93025; color: #fff; border-radius: 999px;
  font-size: .75rem; padding: .05rem .5rem; margin-left: .25rem; }
.ops-nav .ops-logout { margin-left: auto; display: flex; gap: .5rem; align-items: center; }
.ops-nav .ops-logout button { padding: .25rem .75rem; width: auto; margin: 0; }
.ops-error { color: #b3261e; font-weight: 600; }
.ops-warn { color: #8a6d00; }
.ops-login { max-width: 26rem; margin: 4rem auto; }
.ops-grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
.ops-tabs a { margin-right: .75rem; }
.ops-tabs a.active { font-weight: 700; text-decoration: underline; }
.ops-tabs-sep { margin: 0 .5rem; color: #999; }
.ops-photos { display: flex; gap: .4rem; flex-wrap: wrap; }
.ops-photos img { max-height: 96px; border-radius: 6px; }
```

- [ ] **Step 5: 跑测试确认通过**

Run: `python manage.py test ops`
Expected: PASS(6 个用例全绿)

- [ ] **Step 6: 提交**

```bash
git add chatapp/ops chatapp/config/settings.py chatapp/config/urls.py
git commit -m "feat(ops): ops app skeleton, staff login, report queue list"
```

---

### Task 2: 举报详情页(只读)

**Files:**
- Create: `chatapp/ops/templates/ops/report_detail.html`、`templates/ops/partials/user_card.html`
- Modify: `chatapp/ops/views.py`、`chatapp/ops/urls.py`、`chatapp/ops/tests.py`、`templates/ops/reports_list.html`(补回详情链接)

**Interfaces:**
- Consumes: `ops.decorators.staff_required`、`moderation.models.BanLog/Report`
- Produces: `ops.views.report_detail`、view 上下文函数 `_report_context(report)`(Task 3 复用)、`ops/partials/user_card.html`(入参 `user_obj` / `profile`,Task 6 也复用)

- [ ] **Step 1: 写失败测试**

追加到 `chatapp/ops/tests.py`:

```python
class ReportDetailTests(TestCase):
    def setUp(self):
        self.client.force_login(make_staff())
        self.a = User.objects.create_user(phone="13800138000")
        self.b = User.objects.create_user(phone="13900139000")
        self.report = Report.objects.create(reporter=self.a, target=self.b,
                                            type=ReportType.HARASSMENT, detail="骚扰我")

    def test_detail_shows_both_parties(self):
        resp = self.client.get(f"/ops/reports/{self.report.id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "13800138000")   # 举报人
        self.assertContains(resp, "13900139000")   # 被举报人
        self.assertContains(resp, "骚扰我")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python manage.py test ops.tests.ReportDetailTests`
Expected: FAIL —— 404(路由还没建)

- [ ] **Step 3: 实现**

`chatapp/ops/views.py` 追加:

```python
@staff_required
def report_detail(request, report_id):
    report = get_object_or_404(
        Report.objects.select_related("reporter", "target", "handled_by"), pk=report_id)
    return render(request, "ops/report_detail.html", _report_context(report))


def _report_context(report):
    """举报详情页上下文;Task 3 的 HTMX 局部刷新也复用它。"""
    return {
        "report": report,
        "reporter_profile": getattr(report.reporter, "profile", None),
        "target_profile": getattr(report.target, "profile", None),
        "reporter_reports": Report.objects.filter(reporter=report.reporter)
                                           .exclude(pk=report.pk)[:10],
        "target_reports": Report.objects.filter(target=report.target)
                                        .exclude(pk=report.pk)[:10],
        "target_ban_logs": BanLog.objects.filter(user=report.target)[:10],
    }
```

对应 import 行改为:

```python
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render

from moderation.models import BanLog, Report, ReportStatus, ReportType
```

`chatapp/ops/urls.py` urlpatterns 末尾加:

```python
    path("reports/<int:report_id>/", views.report_detail, name="report_detail"),
```

`chatapp/ops/templates/ops/report_detail.html`:

```html
{% extends "ops/base.html" %}
{% block content %}
<h2>举报详情 #{{ report.id }}</h2>
<p><a href="{% url 'ops:reports' %}">← 返回队列</a></p>
<article>
  <p><strong>类型:</strong>{{ report.get_type_display }}
     　<strong>时间:</strong>{{ report.created_at|date:"Y-m-d H:i" }}
     　<strong>状态:</strong>{{ report.get_status_display }}</p>
  <p><strong>说明:</strong>{{ report.detail|default:"(无)" }}</p>
</article>
<div class="ops-grid-2">
  <article>
    <h3>举报人</h3>
    {% include "ops/partials/user_card.html" with user_obj=report.reporter profile=reporter_profile %}
  </article>
  <article>
    <h3>被举报人</h3>
    {% include "ops/partials/user_card.html" with user_obj=report.target profile=target_profile %}
  </article>
</div>
<article id="report-panel-wrap">
  <h3>处理</h3>
  <p>待处理(Task 3 提供操作)</p>
</article>
<article>
  <h3>被举报人封禁历史</h3>
  <table>
    <thead><tr><th>时间</th><th>动作</th><th>原因</th><th>操作人</th></tr></thead>
    <tbody>
    {% for log in target_ban_logs %}
      <tr><td>{{ log.created_at|date:"Y-m-d H:i" }}</td><td>{{ log.get_action_display }}</td>
          <td>{{ log.reason|default:"—" }}</td><td>{{ log.operator.phone|default:"—" }}</td></tr>
    {% empty %}<tr><td colspan="4">无记录</td></tr>{% endfor %}
    </tbody>
  </table>
</article>
<article>
  <h3>双方举报历史</h3>
  <p>举报人发出的举报:</p>
  <table>
    <thead><tr><th>时间</th><th>类型</th><th>被举报人</th><th>状态</th></tr></thead>
    <tbody>
    {% for r in reporter_reports %}
      <tr><td>{{ r.created_at|date:"m-d H:i" }}</td><td>{{ r.get_type_display }}</td>
          <td>{{ r.target.phone }}</td><td>{{ r.get_status_display }}</td></tr>
    {% empty %}<tr><td colspan="4">无记录</td></tr>{% endfor %}
    </tbody>
  </table>
  <p>被举报人被举报的历史:</p>
  <table>
    <thead><tr><th>时间</th><th>类型</th><th>举报人</th><th>状态</th></tr></thead>
    <tbody>
    {% for r in target_reports %}
      <tr><td>{{ r.created_at|date:"m-d H:i" }}</td><td>{{ r.get_type_display }}</td>
          <td>{{ r.reporter.phone }}</td><td>{{ r.get_status_display }}</td></tr>
    {% empty %}<tr><td colspan="4">无记录</td></tr>{% endfor %}
    </tbody>
  </table>
</article>
{% endblock %}
```

`chatapp/ops/templates/ops/partials/user_card.html`(Task 6 会补「查看用户详情」链接,现在不加):

```html
<div class="ops-user-card">
  <p><strong>{{ user_obj.phone }}</strong>
    {% if profile %} {{ profile.nickname|default:"(未设昵称)" }}{% endif %}</p>
  {% if profile %}
    <p>状态:{{ profile.get_status_display }}
      {% if profile.ban_reason %}· 原因:{{ profile.ban_reason }}{% endif %}</p>
    <p>性别:{{ profile.get_gender_display|default:"—" }} · 城市:{{ profile.city|default:"—" }}</p>
    <p>简介:{{ profile.bio|default:"—" }}</p>
  {% else %}
    <p>尚未创建资料</p>
  {% endif %}
  <div class="ops-photos">
    {% for photo in user_obj.photos.all|slice:":6" %}
      <img src="{{ photo.file.url }}" alt="photo">
    {% empty %}<span>无照片</span>{% endfor %}
  </div>
</div>
```

`reports_list.html` 把 Task 1 留空的 `<td></td>` 改回:

```html
<td><a href="{% url 'ops:report_detail' r.id %}">查看</a></td>
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python manage.py test ops`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add chatapp/ops
git commit -m "feat(ops): report detail page with both parties' cards and history"
```

---

### Task 3: 举报处理动作(标记已处理 + 快捷封禁,HTMX)

**Files:**
- Create: `chatapp/ops/templates/ops/partials/report_panel.html`
- Modify: `chatapp/ops/views.py`、`chatapp/ops/urls.py`、`chatapp/ops/tests.py`、`templates/ops/report_detail.html`

**Interfaces:**
- Consumes: `moderation.services.log_ban_change(user, old_status, new_status, reason, operator)`(已存在:写 BanLog;重封会后台踢 IM)、`_report_context`
- Produces: `ops.views._apply_status_change(user, action, reason, operator)`(action ∈ `ban_light|ban_heavy|unban`;Task 7 复用)

- [ ] **Step 1: 写失败测试**

追加到 `chatapp/ops/tests.py`(顶部 import 补:`from unittest.mock import patch`、`from im import client as im_client`、`from moderation.models import BanAction, BanLog`、`from users.models import Profile, ProfileStatus`):

```python
class ReportActionTests(TestCase):
    def setUp(self):
        self.staff = make_staff()
        self.client.force_login(self.staff)
        self.reporter = User.objects.create_user(phone="13800138000")
        self.target = User.objects.create_user(phone="13900139000")
        Profile.objects.create(user=self.target, status=ProfileStatus.COMPLETE)
        self.report = Report.objects.create(reporter=self.reporter, target=self.target,
                                            type=ReportType.PORN, detail="色情")

    def test_handle_marks_report(self):
        resp = self.client.post(f"/ops/reports/{self.report.id}/handle", {"note": "已警告"})
        self.assertEqual(resp.status_code, 200)
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, ReportStatus.HANDLED)
        self.assertEqual(self.report.handled_note, "已警告")
        self.assertEqual(self.report.handled_by, self.staff)
        self.assertIsNotNone(self.report.handled_at)
        self.assertContains(resp, "已处理")

    def test_handle_twice_keeps_first(self):
        self.client.post(f"/ops/reports/{self.report.id}/handle", {"note": "第一次"})
        self.client.post(f"/ops/reports/{self.report.id}/handle", {"note": "第二次"})
        self.report.refresh_from_db()
        self.assertEqual(self.report.handled_note, "第一次")

    def test_quick_ban_heavy_bans_and_handles(self):
        with patch("moderation.services._dispatch_async") as dispatch:
            resp = self.client.post(f"/ops/reports/{self.report.id}/ban",
                                    {"level": "ban_heavy", "reason": "色情图片"})
        self.assertContains(resp, "已处理")
        profile = Profile.objects.get(user=self.target)
        self.assertEqual(profile.status, ProfileStatus.BANNED_HEAVY)
        self.assertEqual(profile.ban_reason, "色情图片")
        self.assertTrue(BanLog.objects.filter(user=self.target, action=BanAction.BAN_HEAVY,
                                              operator=self.staff).exists())
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, ReportStatus.HANDLED)
        self.assertEqual(self.report.handled_note, "封禁处理")
        dispatch.assert_called_once_with(im_client.kick_user, self.target.im_user_id)

    def test_quick_ban_requires_reason(self):
        with patch("moderation.services._dispatch_async") as dispatch:
            resp = self.client.post(f"/ops/reports/{self.report.id}/ban",
                                    {"level": "ban_light", "reason": ""})
        self.assertContains(resp, "必须填写原因")
        profile = Profile.objects.get(user=self.target)
        self.assertEqual(profile.status, ProfileStatus.COMPLETE)
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, ReportStatus.PENDING)
        dispatch.assert_not_called()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python manage.py test ops.tests.ReportActionTests`
Expected: FAIL —— 404(handle/ban 路由还没建)

- [ ] **Step 3: 实现**

`chatapp/ops/views.py` 追加(import 补 `from django.utils import timezone`、`from django.views.decorators.http import require_POST`、`from moderation.services import log_ban_change`、`from users.models import Profile, ProfileStatus`):

```python
def _apply_status_change(user, action, reason, operator):
    """ban_light / ban_heavy / unban。封禁审计与踢 IM 统一走 log_ban_change(与 admin 同源)。"""
    profile, _ = Profile.objects.get_or_create(user=user)
    old_status = profile.status
    if action == "unban":
        profile.ban_reason = ""
        profile.status = ProfileStatus.INCOMPLETE
        profile.save(update_fields=["status", "ban_reason"])
        profile.refresh_status()   # 回到 complete/incomplete(封禁态不参与重算,必须先在非封禁态)
    else:
        profile.status = (ProfileStatus.BANNED_LIGHT if action == "ban_light"
                          else ProfileStatus.BANNED_HEAVY)
        profile.ban_reason = reason[:200]
        profile.save(update_fields=["status", "ban_reason"])
    log_ban_change(user, old_status, profile.status, reason[:200], operator)
    return profile


@require_POST
@staff_required
def report_handle(request, report_id):
    report = get_object_or_404(Report, pk=report_id)
    if report.status == ReportStatus.PENDING:
        report.status = ReportStatus.HANDLED
        report.handled_note = request.POST.get("note", "").strip()[:200]
        report.handled_by = request.user
        report.handled_at = timezone.now()
        report.save(update_fields=["status", "handled_note", "handled_by", "handled_at"])
    return render(request, "ops/partials/report_panel.html",
                  {"report": report, "error": None})


@require_POST
@staff_required
def report_ban(request, report_id):
    report = get_object_or_404(Report.objects.select_related("target"), pk=report_id)
    level = request.POST.get("level")
    reason = request.POST.get("reason", "").strip()
    error = None
    if level not in ("ban_light", "ban_heavy"):
        error = "未知的封禁级别"
    elif not reason:
        error = "封禁必须填写原因"
    if error is None:
        _apply_status_change(report.target, level, reason, request.user)
        if report.status == ReportStatus.PENDING:
            report.status = ReportStatus.HANDLED
            report.handled_note = "封禁处理"
            report.handled_by = request.user
            report.handled_at = timezone.now()
            report.save(update_fields=["status", "handled_note", "handled_by", "handled_at"])
    return render(request, "ops/partials/report_panel.html",
                  {"report": report, "error": error})
```

`chatapp/ops/urls.py` urlpatterns 末尾加:

```python
    path("reports/<int:report_id>/handle", views.report_handle, name="report_handle"),
    path("reports/<int:report_id>/ban", views.report_ban, name="report_ban"),
```

`chatapp/ops/templates/ops/partials/report_panel.html`:

```html
<div id="report-panel">
  {% if error %}<p class="ops-error">{{ error }}</p>{% endif %}
  {% if report.status == 'handled' %}
    <p>已处理{% if report.handled_by %}({{ report.handled_by.phone }}){% endif %}
       · {{ report.handled_at|date:"Y-m-d H:i" }}</p>
    {% if report.handled_note %}<p>备注:{{ report.handled_note }}</p>{% endif %}
  {% else %}
    <form hx-post="{% url 'ops:report_handle' report.id %}"
          hx-target="#report-panel" hx-swap="outerHTML">
      <label>处理备注<input type="text" name="note" maxlength="200"></label>
      <button type="submit">标记已处理</button>
    </form>
    <hr>
    <form hx-post="{% url 'ops:report_ban' report.id %}"
          hx-target="#report-panel" hx-swap="outerHTML">
      <label>封禁原因(封禁必填)<input type="text" name="reason" maxlength="200"></label>
      <button type="submit" name="level" value="ban_light">轻度封禁被举报人</button>
      <button type="submit" name="level" value="ban_heavy" class="secondary">重度封禁被举报人</button>
    </form>
    <p><small>及时封禁会自动把该举报标记为已处理(备注「封禁处理」)。</small></p>
  {% endif %}
</div>
```

`report_detail.html` 的占位块替换为:

```html
<article>
  <h3>处理</h3>
  {% include "ops/partials/report_panel.html" with error=None %}
</article>
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python manage.py test ops`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add chatapp/ops
git commit -m "feat(ops): report handling actions with quick-ban (HTMX)"
```

---

### Task 4: 照片审核逻辑抽取 + Photo 审计字段(migration + admin 改造)

**Files:**
- Modify: `chatapp/users/models.py`、`chatapp/users/services.py`、`chatapp/users/admin.py`、`chatapp/users/tests.py`
- Create: `chatapp/users/migrations/0004_photos_review_audit.py`(makemigrations 自动生成,名字以实际为准)

**Interfaces:**
- Produces: `users.services.review_photos(queryset, status, operator=None) -> int`(改状态 + 重算 Profile 状态 + 落 `reviewed_by/reviewed_at`;Task 5 复用)、`Photo.reviewed_by` / `Photo.reviewed_at` 字段
- Consumes: 无(纯 users app 内重构)

- [ ] **Step 1: 写失败测试**

`chatapp/users/tests.py` 的 `PhotoAdminActionTests` 类内追加:

```python
    def test_action_records_reviewer_and_time(self):
        self._run_action("approve_photos", self.photo)
        self.photo.refresh_from_db()
        self.assertEqual(self.photo.reviewed_by, self.staff)
        self.assertIsNotNone(self.photo.reviewed_at)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python manage.py test users.tests.PhotoAdminActionTests`
Expected: FAIL —— `AttributeError: 'Photo' object has no attribute 'reviewed_by'`

- [ ] **Step 3: 模型 + service + admin 改造**

`chatapp/users/models.py` 的 `Photo` 类在 `created_at` 前加:

```python
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="photos_reviewed")
    reviewed_at = models.DateTimeField(null=True, blank=True)
```

`chatapp/users/services.py` 改为:

```python
from django.utils import timezone

from .models import Preference, Profile


def get_profile(user):
    """取当前用户资料;没有就建空 Profile + 空 Preference(资料是懒创建的)。"""
    profile, _ = Profile.objects.get_or_create(user=user)
    Preference.objects.get_or_create(profile=profile)
    return profile


def review_photos(queryset, status, operator=None) -> int:
    """通过/驳回照片:落审核审计 + 重算相关用户的资料完善状态。admin 与 ops 共用。"""
    user_ids = set(queryset.values_list("user_id", flat=True))
    count = queryset.update(status=status, reviewed_by=operator, reviewed_at=timezone.now())
    # 照片数量变化会影响「资料完善」判定(掉回未完善 = 失去候选资格),必须重算
    for profile in Profile.objects.filter(user_id__in=user_ids):
        profile.refresh_status()
    return count
```

`chatapp/users/admin.py`:顶部 import 加 `from .services import review_photos`;`_review_photos` 改为:

```python
def _review_photos(modeladmin, request, queryset, status):
    count = review_photos(queryset, status, request.user)
    modeladmin.message_user(request, f"已处理 {count} 张照片")
```

- [ ] **Step 4: 生成并应用 migration**

Run:

```bash
python manage.py makemigrations users
python manage.py migrate
```

Expected: 生成 `users/0004_*.py`(含 `photo.reviewed_by`、`photo.reviewed_at`),migrate OK。

- [ ] **Step 5: 跑测试确认通过(含既有回归)**

Run: `python manage.py test users`
Expected: PASS(原有 PhotoAdminActionTests 也全绿)

- [ ] **Step 6: 提交**

```bash
git add chatapp/users
git commit -m "feat(users): extract review_photos service and add photo review audit fields"
```

---

### Task 5: 照片审核页(网格 + 单张/批量 + HTMX)

**Files:**
- Create: `chatapp/ops/templates/ops/photos.html`、`templates/ops/partials/photo_grid.html`
- Modify: `chatapp/ops/views.py`、`chatapp/ops/urls.py`、`chatapp/ops/tests.py`、`templates/ops/base.html`(导航加「照片审核」)、`static/ops/ops.css`(补照片行样式)

**Interfaces:**
- Consumes: `users.services.review_photos`、`Photo.reviewed_by/reviewed_at`
- Produces: `ops.views.photos`、`ops.views.photo_review`(POST `ids`(多个)+ `action` ∈ `approve|reject` + `status` 回显筛选)

- [ ] **Step 1: 写失败测试**

追加到 `chatapp/ops/tests.py`(import 补 `from users.models import Photo, PhotoStatus`):

```python
class OpsPhotoReviewTests(TestCase):
    def setUp(self):
        self.staff = make_staff()
        self.client.force_login(self.staff)
        self.user = User.objects.create_user(phone="13900139000")
        self.profile = Profile.objects.create(
            user=self.user, nickname="小红", gender="female", birthday="2000-01-01",
            city="上海", bio="你好", status=ProfileStatus.COMPLETE)
        self.approved = Photo.objects.create(user=self.user, file="photos/a.png",
                                             status=PhotoStatus.APPROVED)
        self.pending = Photo.objects.create(user=self.user, file="photos/b.png")

    def test_grid_shows_pending_by_default(self):
        resp = self.client.get("/ops/photos/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, f'value="{self.pending.id}"')
        self.assertNotContains(resp, f'value="{self.approved.id}"')

    def test_single_approve_records_reviewer(self):
        resp = self.client.post("/ops/photos/review",
                                {"ids": str(self.pending.id), "action": "approve",
                                 "status": "pending"})
        self.assertEqual(resp.status_code, 200)
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, PhotoStatus.APPROVED)
        self.assertEqual(self.pending.reviewed_by_id, self.staff.id)
        self.assertIsNotNone(self.pending.reviewed_at)

    def test_reject_only_approved_photo_makes_profile_incomplete(self):
        resp = self.client.post("/ops/photos/review",
                                {"ids": str(self.approved.id), "action": "reject",
                                 "status": "approved"})
        self.assertEqual(resp.status_code, 200)
        self.approved.refresh_from_db()
        self.profile.refresh_from_db()
        self.assertEqual(self.approved.status, PhotoStatus.REJECTED)
        self.assertEqual(self.profile.status, ProfileStatus.INCOMPLETE)

    def test_already_reviewed_photo_is_skipped_with_notice(self):
        resp = self.client.post("/ops/photos/review",
                                {"ids": str(self.approved.id), "action": "approve",
                                 "status": "pending"})
        self.assertContains(resp, "已跳过")
        self.approved.refresh_from_db()
        self.assertEqual(self.approved.reviewed_by_id, None)   # 未被重复审核
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python manage.py test ops.tests.OpsPhotoReviewTests`
Expected: FAIL —— 404(photos 路由还没建)

- [ ] **Step 3: 实现**

`chatapp/ops/views.py` 追加(import 补 `from users.models import Photo, PhotoStatus`、`from users.services import review_photos`):

```python
@staff_required
def photos(request):
    status = request.GET.get("status", PhotoStatus.PENDING)
    qs = Photo.objects.select_related("user", "reviewed_by").order_by("-created_at")
    if status in PhotoStatus.values:
        qs = qs.filter(status=status)
    return render(request, "ops/photos.html",
                  {"photos": qs[:120], "status": status, "skipped": 0})


@require_POST
@staff_required
def photo_review(request):
    ids = set(request.POST.getlist("ids"))
    action = request.POST.get("action")
    status_map = {"approve": PhotoStatus.APPROVED, "reject": PhotoStatus.REJECTED}
    skipped = 0
    if action in status_map and ids:
        pending = Photo.objects.filter(pk__in=ids, status=PhotoStatus.PENDING)
        skipped = len(ids) - pending.count()
        review_photos(pending, status_map[action], request.user)
    status = request.POST.get("status", PhotoStatus.PENDING)
    qs = Photo.objects.select_related("user", "reviewed_by").order_by("-created_at")
    if status in PhotoStatus.values:
        qs = qs.filter(status=status)
    return render(request, "ops/partials/photo_grid.html",
                  {"photos": qs[:120], "status": status, "skipped": skipped})
```

`chatapp/ops/urls.py` urlpatterns 末尾加:

```python
    path("photos/", views.photos, name="photos"),
    path("photos/review", views.photo_review, name="photo_review"),
```

`chatapp/ops/templates/ops/photos.html`:

```html
{% extends "ops/base.html" %}
{% block content %}
<h2>照片审核</h2>
<p class="ops-tabs">
  <a href="?status=pending" class="{% if status == 'pending' %}active{% endif %}">待审核</a>
  <a href="?status=approved" class="{% if status == 'approved' %}active{% endif %}">已通过</a>
  <a href="?status=rejected" class="{% if status == 'rejected' %}active{% endif %}">已驳回</a>
</p>
{% include "ops/partials/photo_grid.html" %}
{% endblock %}
```

`chatapp/ops/templates/ops/partials/photo_grid.html`:

```html
<div id="photo-grid">
  {% if skipped %}<p class="ops-warn">有 {{ skipped }} 张已不在待审核状态,已跳过</p>{% endif %}
  {% if photos %}
  {# 批量表单只放按钮;勾选框用 form="batch-form" 从行里关联进来,避免行内快捷按钮误带勾选值 #}
  <form id="batch-form" hx-post="{% url 'ops:photo_review' %}"
        hx-target="#photo-grid" hx-swap="outerHTML">
    <input type="hidden" name="status" value="{{ status }}">
    <p>
      <button type="submit" name="action" value="approve">通过所选</button>
      <button type="submit" name="action" value="reject" class="secondary">驳回所选</button>
    </p>
  </form>
  {% for photo in photos %}
  <div class="ops-photo-row">
    <label><input type="checkbox" name="ids" value="{{ photo.id }}" form="batch-form"></label>
    <img src="{{ photo.file.url }}" alt="photo#{{ photo.id }}">
    <div class="ops-photo-meta">
      <span>{{ photo.user.phone }} · {{ photo.created_at|date:"m-d H:i" }}</span>
      {% if photo.reviewed_by %}
        <small>审核:{{ photo.reviewed_by.phone }} · {{ photo.reviewed_at|date:"m-d H:i" }}</small>
      {% endif %}
      <form hx-post="{% url 'ops:photo_review' %}"
            hx-target="#photo-grid" hx-swap="outerHTML">
        <input type="hidden" name="ids" value="{{ photo.id }}">
        <input type="hidden" name="status" value="{{ status }}">
        <button type="submit" name="action" value="approve">通过</button>
        <button type="submit" name="action" value="reject" class="secondary">驳回</button>
      </form>
    </div>
  </div>
  {% endfor %}
  {% else %}
  <p>没有照片</p>
  {% endif %}
</div>
```

`base.html` 导航在「举报」链接后加:

```html
  <a href="{% url 'ops:photos' %}">照片审核{% if pending_photo_count %} <span class="ops-badge">{{ pending_photo_count }}</span>{% endif %}</a>
```

`ops.css` 追加:

```css
.ops-photo-row { display: flex; gap: 1rem; align-items: flex-start;
  border-bottom: 1px solid #ddd; padding: .75rem 0; }
.ops-photo-row img { max-height: 140px; border-radius: 6px; }
.ops-photo-meta { display: flex; flex-direction: column; gap: .35rem; }
.ops-photo-meta button { width: auto; padding: .25rem .75rem; margin: 0; }
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python manage.py test ops`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add chatapp/ops
git commit -m "feat(ops): photo review queue with single/batch approve/reject"
```

---

### Task 6: 用户搜索 + 用户详情页(只读)

**Files:**
- Create: `chatapp/ops/templates/ops/users_search.html`、`templates/ops/user_detail.html`、`templates/ops/partials/user_ban_panel.html`(本 Task 只有状态+历史展示,无表单)
- Modify: `chatapp/ops/views.py`、`chatapp/ops/urls.py`、`chatapp/ops/tests.py`、`templates/ops/base.html`(导航加「用户」)、`templates/ops/partials/user_card.html`(补详情链接)

**Interfaces:**
- Consumes: `ops/partials/user_card.html`
- Produces: `ops.views.users_search`、`ops.views.user_detail`、view 上下文函数 `_user_context(user)`(Task 7 复用);`ops/partials/user_ban_panel.html`(Task 7 会在其中加表单)

- [ ] **Step 1: 写失败测试**

追加到 `chatapp/ops/tests.py`:

```python
class OpsUserSearchTests(TestCase):
    def setUp(self):
        self.client.force_login(make_staff())
        self.alice = User.objects.create_user(phone="13800138000")
        Profile.objects.create(user=self.alice, nickname="小红")

    def test_search_by_phone_exact(self):
        resp = self.client.get("/ops/users/", {"q": "13800138000"})
        self.assertContains(resp, "小红")

    def test_search_by_nickname_substring(self):
        resp = self.client.get("/ops/users/", {"q": "小"})
        self.assertContains(resp, "13800138000")

    def test_partial_phone_does_not_match(self):
        resp = self.client.get("/ops/users/", {"q": "13800138"})
        self.assertNotContains(resp, "小红")


class OpsUserDetailTests(TestCase):
    def setUp(self):
        self.client.force_login(make_staff())
        self.alice = User.objects.create_user(phone="13800138000")
        self.bob = User.objects.create_user(phone="13900139000")
        Profile.objects.create(user=self.alice, nickname="小红")
        Report.objects.create(reporter=self.bob, target=self.alice,
                              type=ReportType.FRAUD, detail="骗钱")

    def test_detail_shows_profile_reports_and_links(self):
        resp = self.client.get(f"/ops/users/{self.alice.id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "小红")
        self.assertContains(resp, "骗钱")
        self.assertContains(resp, "13900139000")   # 举报人
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python manage.py test ops.tests.OpsUserSearchTests ops.tests.OpsUserDetailTests`
Expected: FAIL —— 404(users 路由还没建)

- [ ] **Step 3: 实现**

`chatapp/ops/views.py` 追加(import 补 `from django.db.models import Count, Q`、`from moderation.models import Block`):

```python
@staff_required
def users_search(request):
    q = request.GET.get("q", "").strip()
    results = []
    if q:
        results = (User.objects.filter(Q(phone=q) | Q(profile__nickname__icontains=q))
                   .select_related("profile").order_by("id")[:50])
    return render(request, "ops/users_search.html", {"q": q, "results": results})


@staff_required
def user_detail(request, user_id):
    user = get_object_or_404(User.objects.select_related("profile"), pk=user_id)
    return render(request, "ops/user_detail.html", _user_context(user))


def _user_context(user):
    """用户详情页上下文;Task 7 的封禁局部刷新也复用它。"""
    return {
        "target_user": user,
        "target_profile": getattr(user, "profile", None),
        "ban_logs": BanLog.objects.filter(user=user).select_related("operator")[:20],
        "reports_received": Report.objects.filter(target=user).select_related("reporter")[:20],
        "reports_made": Report.objects.filter(reporter=user).select_related("target")[:20],
        "blocks_made": Block.objects.filter(blocker=user).select_related("blocked")[:20],
        "blocks_received": Block.objects.filter(blocked=user).select_related("blocker")[:20],
    }
```

import 行同时补 `from accounts.models import User`(Task 1-5 还没用过 User 类)。

`chatapp/ops/urls.py` urlpatterns 末尾加:

```python
    path("users/", views.users_search, name="users"),
    path("users/<int:user_id>/", views.user_detail, name="user_detail"),
```

`chatapp/ops/templates/ops/users_search.html`:

```html
{% extends "ops/base.html" %}
{% block content %}
<h2>用户查询</h2>
<form method="get">
  <input type="search" name="q" value="{{ q }}" placeholder="手机号(完整)或昵称">
  <button type="submit">搜索</button>
</form>
{% if q %}
<table>
  <thead><tr><th>ID</th><th>手机号</th><th>昵称</th><th>状态</th><th></th></tr></thead>
  <tbody>
  {% for u in results %}
    <tr>
      <td>{{ u.id }}</td>
      <td>{{ u.phone }}</td>
      <td>{% firstof u.profile.nickname "—" %}</td>
      <td>{% if u.profile %}{{ u.profile.get_status_display }}{% else %}—{% endif %}</td>
      <td><a href="{% url 'ops:user_detail' u.id %}">详情</a></td>
    </tr>
  {% empty %}<tr><td colspan="5">无结果</td></tr>{% endfor %}
  </tbody>
</table>
{% endif %}
{% endblock %}
```

`chatapp/ops/templates/ops/user_detail.html`:

```html
{% extends "ops/base.html" %}
{% block content %}
<h2>用户 #{{ target_user.id }}</h2>
{% include "ops/partials/user_card.html" with user_obj=target_user profile=target_profile %}
<article>
  <h3>封禁管理</h3>
  {% include "ops/partials/user_ban_panel.html" %}
</article>
<article>
  <h3>举报关系</h3>
  <p>被举报({{ reports_received|length }} 条):</p>
  <table>
    <thead><tr><th>时间</th><th>类型</th><th>举报人</th><th>状态</th></tr></thead>
    <tbody>
    {% for r in reports_received %}
      <tr><td>{{ r.created_at|date:"m-d H:i" }}</td><td>{{ r.get_type_display }}</td>
          <td>{{ r.reporter.phone }}</td><td>{{ r.get_status_display }}</td></tr>
    {% empty %}<tr><td colspan="4">无记录</td></tr>{% endfor %}
    </tbody>
  </table>
  <p>发出的举报({{ reports_made|length }} 条):</p>
  <table>
    <thead><tr><th>时间</th><th>类型</th><th>被举报人</th><th>状态</th></tr></thead>
    <tbody>
    {% for r in reports_made %}
      <tr><td>{{ r.created_at|date:"m-d H:i" }}</td><td>{{ r.get_type_display }}</td>
          <td>{{ r.target.phone }}</td><td>{{ r.get_status_display }}</td></tr>
    {% empty %}<tr><td colspan="4">无记录</td></tr>{% endfor %}
    </tbody>
  </table>
</article>
<article>
  <h3>拉黑关系</h3>
  <p>拉黑的人:{% for b in blocks_made %}{{ b.blocked.phone }}({{ b.created_at|date:"m-d" }}) {% empty %}—{% endfor %}</p>
  <p>被谁拉黑:{% for b in blocks_received %}{{ b.blocker.phone }}({{ b.created_at|date:"m-d" }}) {% empty %}—{% endfor %}</p>
</article>
{% endblock %}
```

`chatapp/ops/templates/ops/partials/user_ban_panel.html`(本 Task 无表单,Task 7 加):

```html
<div id="ban-panel">
  {% if error %}<p class="ops-error">{{ error }}</p>{% endif %}
  <p>当前状态:{% if target_profile %}{{ target_profile.get_status_display }}{% else %}无资料{% endif %}
    {% if target_profile.ban_reason %}· 原因:{{ target_profile.ban_reason }}{% endif %}</p>
  <h4>封禁历史</h4>
  <table>
    <thead><tr><th>时间</th><th>动作</th><th>原因</th><th>操作人</th></tr></thead>
    <tbody>
    {% for log in ban_logs %}
      <tr><td>{{ log.created_at|date:"Y-m-d H:i" }}</td><td>{{ log.get_action_display }}</td>
          <td>{{ log.reason|default:"—" }}</td><td>{{ log.operator.phone|default:"—" }}</td></tr>
    {% empty %}<tr><td colspan="4">无记录</td></tr>{% endfor %}
    </tbody>
  </table>
</div>
```

`user_card.html` 在 `</div>`(ops-photos 后)前加:

```html
  <a href="{% url 'ops:user_detail' user_obj.id %}">查看用户详情 →</a>
```

`base.html` 导航在「照片审核」后加:

```html
  <a href="{% url 'ops:users' %}">用户</a>
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python manage.py test ops`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add chatapp/ops
git commit -m "feat(ops): user search and profile detail page"
```

---

### Task 7: 用户封禁 / 解封(HTMX)

**Files:**
- Modify: `chatapp/ops/views.py`、`chatapp/ops/urls.py`、`chatapp/ops/tests.py`、`templates/ops/partials/user_ban_panel.html`

**Interfaces:**
- Consumes: `ops.views._apply_status_change`(Task 3)、`_user_context`(Task 6)
- Produces: `ops.views.user_ban`(POST `action` ∈ `ban_light|ban_heavy|unban` + `reason`)

- [ ] **Step 1: 写失败测试**

追加到 `chatapp/ops/tests.py`:

```python
class OpsUserBanTests(TestCase):
    def setUp(self):
        self.staff = make_staff()
        self.client.force_login(self.staff)
        self.user = User.objects.create_user(phone="13900139000")
        self.profile = Profile.objects.create(
            user=self.user, nickname="小红", gender="female", birthday="2000-01-01",
            city="上海", bio="你好", status=ProfileStatus.COMPLETE)
        Photo.objects.create(user=self.user, file="photos/a.png", status=PhotoStatus.APPROVED)

    def test_ban_light_records_log_without_kick(self):
        with patch("moderation.services._dispatch_async") as dispatch:
            resp = self.client.post(f"/ops/users/{self.user.id}/ban",
                                    {"action": "ban_light", "reason": "骚扰他人"})
        self.assertEqual(resp.status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.status, ProfileStatus.BANNED_LIGHT)
        self.assertEqual(self.profile.ban_reason, "骚扰他人")
        self.assertTrue(BanLog.objects.filter(user=self.user, action=BanAction.BAN_LIGHT,
                                              operator=self.staff).exists())
        dispatch.assert_not_called()

    def test_ban_heavy_kicks_im(self):
        with patch("moderation.services._dispatch_async") as dispatch:
            self.client.post(f"/ops/users/{self.user.id}/ban",
                             {"action": "ban_heavy", "reason": "严重违规"})
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.status, ProfileStatus.BANNED_HEAVY)
        dispatch.assert_called_once_with(im_client.kick_user, self.user.im_user_id)

    def test_ban_requires_reason(self):
        with patch("moderation.services._dispatch_async") as dispatch:
            resp = self.client.post(f"/ops/users/{self.user.id}/ban",
                                    {"action": "ban_heavy", "reason": "  "})
        self.assertContains(resp, "必须填写原因")
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.status, ProfileStatus.COMPLETE)
        dispatch.assert_not_called()

    def test_unban_recomputes_status_and_clears_reason(self):
        with patch("moderation.services._dispatch_async"):
            self.client.post(f"/ops/users/{self.user.id}/ban",
                             {"action": "ban_light", "reason": "先封"})
        resp = self.client.post(f"/ops/users/{self.user.id}/ban",
                                {"action": "unban", "reason": ""})
        self.assertEqual(resp.status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.status, ProfileStatus.COMPLETE)   # 资料齐全+有照片 → 重算回已完善
        self.assertEqual(self.profile.ban_reason, "")
        self.assertTrue(BanLog.objects.filter(user=self.user, action=BanAction.UNBAN).exists())
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python manage.py test ops.tests.OpsUserBanTests`
Expected: FAIL —— 404(user ban 路由还没建)

- [ ] **Step 3: 实现**

`chatapp/ops/views.py` 追加:

```python
@require_POST
@staff_required
def user_ban(request, user_id):
    user = get_object_or_404(User, pk=user_id)
    action = request.POST.get("action")
    reason = request.POST.get("reason", "").strip()
    error = None
    if action == "unban":
        _apply_status_change(user, action, reason, request.user)
    elif action in ("ban_light", "ban_heavy"):
        if not reason:
            error = "封禁必须填写原因"
        else:
            _apply_status_change(user, action, reason, request.user)
    else:
        error = "未知操作"
    ctx = _user_context(user)
    ctx["error"] = error
    return render(request, "ops/partials/user_ban_panel.html", ctx)
```

`chatapp/ops/urls.py` urlpatterns 末尾加:

```python
    path("users/<int:user_id>/ban", views.user_ban, name="user_ban"),
```

`user_ban_panel.html` 在「当前状态」段后插入表单:

```html
  <form hx-post="{% url 'ops:user_ban' target_user.id %}"
        hx-target="#ban-panel" hx-swap="outerHTML">
    <label>原因(封禁必填;解封可留空)
      <input type="text" name="reason" maxlength="200"></label>
    <button type="submit" name="action" value="ban_light">轻度封禁</button>
    <button type="submit" name="action" value="ban_heavy" class="secondary">重度封禁</button>
    <button type="submit" name="action" value="unban" class="outline">解封</button>
  </form>
  <p><small>重度封禁会自动踢掉其 IM 登录(重封最长 7 天内还能聊的问题由踢下线兜底)。</small></p>
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python manage.py test ops`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add chatapp/ops
git commit -m "feat(ops): user ban/unban actions with audit trail (HTMX)"
```

---

### Task 8: 操作日志页

**Files:**
- Create: `chatapp/ops/templates/ops/logs.html`
- Modify: `chatapp/ops/views.py`、`chatapp/ops/urls.py`、`chatapp/ops/tests.py`、`templates/ops/base.html`(导航加「日志」)

**Interfaces:**
- Consumes: `moderation.models.BanLog/BanAction/Block`
- Produces: `ops.views.logs`(筛选参数 `action` / `phone` / `date`)

- [ ] **Step 1: 写失败测试**

追加到 `chatapp/ops/tests.py`:

```python
class OpsLogsTests(TestCase):
    def setUp(self):
        self.client.force_login(make_staff())
        self.user = User.objects.create_user(phone="13900139000")
        BanLog.objects.create(user=self.user, action=BanAction.BAN_LIGHT, reason="骚扰")
        BanLog.objects.create(user=self.user, action=BanAction.UNBAN, reason="申诉通过")

    def test_logs_list_shows_history(self):
        resp = self.client.get("/ops/logs/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "骚扰")
        self.assertContains(resp, "申诉通过")

    def test_filter_by_action(self):
        resp = self.client.get("/ops/logs/", {"action": "unban"})
        self.assertContains(resp, "申诉通过")
        self.assertNotContains(resp, "骚扰")   # 轻度封禁行的原因文本被过滤掉(动作名在筛选下拉里恒有,不能拿来断言)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python manage.py test ops.tests.OpsLogsTests`
Expected: FAIL —— 404(logs 路由还没建)

- [ ] **Step 3: 实现**

`chatapp/ops/views.py` 追加(import 补 `from django.core.exceptions import ValidationError`、`from moderation.models import BanAction`):

```python
@staff_required
def logs(request):
    action = request.GET.get("action", "")
    phone = request.GET.get("phone", "").strip()
    date = request.GET.get("date", "").strip()
    qs = BanLog.objects.select_related("user", "operator").order_by("-created_at")
    if action in BanAction.values:
        qs = qs.filter(action=action)
    if phone:
        qs = qs.filter(user__phone=phone)
    if date:
        try:
            qs = qs.filter(created_at__date=date)
        except ValidationError:
            date = ""
    blocks = Block.objects.select_related("blocker", "blocked").order_by("-created_at")[:100]
    return render(request, "ops/logs.html", {
        "ban_logs": qs[:200], "blocks": blocks,
        "action": action, "phone": phone, "date": date,
        "actions": BanAction.choices,
    })
```

`chatapp/ops/urls.py` urlpatterns 末尾加:

```python
    path("logs/", views.logs, name="logs"),
```

`chatapp/ops/templates/ops/logs.html`:

```html
{% extends "ops/base.html" %}
{% block content %}
<h2>操作日志</h2>
<form method="get" class="ops-grid-2">
  <label>动作
    <select name="action">
      <option value="">全部</option>
      {% for value, label in actions %}
        <option value="{{ value }}" {% if action == value %}selected{% endif %}>{{ label }}</option>
      {% endfor %}
    </select>
  </label>
  <label>手机号<input type="text" name="phone" value="{{ phone }}" placeholder="完整手机号"></label>
  <label>日期<input type="date" name="date" value="{{ date }}"></label>
  <button type="submit">筛选</button>
</form>
<h3>封禁审计流水</h3>
<table>
  <thead><tr><th>时间</th><th>用户</th><th>动作</th><th>原因</th><th>操作人</th></tr></thead>
  <tbody>
  {% for log in ban_logs %}
    <tr><td>{{ log.created_at|date:"Y-m-d H:i" }}</td><td>{{ log.user.phone }}</td>
        <td>{{ log.get_action_display }}</td><td>{{ log.reason|default:"—" }}</td>
        <td>{{ log.operator.phone|default:"—" }}</td></tr>
  {% empty %}<tr><td colspan="5">无记录</td></tr>{% endfor %}
  </tbody>
</table>
<h3>拉黑对账(只读;拉黑须走 App 接口才会同步 IM)</h3>
<table>
  <thead><tr><th>时间</th><th>拉黑方</th><th>被拉黑方</th></tr></thead>
  <tbody>
  {% for b in blocks %}
    <tr><td>{{ b.created_at|date:"Y-m-d H:i" }}</td><td>{{ b.blocker.phone }}</td>
        <td>{{ b.blocked.phone }}</td></tr>
  {% empty %}<tr><td colspan="3">无记录</td></tr>{% endfor %}
  </tbody>
</table>
{% endblock %}
```

`base.html` 导航在「用户」后加:

```html
  <a href="{% url 'ops:logs' %}">日志</a>
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python manage.py test ops`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add chatapp/ops
git commit -m "feat(ops): audit logs page (ban history + block reconciliation)"
```

---

### Task 9: 全量回归 + 文档收尾

**Files:**
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: 前 8 个 Task 的全部产出
- Produces: 可交付的 `/ops/` 审核台 + 文档

- [ ] **Step 1: 全量测试(后端 + 确认前端不受影响)**

```bash
cd D:/pycharmproject/chat_app/chatapp && python manage.py test
```

Expected: 全部 PASS(原 153 + 本计划新增 ≈ 25 个用例)。

- [ ] **Step 2: 手测冒烟(需后端 runserver + 浏览器)**

启动/复用 `python manage.py runserver 0.0.0.0:8000`,浏览器开 `http://127.0.0.1:8000/ops/`:

1. 未登录 → 跳登录页;用非 staff 账号登录 → 提示「该账号无运营权限」
2. 用 `13900000000` 登录 → 进举报队列;导航角标显示待处理数
3. 打开一条举报详情 → 双方资料卡/历史都在;「标记已处理」不刷新整页生效
4. 照片页:传一张新图(App 端或直接造数据),单张「通过」后卡片从队列消失
5. 用户页搜手机号 → 详情页封禁(轻)→ 状态与历史即时更新;解封 → 状态重算回已完善
6. 日志页出现刚才的封禁/解封流水
7. 顺带确认 Django admin 照片 action 仍可用(随便点一个)

- [ ] **Step 3: 更新 CLAUDE.md**

「当前进度」段的 M3 描述后追加一句:完成 `ops` 运营审核台(`/ops/`,is_staff 登录;举报处理/照片审核/用户封禁/操作日志)。并在「合规与审核(M3 已实测)」小节末尾新增:

```markdown
## 运营审核台 /ops/(M3 后新增)

- 独立 Django app `ops`:服务端模板 + HTMX 局部刷新;静态资源 vendored 在 `ops/static/ops/vendor/`(Pico.css/htmx),**不依赖 CDN,生产需 collectstatic**
- 登录复用 Django 账号体系,**判据 `is_staff`**;建运营账号 = 建一个 is_staff 用户(手机号+密码)
- 写操作与 admin 同源:`log_ban_change`(封禁审计+踢 IM)、`users/services.py::review_photos`(照片审核+资料状态重算+`reviewed_by/at` 审计)
- 解封会 `refresh_status()` 重算 complete/incomplete(admin 是手改状态下拉,别混用)
- 测试纪律:任何触发 IM 的路径 mock `moderation.services._dispatch_async`
```

- [ ] **Step 4: 提交**

```bash
cd D:/pycharmproject/chat_app
git add CLAUDE.md
git commit -m "docs: document ops console in CLAUDE.md"
```

- [ ] **Step 5: 分支收尾**

沿用仓库节奏(短生命周期分支):用户手测通过后合回 master:

```bash
git checkout master && git merge --no-ff ops-console
```

---

## 附:本计划新增路由/接口一览

| 路由 | 方法 | 说明 |
|---|---|---|
| `/ops/login/` `/ops/logout/` | GET/POST | 登录(仅 is_staff)/登出 |
| `/ops/` | GET | 302 → `/ops/reports/` |
| `/ops/reports/` | GET | 举报队列;`?status=pending|handled|all&type=` |
| `/ops/reports/<id>/` | GET | 举报详情 |
| `/ops/reports/<id>/handle` | POST | 标记已处理(note) |
| `/ops/reports/<id>/ban` | POST | 快捷封禁(level + reason) |
| `/ops/photos/` | GET | 照片网格;`?status=` |
| `/ops/photos/review` | POST | 单张/批量审核(`ids` + `action` + `status` 回显) |
| `/ops/users/` | GET | 搜索;`?q=` |
| `/ops/users/<id>/` | GET | 用户详情 |
| `/ops/users/<id>/ban` | POST | 封禁/解封(`action` + `reason`) |
| `/ops/logs/` | GET | 审计日志;`?action=&phone=&date=` |
