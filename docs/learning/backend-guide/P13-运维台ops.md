# P13 · 运维台 ops（约 369 行）

> 上一批：[P12 广场 feed](P12-广场feed.md) · 下一批：[P14 收尾横扫](P14-收尾横扫.md)
> 预计 2 小时 · 本批是**同一个项目里的另一套技术路线**：服务端渲染 + Session 鉴权，完全不碰 DRF

---

## §1 本批目标

1. 说出运维台与 API 在**鉴权方式、响应形式、路由风格**上的三处不同；
2. 说出"为什么 ops 不写成 DRF 接口"；
3. 说出运营台里那些"动作视图"为什么返回局部模板（`partials/*.html`）；
4. 说出 admin 后台与自研 ops 后台的分工。

---

## §2 读前必建概念

### 1）同一项目、两套技术路线

| 维度 | `/api/v1/*`（App/Web 用） | `/ops/*`（运营用） |
|---|---|---|
| 响应 | JSON（DRF） | **HTML 模板**（Django `render`） |
| 鉴权 | Bearer JWT（`SessionJwtAuthentication`） | **Django Session + `is_staff`** |
| 路由风格 | 路径**不带**尾斜杠 | 路径**带**尾斜杠 |
| 限流 | DRF 限流器（Redis 计数） | 无（只给内部员工） |
| 客户端 | 移动端 / Web 前端 | 浏览器（含 HTMX 局部刷新） |

**为什么两套？** 面向人的后台页面，服务端渲染 + Session 是最省事的方案：不用写前端路由、不用管令牌刷新、表单与权限都由 Django 现成机制处理。而 App 需要的是稳定 JSON 契约——两者的"最好方案"本来就不同。**"一个项目只能有一种风格"是伪命题。**

### 2）`app_name` 与命名空间反向解析

```python
app_name = "ops"
path("reports/", views.reports_list, name="reports")
```
于是模板/代码里可以用 `{% url 'ops:reports' %}` 或 `reverse("ops:reports")`——**路由改名不会漏改引用点**（这是硬拼字符串做不到的）。

### 3）Session 登录复用 Django 内置视图

`LoginView` / `LogoutView` 是 Django 自带的（`django.contrib.auth.views`），本项目只做了两件事：指定模板 + 用自定义表单**额外要求 `is_staff`**；并设置 `LOGIN_REDIRECT_URL = "/ops/reports/"`（settings 第 308 行）。

### 4）HTMX 式的"局部刷新"（本项目的手工版）

动作视图（如"处理举报"）不返回整个页面，而是返回**一小块 HTML 片段**（`ops/partials/report_panel.html`），由前端把它替换进当前页面。这样做的好处：不用写 JS、不用 JSON 契约、状态由服务端一次性渲染。

### 5）admin 与 ops 的分工

| | Django admin（`/admin/`） | 自研 ops 后台（`/ops/`） |
|---|---|---|
| 定位 | 通用数据管理（开发者/超管用） | **业务审核台**（给运营人员按流程用） |
| 形态 | 表 → 行 → 编辑表单 | 页面 → 待办队列 → 一键动作 |
| 本项目的角色 | 兜底/应急（也挂了照片审核、封禁审计） | 主流程（举报处理、照片审核、用户封禁、动态处理、日志） |

两者**共用同一个 service 层**（`users.services.review_photos`、`moderation.services.log_ban_change`、`feed.services.delete_post`）——P06/P07/P11/P12 里都埋了这条伏笔，本批收网。

---

## §3 精读清单

### 1. `ops/decorators.py`（16 行）——鉴权就这 16 行

| 行 | 在干什么 |
|---|---|
| 8–15 | `staff_required`：①未登录 → `redirect_to_login(当前路径, ops:login)`（**带上 next，登录后回到原页**）；②已登录但非 staff → `HttpResponseForbidden("该账号无运营权限")`；③否则放行 |
| 9 | `@wraps(view)`：保留原视图的名字/docstring（否则所有视图都叫 `wrapper`，日志与调试都废） |

### 2. `ops/forms.py`（9 行）

`OpsLoginForm(AuthenticationForm)`：覆写 `confirm_login_allowed`（Django 提供的"额外准入校验"钩子）→ 非 staff 直接抛 `ValidationError("该账号无运营权限")`。**与装饰器形成双重保险**：登录时就挡一次，每个视图再挡一次。

### 3. `ops/context_processors.py`（14 行）

`ops_badges(request)`：只有"已登录且 staff"才返回三个待办计数（待处理举报 / 待审照片 / 待处理动态举报）。**它在 settings 第 86 行被注册**，所以**每个** ops 模板都能直接用 `{{ pending_report_count }}` 之类的变量——侧边栏角标就是这么来的。
> 注意代价：每次渲染 ops 页面都会多 3 次 `COUNT` 查询。对内部后台可接受；对 C 端接口就要谨慎了。

### 4. `ops/urls.py`（34 行）

| 类别 | 路由 |
|---|---|
| 入口 | `""` → home（重定向到 reports）、`login/`、`logout/` |
| 举报 | `reports/`、`reports/<int:report_id>/`（详情）、`reports/<id>/handle`、`reports/<id>/ban` |
| 照片 | `photos/`、`photos/review` |
| 用户 | `users/`（搜索）、`users/<id>/`（详情）、`users/<id>/ban` |
| 动态 | `posts/`、`posts/<id>/delete`、`post-reports/`、`post-reports/<id>/handle`、`post-reports/<id>/delete-post` |
| 日志 | `logs/` |

**观察点**：列表与详情页带尾斜杠，**动作端点不带**（`/handle`、`/ban`、`/delete`）——一种"页面 vs 动作"的区分习惯。这套风格与 `/api/v1` 相反，正好说明**尾斜杠不是对错问题，是约定问题**（P01 讲过机制）。

### 5. `ops/views.py`（296 行）——按四类读

**（a）列表页：查询 + 过滤 + 渲染（都在 200 行以内截断）**

| 函数 | 行 | 要抓的点 |
|---|---|---|
| `home` | 19–21 | `redirect("ops:reports")`——用命名空间而不是硬编码 URL |
| `reports_list` | 24–38 | 默认 `status=pending`；`annotate(target_report_count=Count("target__reports_received", distinct=True))` → **在列表里直接显示"该用户被举报过几次"**（运营最需要的信息）；第 34–35 行 `order_by("-status","-created_at")` 与 admin 同款"字符串降序让 pending 在前"；`[:200]` 硬截断 |
| `photos` | 119–126 | 默认筛 `pending`；`[:120]` |
| `users_search` | 149–156 | `Q(phone=q) | Q(profile__nickname__icontains=q)`：**精确手机号 + 昵称模糊**；`[:50]` |
| `logs` | 199–219 | 三个可选过滤（action/phone/date）；日期用 `created_at__date=` 且**用 try/except 处理非法日期**（第 210–213 行）——**运营台对错误输入的宽容处理**；顺带展示最近 100 条拉黑记录 |
| `posts` / `post_reports` | 230–264 | 分别复用 `_posts_queryset()` / `_post_reports_queryset(status)` |

**（b）详情页：把"判断所需的全部上下文"一次查齐**

`report_detail`（41–45）+ `_report_context`（48–59）：举报详情 + 双方资料 + **举报人的其他举报（最近 10 条）+ 被举报人的其他举报（最近 10 条）+ 被举报人的封禁历史（最近 10 条）**。
> **这就是"运营判断依据"的具象化**：处理一条举报，需要知道"这人是不是惯犯""以前有没有被封过"。**设计后台页面时，先想清楚"人做什么决定需要什么信息"** —— 这是本批最值得带走的方法论。

`user_detail`（159–162）+ `_user_context`（165–175）：用户资料 + 封禁历史 + 收到的/发出的举报 + 拉黑关系。

**（c）动作页：改状态 + 复用 service + 返回局部片段**

| 函数 | 行 | 要抓的点 |
|---|---|---|
| `_apply_status_change` | 62–77 | **被封禁/解封的唯一实现**：解封时先置 `INCOMPLETE`、清 `ban_reason`，**再 `refresh_status()`**——第 70 行注释说明原因："封禁态不参与重算，必须先在非封禁态"（回看 P06 第 98–99 行：`refresh_status` 遇到封禁态直接 return）；最后统一调 `log_ban_change(...)`（**与 admin 同源**，P11） |
| `report_handle` | 80–92 | **只在 pending 时**处理（幂等）；写 `handled_note/handled_by/handled_at`；`notify_report_handled` 通知举报者；返回 `partials/report_panel.html` |
| `report_ban` | 95–116 | 先校验 level 与 reason（**封禁必须填原因**）→ `_apply_status_change` → 顺手把举报标成已处理（`handled_note="封禁处理"`）→ 同一片段返回；出错时把 `error` 传给模板显示 |
| `photo_review` | 129–146 | `ids = set(request.POST.getlist("ids"))`（多选）；**任何状态都可再审**（注释：已通过可撤回驳回）；`skipped` 只统计"页面陈旧、照片已被删"的 id；核心调 `review_photos(targets, action, request.user)`（**P06/P07 那个共用 service**） |
| `user_ban` | 178–196 | 三种 action（unban / ban_light / ban_heavy）+ 封禁必须填原因 |
| `post_delete` | 235–240 | 调 `delete_post(post)`（**P12 那个共用 service**，会自动关闭该动态的全部待处理举报） |
| `post_report_handle` | 267–278 | 与 `report_handle` 同构 |
| `post_report_delete_post` | 281–296 | **两种情况**：动态还在 → `delete_post`（连带关闭全部举报）；**动态已被作者删除（`post` 为 None）→ 只关闭这一条举报**（第 288–295 行）。这是 `SET_NULL` 设计（P12）带来的分支，也是运营台的边界处理 |

**（d）两个查询助手**：`_posts_queryset()`（222–227，注解点赞/评论数）与 `_post_reports_queryset(status)`（243–248）。

### 6. 模板（16 个，`ops/templates/ops/`）

- `base.html`：公共骨架（侧边栏角标就是 `ops_badges` 提供的变量）
- `reports_list.html` / `report_detail.html` / `photos.html` / `users_search.html` / `user_detail.html` / `logs.html` / `posts.html` / `post_reports.html` / `login.html`
- `partials/`：`report_panel.html`、`photo_grid.html`、`user_ban_panel.html`、`user_card.html`、`posts_table.html`、`post_reports_table.html` —— **动作返回的就是这些片段**

> 读模板不必逐行（HTML 没有业务逻辑，逻辑应该在视图里）。只需抽查：**视图传了哪些上下文变量、模板里怎么用**。若在模板里发现复杂逻辑（循环里做查询、条件判断业务规则），那是设计信号——值得记进笔记。

---

## §4 动手实验

### 实验 1 · 登录与权限双重拦截

```powershell
cd D:\pycharmproject\chat_app\chatapp
python manage.py createsuperuser      # 手机号 + 密码(运营账号,is_staff/is_superuser)
python manage.py runserver
```
浏览器依次验证：
1. 未登录访问 `http://127.0.0.1:8000/ops/reports/` → **302 跳登录页**，URL 带 `?next=/ops/reports/`；登录后回到该页（`decorators.py` 第 12 行的 `redirect_to_login`）。
2. 用一个**普通用户**（`is_staff=False`）的手机号+密码登录 → 表单报"该账号无运营权限"（`forms.py` 第 9 行）。
3. 尾斜杠实验：访问 `/ops/reports`（不带斜杠）→ 应被 `CommonMiddleware` **301 重定向**到 `/ops/reports/`（与 P01 里 `/api/v1/health/` 的 404 恰好相反——因为这一套路由是**带**尾斜杠的）。

### 实验 2 · 走一遍完整审核流程

1. 用 App/curl 造一条举报（P11 实验 1）。
2. `/ops/reports/` 打开待办（注意侧边栏角标数字 = `ops_badges`）。
3. 进详情页，注意页面上同时显示了：举报人历史举报、被举报人历史举报、被举报人封禁历史（`_report_context`）。
4. 点"封禁"→ 必须填原因（不填会显示错误）→ 提交后返回局部片段。
5. 验证副作用：
   ```powershell
   python manage.py shell -c "from moderation.models import BanLog, Report; print(list(BanLog.objects.values_list('action','reason'))); print(list(Report.objects.values_list('status','handled_note')))"
   ```
   预期：多了一条 `ban_light/ban_heavy` 审计；该举报变成 `handled`，`handled_note='封禁处理'`。
   （若起了 worker，还能看到 `ban_notice` 任务被消费。）

### 实验 3 · 照片审核（多选 + 可撤回）

1. `/ops/photos/` 看待审队列（需先把 `AUTO_APPROVE` 关掉或直接造 `pending` 照片）：
   ```powershell
   python manage.py shell -c "from users.models import Photo, PhotoStatus; Photo.objects.update(status=PhotoStatus.PENDING); print(Photo.objects.count())"
   ```
2. 勾选几张 → "通过"或"驳回"。
3. 观察：照片状态变化 + **对应 `Profile.status` 被重算**（`review_photos` 第 20–22 行）+ 过审时入队 `sync_profile:avatar`（P07/P10）。
4. 再做一次相反操作（对已通过的点"驳回"）→ 验证"任何状态都可再审"。

### 实验 4 · 封禁/解封的状态机

```powershell
# 在 /ops/users/ 搜索一个用户 → 详情页 → 封禁(轻封禁) → 再解封
python manage.py shell -c "from users.models import Profile; print(list(Profile.objects.values_list('user_id','status')))"
```
**观察点**：解封后状态回到 `complete`/`incomplete`（而不是停在某个中间态）——这是 `_apply_status_change` 第 67–70 行的顺序（先非封禁态、再 `refresh_status`）在起作用。**故意把顺序写反你会发现状态卡在 `incomplete`**（因为 `refresh_status` 对封禁态直接 return）——这值得亲手试一次（试完改回来）。

### 实验 5 · 动态处理的两条分支

1. `/ops/post-reports/` 有一条针对某动态的举报 → 点"删除动态" → `delete_post` 会关闭该动态**全部**待处理举报并通知所有举报者（P12）。
2. 再造一条举报，然后**由作者自己先删掉动态**（App/curl）→ 回到 `/ops/post-reports/`，这条举报的 `post` 已为 None → 点"删除动态"会走第 288–295 行的**只关闭这一条**分支。

### 实验 6 · 读 ops 的测试

```powershell
python manage.py test ops --noinput
```
读 `ops/tests.py`（412 行），重点看：未登录跳转、非 staff 403、举报处理幂等、封禁必须填原因、照片批量审核、动态删除两分支。**运营台的测试比接口测试更值得读**——因为它的分支更多、更容易被忽略。

---

## §5 自查题

**Q1. 为什么运维台用 Session + 模板，而 API 用 JWT + JSON？**

**参考答案**：面向人的后台页面用服务端渲染最省事（不用写前端路由、不用处理令牌刷新，表单与权限用 Django 现成机制），且只有内部员工使用、无跨端需求。API 面向移动端/Web，需要稳定的 JSON 契约与无状态鉴权。**两套路线服务两类消费者，不冲突。**

**Q2. `/ops/*` 为什么带尾斜杠而 `/api/v1/*` 不带？**

**参考答案**：约定不同。`APPEND_SLASH` 只能"补"不能"去"，所以带斜杠的约定下，访问 `/ops/reports` 会 301 到 `/ops/reports/`（体验友好）；而 API 采用不带斜杠的约定，访问带斜杠版本直接 404（P01 实测）。**关键不是哪种更好，而是同一体系内要一致。**

**Q3. 动作视图（handle/ban/review）为什么返回 `partials/*.html` 而不是整页？**

**参考答案**：为了让前端只替换页面上那一块（HTMX 式局部刷新），避免整页重载、丢失滚动位置与筛选状态。好处是几乎不用写 JS，状态由服务端渲染决定。

**Q4. `context_processors.ops_badges` 的代价是什么？**

**参考答案**：它在**每个** ops 页面渲染时执行 3 次 `COUNT` 查询（待办举报/待审照片/待处理动态举报）。对内部后台（访问量低）可接受，是"方便 > 性能"的取舍；若搬到 C 端接口就是明显的浪费。

**Q5. 运营台与 Django admin 是什么关系？为什么两边都有照片审核/封禁？**

**参考答案**：admin 是通用数据管理（兜底、应急、开发期方便），ops 是按业务流程设计的审核台（待办队列 + 一键动作）。两者**共用同一 service 层**（`review_photos`、`log_ban_change`、`delete_post`），所以行为一致——这也是 P02/P06/P11/P12 反复出现的"一处逻辑多入口"模式的收口。

**Q6. 解封时为什么必须"先置非封禁态、再 `refresh_status()`"？**

**参考答案**：`Profile.refresh_status()` 遇到封禁态会直接 return（P06 第 98–99 行，防止封禁被洗白）。所以解封必须先把 status 改成非封禁值，再调用它去重算 `complete`/`incomplete`；顺序反了会卡在 `banned_*`（或算不出正确状态）。

**Q7. 运营列表为什么可以直接 `[:200]` 截断而不做分页？**

**参考答案**：内部后台的使用模式是"看最近的待办"，不是"翻完历史"；硬截断实现简单、性能可控。这是**面向内部用户的合理简化**——但要注意它意味着"更早的记录必须靠筛选条件才能看到"（如手机号/日期过滤，`logs` 视图就提供了）。

---

## §6 卡住时查哪里

| 需要 | 去处 |
|---|---|
| 审核台设计意图 | [../../superpowers/specs/2026-09-11-moderation-console-design.md](../../superpowers/specs/2026-09-11-moderation-console-design.md)、[../../superpowers/specs/2026-09-11-ops-console-ui-design.md](../../superpowers/specs/2026-09-11-ops-console-ui-design.md) |
| 封禁/审核的业务规则 | P11、[../../api/errors.md](../../api/errors.md) §封禁行为 |
| Django 模板视图 / 内置 auth 视图 | Django 官方 `topics/class-based-views`、`django.contrib.auth.views`（只查你要用的那个） |

---

## §7 验收

1. 能说出运维台与 API 的三处关键差异及各自理由；
2. 实验 2 完整走通过一遍举报 → 封禁 → 审计留痕；
3. 实验 4 亲手验证过"解封的状态机"（并知道顺序反了会怎样）；
4. 能列出 ops 复用了哪些 service（至少 3 个）；
5. 笔记 `docs/learning/backend-notes/P13-运维台ops.md`，勾掉总纲 P13。
