# 运营审核台 UI 改版(宝塔式亮色)实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `/ops/` 从 Pico 默认观感改成宝塔面板式三区布局(侧边栏 + 顶栏 + 内容区)+ 亮色蓝主题,零行为改动。

**Architecture:** 重写 `base.html` 为三区壳(新增 `page_title` block),登录页独立成页,`ops.css` 整体重写并删除 Pico。仅改模板与静态样式;视图/路由/HTMX/文案全部不动,既有 180 个后端测试作为行为回归护栏。

**Tech Stack:** Django 模板(纯 CSS,零新依赖;图标用内联 SVG)

**Spec:** `docs/superpowers/specs/2026-09-11-ops-console-ui-design.md`
**分支:** 在现有未合并的 `ops-console` 分支上继续(不新开分支)。

## Global Constraints

- **文案一字不改**:所有中文文案保持原样(测试断言依赖它们,是本次改版的行为护栏)
- **零行为改动**:视图、URL、HTMX 属性、CSRF、表单 name/value 全部不动;唯一 JS 仍是 htmx.min.js
- **零新依赖**:不加 npm/pip 包;图标为内联 SVG(16px,feather 风格,MIT)
- 删除 `ops/static/ops/vendor/pico.min.css` 与 base 中的 pico `<link>`
- 配色以 spec §3 为准:主色 `#2c7be5`(hover `#1a68d1`)、页面底 `#f5f6f8`、卡片 `#fff`、边框 `#e8eaed`、正文 `#2b2f36`、次要 `#6b7280`;语义:绿 `#1e9e57` / 橙 `#e8890c` / 红 `#d93025`
- 桌面优先(不处理移动端);命令 cwd 默认 `chatapp/`
- 每个 Task 独立提交

---

### Task 1: 三区壳 + 全局样式 + 登录页独立

**Files:**
- Modify: `chatapp/ops/templates/ops/base.html`(重写)
- Modify: `chatapp/ops/templates/ops/login.html`(脱离 base,独立成页)
- Modify: `chatapp/ops/static/ops/ops.css`(整个重写)
- Delete: `chatapp/ops/static/ops/vendor/pico.min.css`

**Interfaces:**
- Consumes: 现有 `ops:` URL 名(reports/photos/users/logs/login/logout)、context processor 的 `pending_report_count`/`pending_photo_count`
- Produces: 新 CSS 组件类:`.layout/.sidebar/.brand/.menu/.ops-badge/.main/.topbar/.page-title/.topbar-right/.content`(结构)、`.tag/.tag-gray/.tag-green/.tag-orange/.tag-red`(状态胶囊)、按钮变体 `button.secondary/.danger/.warn/.ok`、保留旧类名重定义(`.ops-tabs/.ops-photo-row/.ops-photo-meta/.ops-photos/.ops-user-card/.ops-error/.ops-warn/.ops-grid-2`);`{% block page_title %}`(Task 2 各页使用)

- [ ] **Step 1: 重写 base.html**

```html
{% load static %}
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}运营审核台{% endblock %}</title>
  <link rel="stylesheet" href="{% static 'ops/ops.css' %}">
  <script src="{% static 'ops/vendor/htmx.min.js' %}"></script>
</head>
<body hx-headers='{"X-CSRFToken": "{{ csrf_token }}"}'>
<div class="layout">
  <aside class="sidebar">
    <div class="brand">运营审核台</div>
    <nav class="menu">
      <a href="{% url 'ops:reports' %}" class="{% if '/ops/reports' in request.path %}active{% endif %}">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
             stroke-linecap="round" stroke-linejoin="round"><path d="M4 22V4"/><path d="M4 4c4-2 8 2 12 0v10c-4 2-8-2-12 0"/></svg>
        举报{% if pending_report_count %}<span class="ops-badge">{{ pending_report_count }}</span>{% endif %}
      </a>
      <a href="{% url 'ops:photos' %}" class="{% if '/ops/photos' in request.path %}active{% endif %}">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
             stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="m21 15-5-5L5 21"/></svg>
        照片审核{% if pending_photo_count %}<span class="ops-badge">{{ pending_photo_count }}</span>{% endif %}
      </a>
      <a href="{% url 'ops:users' %}" class="{% if '/ops/users' in request.path %}active{% endif %}">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
             stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
        用户
      </a>
      <a href="{% url 'ops:logs' %}" class="{% if '/ops/logs' in request.path %}active{% endif %}">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
             stroke-linecap="round" stroke-linejoin="round"><path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/></svg>
        日志
      </a>
    </nav>
  </aside>
  <div class="main">
    <header class="topbar">
      <div class="page-title">{% block page_title %}{% endblock %}</div>
      <div class="topbar-right">
        {% if user.is_authenticated %}
          <span class="who">{{ user.phone }}</span>
          <form method="post" action="{% url 'ops:logout' %}">
            {% csrf_token %}
            <button type="submit" class="secondary">退出</button>
          </form>
        {% endif %}
      </div>
    </header>
    <main class="content">
      {% block content %}{% endblock %}
    </main>
  </div>
</div>
</body>
</html>
```

- [ ] **Step 2: login.html 独立成页(不再 extends base)**

```html
{% load static %}
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>登录 · 运营审核台</title>
  <link rel="stylesheet" href="{% static 'ops/ops.css' %}">
</head>
<body class="login-body">
<div class="login-card">
  <h1>运营审核台</h1>
  <form method="post">
    {% csrf_token %}
    {% if form.non_field_errors %}<p class="ops-error">{{ form.non_field_errors.0 }}</p>{% endif %}
    <label>手机号<input type="text" name="username" autofocus autocomplete="username"></label>
    <label>密码<input type="password" name="password" autocomplete="current-password"></label>
    <button type="submit">登录</button>
  </form>
</div>
</body>
</html>
```

- [ ] **Step 3: 重写 ops.css(自包含,约 140 行)**

```css
/* ===== 基础 ===== */
* { box-sizing: border-box; }
body { margin: 0; background: #f5f6f8; color: #2b2f36; font-size: 14px;
  font-family: -apple-system, "Segoe UI", "Microsoft YaHei", "PingFang SC", sans-serif; }
a { color: #2c7be5; text-decoration: none; }
a:hover { color: #1a68d1; }
h3 { margin: 0 0 12px; font-size: 15px; font-weight: 600; }
h4 { margin: 12px 0 8px; font-size: 14px; font-weight: 600; }
small { color: #6b7280; }

/* ===== 布局骨架 ===== */
.layout { display: flex; min-height: 100vh; }
.sidebar { flex: 0 0 220px; background: #fff; border-right: 1px solid #e8eaed; }
.brand { display: flex; align-items: center; gap: 8px; height: 56px; padding: 0 20px;
  border-bottom: 1px solid #e8eaed; font-size: 16px; font-weight: 700; }
.brand::before { content: ""; width: 8px; height: 8px; border-radius: 2px; background: #2c7be5; }
.menu { padding: 8px 0; }
.menu a { display: flex; align-items: center; gap: 10px; height: 40px; padding: 0 16px;
  border-left: 3px solid transparent; color: #2b2f36; }
.menu a svg { flex: 0 0 16px; color: #6b7280; }
.menu a:hover { background: #f5f7fa; }
.menu a.active { background: #e8f0fe; border-left-color: #2c7be5; color: #2c7be5; font-weight: 600; }
.menu a.active svg { color: #2c7be5; }
.ops-badge { margin-left: auto; min-width: 18px; padding: 0 6px; border-radius: 9px;
  background: #d93025; color: #fff; font-size: 12px; line-height: 18px; text-align: center; }
.main { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.topbar { display: flex; align-items: center; height: 56px; padding: 0 20px;
  background: #fff; border-bottom: 1px solid #e8eaed; }
.page-title { font-size: 15px; font-weight: 600; }
.topbar-right { display: flex; align-items: center; gap: 12px; margin-left: auto; }
.topbar-right .who { color: #6b7280; font-size: 13px; }
.topbar-right form { margin: 0; }
.content { padding: 20px; }

/* ===== 卡片 ===== */
article, .ops-user-card { background: #fff; border: 1px solid #e8eaed; border-radius: 8px;
  padding: 16px; margin: 0 0 16px; box-shadow: 0 1px 2px rgba(16, 24, 40, .04); }
#photo-grid { background: #fff; border: 1px solid #e8eaed; border-radius: 8px;
  padding: 16px; margin-bottom: 16px; box-shadow: 0 1px 2px rgba(16, 24, 40, .04); }
.ops-grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }

/* ===== 按钮 ===== */
button { height: 30px; padding: 0 12px; border: 1px solid #2c7be5; border-radius: 4px;
  background: #2c7be5; color: #fff; font: inherit; font-size: 13px; cursor: pointer; }
button:hover { background: #1a68d1; border-color: #1a68d1; }
button.secondary { background: #fff; border-color: #d5d9e0; color: #2b2f36; }
button.secondary:hover { border-color: #2c7be5; color: #2c7be5; background: #fff; }
button.danger { background: #fff; border-color: #f0b4b0; color: #d93025; }
button.danger:hover { background: #fdecea; border-color: #d93025; }
button.warn { background: #fff; border-color: #f3d19e; color: #e8890c; }
button.warn:hover { background: #fdf3e2; border-color: #e8890c; }
button.ok { background: #fff; border-color: #a8ddbd; color: #1e9e57; }
button.ok:hover { background: #e6f6ec; border-color: #1e9e57; }

/* ===== 表单 ===== */
label { display: block; margin: 0 0 10px; font-size: 13px; }
input[type="text"], input[type="search"], input[type="password"], input[type="date"], select {
  display: block; width: 100%; height: 32px; margin-top: 4px; padding: 0 10px;
  border: 1px solid #d5d9e0; border-radius: 4px; background: #fff; color: #2b2f36;
  font: inherit; font-size: 13px; }
input:focus, select:focus { outline: none; border-color: #2c7be5;
  box-shadow: 0 0 0 2px rgba(44, 123, 229, .15); }
input[type="checkbox"] { width: 16px; height: 16px; margin: 6px 0 0; accent-color: #2c7be5; }

/* ===== 表格 ===== */
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th { padding: 8px 12px; background: #fafbfc; border-bottom: 1px solid #e8eaed;
  color: #6b7280; font-weight: 600; text-align: left; white-space: nowrap; }
td { padding: 8px 12px; border-bottom: 1px solid #f0f2f5; vertical-align: top; }
tbody tr:hover { background: #f5f9ff; }
tbody tr:last-child td { border-bottom: none; }

/* ===== tabs / 胶囊 / 提示 ===== */
.ops-tabs { display: flex; flex-wrap: wrap; align-items: center; gap: 4px; margin: 0 0 14px; }
.ops-tabs a { padding: 4px 10px; border-radius: 4px; font-size: 13px; color: #2b2f36; }
.ops-tabs a:hover { color: #2c7be5; }
.ops-tabs a.active { background: #e8f0fe; color: #2c7be5; font-weight: 600; }
.ops-tabs-sep { display: none; }
.tag { display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 12px; line-height: 18px; }
.tag-gray { background: #f0f2f5; color: #6b7280; }
.tag-green { background: #e6f6ec; color: #1e9e57; }
.tag-orange { background: #fdf3e2; color: #e8890c; }
.tag-red { background: #fdecea; color: #d93025; }
.ops-error { margin: 0 0 10px; color: #d93025; font-weight: 600; }
.ops-warn { margin: 0 0 10px; color: #e8890c; }

/* ===== 用户卡 / 照片 ===== */
.ops-photos { display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0; }
.ops-photos img { max-height: 96px; border: 1px solid #e8eaed; border-radius: 6px; }
.ops-photo-row { display: flex; gap: 16px; align-items: flex-start; padding: 12px 0;
  border-bottom: 1px solid #f0f2f5; }
.ops-photo-row:last-child { border-bottom: none; }
.ops-photo-row img { max-height: 140px; border: 1px solid #e8eaed; border-radius: 6px; }
.ops-photo-meta { display: flex; flex-direction: column; gap: 6px; font-size: 13px; }
.ops-photo-meta form { display: flex; gap: 8px; }

/* ===== 登录页 ===== */
.login-body { display: flex; align-items: center; justify-content: center; min-height: 100vh; }
.login-card { width: 380px; padding: 32px; background: #fff; border: 1px solid #e8eaed;
  border-radius: 8px; box-shadow: 0 4px 16px rgba(16, 24, 40, .06); }
.login-card h1 { margin: 0 0 24px; font-size: 18px; text-align: center; }
.login-card button { width: 100%; height: 36px; margin-top: 6px; }
```

- [ ] **Step 4: 删除 Pico + 验证测试仍绿**

```bash
git rm chatapp/ops/static/ops/vendor/pico.min.css
cd chatapp && python manage.py test ops
```

Expected: 全部 PASS(26 个;文案与 name/value 未动,断言不受影响)

- [ ] **Step 5: 截图目检(登录页 + 壳)**

若后端未运行:`cd chatapp && python manage.py runserver 0.0.0.0:8000`(后台)。
建临时运营账号(截图用,Task 3 会删除):

```bash
python manage.py shell -c "from accounts.models import User; u = User.objects.create_user(phone='13000000001', is_staff=True); u.set_password('ops-temp-123'); u.save()"
```

用 Playwright:打开 `http://127.0.0.1:8000/ops/login/` 截图 → 填 `13000000001` / `ops-temp-123` 登录 → 截图 `/ops/reports/`。用 Read 查看截图,对照 spec §2/§3 检查:左侧边栏+顶栏结构、白色卡片、蓝色选中菜单、红色角标。有问题当场修 CSS 并重复截图。

- [ ] **Step 6: 提交**

```bash
git add chatapp/ops
git commit -m "feat(ops): Baota-style light shell with sidebar and topbar"
```

---

### Task 2: 各页面适配(page_title + 状态胶囊 + 危险按钮 + 卡片包裹)

**Files:**
- Modify: `chatapp/ops/templates/ops/reports_list.html`、`report_detail.html`、`photos.html`、`users_search.html`、`user_detail.html`、`logs.html`
- Modify: `chatapp/ops/templates/ops/partials/user_card.html`、`user_ban_panel.html`、`report_panel.html`、`photo_grid.html`

**Interfaces:**
- Consumes: Task 1 的 `{% block page_title %}`、`.tag-*` 胶囊类、`button.danger/.warn/.ok`
- Produces: 全部页面的最终视觉形态(无新接口)

- [ ] **Step 1: 六个页面页头改造(文案一字不改)**

各页面统一模式:在 `{% extends "ops/base.html" %}` 后加 `{% block page_title %}...{% endblock %}`,并删掉正文里的 `<h2>`:

| 文件 | page_title |
|---|---|
| reports_list.html | `举报队列` |
| report_detail.html | `举报详情 #{{ report.id }}` |
| photos.html | `照片审核` |
| users_search.html | `用户查询` |
| user_detail.html | `用户 #{{ target_user.id }}` |
| logs.html | `操作日志` |

示例(reports_list.html,其余同样式):

```html
{% extends "ops/base.html" %}
{% block page_title %}举报队列{% endblock %}
{% block content %}
<p class="ops-tabs">
  ...(原样保留)...
</p>
<article>
<table>
  ...(原表格原样保留)...
</table>
</article>
{% endblock %}
```

即:删 `<h2>...</h2>` 一行;表格外包一层 `<article></article>`。**注意 reports_list 只包表格**(tabs 留在卡片外)。

- [ ] **Step 2: 卡片包裹补齐(logs / users_search)**

`logs.html`:筛选 `<form method="get" class="ops-grid-2">...</form>` 外套 `<article>`;两个 `<h3>+<table>` 块各自外套 `<article>`(即三个卡片)。

`users_search.html`:`<form method="get">...</form>` 与结果 `<table>` 一起外套一个 `<article>`。

- [ ] **Step 3: 状态改彩色胶囊**

`report_detail.html` 状态行:

```html
<p><strong>类型:</strong>{{ report.get_type_display }}
   　<strong>时间:</strong>{{ report.created_at|date:"Y-m-d H:i" }}
   　<strong>状态:</strong><span class="tag {% if report.status == 'pending' %}tag-orange{% else %}tag-green{% endif %}">{{ report.get_status_display }}</span></p>
```

`user_card.html` 状态行:

```html
<p>状态:<span class="tag {% if profile.status == 'complete' %}tag-green{% elif profile.status == 'banned_light' %}tag-orange{% elif profile.status == 'banned_heavy' %}tag-red{% else %}tag-gray{% endif %}">{{ profile.get_status_display }}</span>
  {% if profile.ban_reason %}· 原因:{{ profile.ban_reason }}{% endif %}</p>
```

`user_ban_panel.html` 当前状态行(同样映射):

```html
<p>当前状态:{% if target_profile %}<span class="tag {% if target_profile.status == 'complete' %}tag-green{% elif target_profile.status == 'banned_light' %}tag-orange{% elif target_profile.status == 'banned_heavy' %}tag-red{% else %}tag-gray{% endif %}">{{ target_profile.get_status_display }}</span>{% else %}无资料{% endif %}
  {% if target_profile.ban_reason %}· 原因:{{ target_profile.ban_reason }}{% endif %}</p>
```

`user_detail.html` 两个举报表的状态列(两处相同改法):

```html
<td><span class="tag {% if r.status == 'pending' %}tag-orange{% else %}tag-green{% endif %}">{{ r.get_status_display }}</span></td>
```

- [ ] **Step 4: 危险/语义按钮改类名**

| 文件 | 按钮 | 加类 |
|---|---|---|
| partials/photo_grid.html | 「驳回所选」「驳回」「撤回并驳回」 | `danger` |
| partials/report_panel.html | 「轻度封禁被举报人」 | `warn` |
| partials/report_panel.html | 「重度封禁被举报人」 | `danger`(去掉原 secondary) |
| partials/user_ban_panel.html | 「轻度封禁」 | `warn` |
| partials/user_ban_panel.html | 「重度封禁」 | `danger`(去掉原 secondary) |
| partials/user_ban_panel.html | 「解封」 | `ok`(去掉原 outline) |

即把对应 `class="secondary"`/`class="outline"` 换成上表类名;「通过」「恢复通过」「通过所选」保持默认(蓝)。

- [ ] **Step 5: 跑测试 + 截图全页目检**

```bash
cd chatapp && python manage.py test ops
```

Expected: PASS(26 个)。

Playwright(复用 Task 1 的临时账号与已登录会话或重新登录)依次截图并目检:`/ops/reports/`(tabs+表格卡片)、一条举报详情(双方卡片并排、状态胶囊、两种封禁按钮橙/红)、`/ops/photos/`(照片卡、通过/驳回按钮蓝/红)、`/ops/users/?q=13300133001`(结果表)、用户详情(状态胶囊、封禁三按钮橙/红/绿、举报关系表状态胶囊)、`/ops/logs/`(筛选+两表三卡片)。有问题当场修并重复。

- [ ] **Step 6: 提交**

```bash
git add chatapp/ops
git commit -m "feat(ops): adapt pages to new shell (titles, status tags, danger buttons)"
```

---

### Task 3: 全量回归 + 清理临时账号 + 收尾

**Files:**
- Modify: `docs/superpowers/plans/2026-09-11-ops-console-ui.md`(勾选进度)

**Interfaces:**
- Consumes: Task 1/2 的全部产出
- Produces: 可交付的改版(等待用户浏览器复核)

- [ ] **Step 1: 后端全量测试**

```bash
cd D:/pycharmproject/chat_app/chatapp && python manage.py test
```

Expected: 180 个全部 PASS。

- [ ] **Step 2: 删除临时截图账号**

```bash
python manage.py shell -c "from accounts.models import User; print(User.objects.filter(phone='13000000001').delete())"
```

Expected: 输出删除计数(1 条);**不动** `13900000000` 运营账号。

- [ ] **Step 3: 最终截图留档(可选)**

登录页 + 举报队列两页再截一次,确认最终态;截图存 `%TEMP%`,不入库。

- [ ] **Step 4: 勾选本计划 checkbox 并提交**

```bash
git add docs/superpowers/plans/2026-09-11-ops-console-ui.md
git commit -m "docs: mark ops console UI plan progress"
```

- [ ] **Step 5: 交回用户复核**

告知用户浏览器打开 `http://127.0.0.1:8000/ops/` 复核视觉效果(账号 `13900000000`);确认后再回到合并决策。
