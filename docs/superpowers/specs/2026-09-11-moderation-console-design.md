# 运营审核台(Moderation Console)设计

日期:2026-09-11
状态:已与用户逐节确认,待用户终审
上游:M3 设计 spec(`2026-09-11-m3-compliance-design.md`)的 admin 审核台;本设计是它的产品化替代

## 1. 目标与范围

**背景**:M3 的审核能力全部挂在 Django admin 上,手测中发现操作路径绕、信息不聚焦(封禁要先找到 Profile 再改字段、照片审核混在通用列表里),不满足未来运营同事的使用要求。

**定位**:产品级内部工具,给未来运营人员用(非公开产品),与 App 共用同一后端。

**v1 交付(四项功能):**
1. 举报处理:待办队列 + 详情(双方资料卡)+ 处理备注 + 快捷封禁
2. 照片审核:待审网格 + 单张/批量通过/驳回 + 审核留痕
3. 用户管理与封禁:搜索用户 → 详情页 → 封禁(轻/重)/解封
4. 操作日志:封禁审计流水 + 拉黑对账(只读)

**非目标(YAGNI):** 聊天记录查看(需接腾讯云漫游消息 API,敏感操作另议)、数据看板、移动端适配(桌面优先)、多角色细粒度权限(v1 一把 `is_staff`)、照片驳回原因对用户展示、运营消息通知。

## 2. 技术选型(已确认)

| 决策 | 选择 | 理由 |
|---|---|---|
| 形态 | 新 Django app `ops`,同工程同进程,路由挂 `/ops/` | 维护成本最低;M4 部署跟主站一起上线 |
| 渲染 | Django 模板(服务端渲染) | 审核台本质是列表+表单,无需 SPA |
| 交互增强 | HTMX(单文件 JS,局部刷新) | 通过/驳回/封禁不整页跳转;无构建链 |
| 样式 | Pico.css(vendored)+ 少量自定义 CSS | 静态文件打进工程,**不依赖 CDN**,国内服务器可用 |
| 登录 | 复用 Django 账号体系(手机号+密码),判据 `is_staff=True` | 与 admin 同一张用户表;建运营账号=建一个 is_staff 用户 |
| 与 admin 关系 | admin 保留(superuser 应急处置),`/ops/` 是日常运营主入口 | 不破坏既有能力 |

## 3. 架构与路由

```
chatapp/ops/
├── apps.py
├── urls.py              # 全部 /ops/ 路由
├── views.py             # 视图(按功能分节;规模大再拆包)
├── decorators.py        # staff_required
├── context_processors.py# 导航栏待办角标(待处理举报数/待审照片数)
├── tests.py
├── templates/ops/
│   ├── base.html        # 顶部导航:举报 / 照片审核 / 用户 / 日志(带角标)
│   ├── login.html
│   ├── reports_list.html / report_detail.html
│   ├── photos.html
│   ├── users_search.html / user_detail.html
│   ├── logs.html
│   └── partials/        # HTMX 局部片段(行、状态块)
└── static/ops/
    ├── vendor/pico.min.css / htmx.min.js
    └── ops.css
```

| 路由 | 方法 | 说明 |
|---|---|---|
| `/ops/login/`、`/ops/logout/` | GET/POST | 用 Django 内置 auth 视图 + 自定义模板 |
| `/ops/` | GET | 重定向到举报队列 |
| `/ops/reports/` | GET | 举报列表;`?status=&type=` 筛选,待处理排最前 |
| `/ops/reports/<id>/` | GET | 举报详情 |
| `/ops/reports/<id>/handle` | POST | 标记已处理(备注)[HTMX] |
| `/ops/reports/<id>/ban` | POST | 快捷封禁被举报人(级别+原因),并自动标记该举报已处理 [HTMX] |
| `/ops/photos/` | GET | 照片网格;`?status=` 默认 pending |
| `/ops/photos/review` | POST | 单张/批量通过/驳回(`ids[]` + `action`)[HTMX] |
| `/ops/users/` | GET | 搜索;`?q=` 手机号精确或昵称模糊 |
| `/ops/users/<id>/` | GET | 用户详情 |
| `/ops/users/<id>/ban` | POST | 封禁(轻/重,原因必填)/解封 [HTMX] |
| `/ops/logs/` | GET | 封禁审计流水;`?action=&user=&date=` 筛选;附拉黑对账(只读) |

**数据流**:浏览器 → `ops` 视图 → 现有 models + services(moderation/users)→ 模板或 HTMX 片段渲染。所有写操作 POST + CSRF,不新建 App API,**App 端接口零改动**。

## 4. 功能设计

### 4.1 举报处理(默认首页)

- 列表列:时间、类型、举报人(手机号/昵称)、被举报人、**该被举报人累计被举报次数**(识别惯犯);筛选:状态(默认待处理)/类型
- 详情页:举报类型 + 说明 + **双方并排资料卡**(昵称/手机号/账号状态/照片缩略图)+ 举报人发出的历史举报 + 被举报人被举报的历史 + 被举报人封禁历史
- 处理:`POST handle` 填备注 → 标记已处理(自动落 `handled_by`/`handled_at`,沿用现有规则);`POST ban` 快捷封禁 = 封禁被举报人 + 该举报自动标记已处理(备注自动填「封禁处理」)
- 已处理的举报可回看(列表切「已处理」筛选)

### 4.2 照片审核

- 网格:大图预览、上传人(链到用户详情)、时间;单张按钮或勾选批量「通过/驳回」
- 驳回/通过后重算资料完善状态(掉回未完善即失去候选资格,沿用现有逻辑)
- **新增审计字段**(本次确认):`Photo.reviewed_by`(FK User, null)/ `reviewed_at`(null),审核动作写入,详情可查「谁在何时审的」

### 4.3 用户管理与封禁

- 搜索:手机号(精确)/ 昵称(模糊);结果列表给基础信息 + 状态
- 详情页一屏看全:资料(昵称/性别/生日/城市/简介/标签/照片)、当前状态与 `ban_reason`、**封禁历史时间线**(BanLog)、举报关系(举报过谁/被谁举报)、拉黑关系
- 操作:`POST ban` 封禁(轻/重,原因必填)或解封(原因选填);重封自动踢 IM 下线(沿用现有逻辑);**解封后调 `profile.refresh_status()` 重算 complete/incomplete**(admin 是手改状态下拉,ops 自动重算更稳)

### 4.4 操作日志

- 封禁/解封审计流水(BanLog,按动作/用户/日期筛选)
- 拉黑记录对账(只读)
- 举报处理记录不另做页面,用举报列表「已处理」筛选代替

## 5. 后端改动

**原则:ops 与 admin 走同一套业务逻辑,行为绝不分叉。**

**直接复用(零改动)**
- 封禁/解封:`moderation/services.py::log_ban_change`(写 BanLog + 重封踢 IM 全在里面)
- 拉黑:`moderation.services.blocked_user_ids` 等仅用于展示

**两处改动**
1. **抽公共函数**:`users/admin.py::_review_photos` 的照片审核逻辑(改状态 + `refresh_status`)抽到 `users/services.py::review_photos(queryset, status, operator)`,并写入 `reviewed_by/reviewed_at`;admin 的 action 改为调用它(行为不变,多落审计字段)
2. **migration**:`users` app,Photo 加 `reviewed_by`(FK `AUTH_USER_MODEL`, null, `on_delete=SET_NULL`)/ `reviewed_at`(null)

**配置**:`INSTALLED_APPS` 注册 `ops`;`config/urls.py` 挂 `path("ops/", include("ops.urls"))`(注意挂在根 urls,非 api_urls)。

## 6. 权限与安全

- 登录视图校验 `is_staff`:非 staff 账号登录时直接提示「该账号无运营权限」,不发 session
- 所有 ops 视图挂 `staff_required` 装饰器:未登录 → 跳登录页;已登录非 staff → 403 页
- 表单与 HTMX 写操作全部 CSRF;HTMX 请求带 `X-CSRFToken` 头
- 运营账号创建:走现有 admin 用户表或 `createsuperuser`(建后不勾 superuser、勾 is_staff)
- 生产(M4)注意:全站 HTTPS 后 /ops/ 自然同域;如需再收紧可加 IP 白名单(非本期)

## 7. 错误处理

- 表单校验失败:页面内错误提示,已填内容不丢
- 重复操作(处理已处理的举报、封禁已封禁的人):幂等或友好提示,不报 500
- IM 踢人/黑名单失败:后台线程记日志、不阻塞页面(沿用现有模式)
- 照片已不在待审状态时再审核:提示

## 8. 测试策略

Django test client,沿用后端测试风格(`ops/tests.py`):

- 每个页面三态:匿名 → 302 登录页;非 staff → 403;staff → 200
- 举报:列表筛选、handle 落 `handled_note/handled_by/handled_at`、快捷 ban 一步生效(BanLog 落库 + Profile 状态变更 + IM 调用 mock)
- 照片:单张/批量通过驳回、`refresh_status` 重算、`reviewed_by/reviewed_at` 落库
- 用户:搜索(手机号/昵称)、封禁/解封写 BanLog、解封后状态重算、踢 IM mock
- 日志:筛选渲染正确
- 纪律沿用:**凡触发 IM 的用例一律 mock,不许真打腾讯云**;涉及 on_commit 的沿用 `captureOnCommitCallbacks`

## 9. 验收(手测)

用 admin 账号 `13900000000` 登录 `/ops/`:举报处理(含快捷封禁)→ 照片审核(需 `AUTO_APPROVE=0`)→ 用户搜索/封禁/解封 → 日志对账;确认 admin 原功能不受影响(照片 action 仍可用、封禁仍写 BanLog)。
