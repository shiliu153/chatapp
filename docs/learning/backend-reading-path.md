# 后端通读学习路线（新手向）

> 建立于 2026-10-09。目标：**从零读懂 `chatapp/` 的每一行后端代码**（前端 Flutter / Vue 暂不纳入）。
> 本文件既是路线图，也是进度表——每批完成后勾掉对应 checkbox。

---

## 0. 怎么用这份文档

**每一批都有一册配套指导书**（读前必建概念 + 精确行号清单 + 可复制实验与预期结果 + 自查题参考答案），开工前先打开对应那一册。用法见 [backend-guide/README.md](backend-guide/README.md)。

| 批次 | 指导书 | 批次 | 指导书 |
|---|---|---|---|
| P00 | [P00-环境与反馈回路.md](backend-guide/P00-环境与反馈回路.md) | P08 | [P08-滑卡与配对.md](backend-guide/P08-滑卡与配对.md) |
| P01 | [P01-请求怎么进门.md](backend-guide/P01-请求怎么进门.md) | P09 | [P09-IM抽象层与签名.md](backend-guide/P09-IM抽象层与签名.md) |
| P02 | [P02-settings逐行.md](backend-guide/P02-settings逐行.md) | P10 | [P10-Celery异步副作用.md](backend-guide/P10-Celery异步副作用.md) |
| P03 | [P03-请求怎么出门.md](backend-guide/P03-请求怎么出门.md) | P11 | [P11-合规与封禁两级.md](backend-guide/P11-合规与封禁两级.md) |
| P04 | [P04-登录上-发验证码.md](backend-guide/P04-登录上-发验证码.md) | P12 | [P12-广场feed.md](backend-guide/P12-广场feed.md) |
| P05 | [P05-登录下-JWT与单设备.md](backend-guide/P05-登录下-JWT与单设备.md) | P13 | [P13-运维台ops.md](backend-guide/P13-运维台ops.md) |
| P06 | [P06-资料上-模型与在线状态.md](backend-guide/P06-资料上-模型与在线状态.md) | P14 | [P14-收尾横扫.md](backend-guide/P14-收尾横扫.md) |
| P07 | [P07-资料下-序列化与照片.md](backend-guide/P07-资料下-序列化与照片.md) | | |

1. 按批次**顺序**推进，不要跳批。P00–P03 是地基，跳过后面的批次会变成"看天书"。
2. 每批严格走第 3 节的**五步法**，其中第 4 步（改一行做实验）**不许省**。
3. 每批写一份笔记，模板见第 5 节，存到 `docs/learning/backend-notes/`。
4. 当场没懂的东西写进笔记的「存疑清单」，**不要停下来死磕**，攒到 P14 集中解决。

---

## 1. 起点与范围（2026-10-09 实测）

| 项目 | 实测值 |
|---|---|
| 已具备 | Python 语言（函数/类/装饰器/异常）、SQL 与 MySQL（建表/外键/索引/事务） |
| 尚不具备（本路线覆盖） | Django、DRF、HTTP/REST/JWT、Redis、Celery |
| 后端体量 | 生产代码 **3829 行**（103 个 py 文件，不含 migrations）/ 测试 **3235 行**（9 个 tests.py） |
| 解释器 | `C:\Users\20157\anaconda3\envs\Django\python.exe`（Python 3.10.19 + Django 5.2.9） |
| 数据库 | MySQL80 服务运行中，3306 通，`chatapp/.env` 已配置 |
| Redis | **未运行**（6379 不通）；只能通过 Docker 起（项目内无本地 redis 可执行文件） |
| Docker | 已安装 28.3.2，但**守护进程未运行** |

**结论：量完全可控。别把"通读"想成啃 3 万行——后端生产代码只有 3829 行，一天读 300 行，13 天读完。**

---

## 2. 三条铁律（决定你会不会半途而废）

1. **只查当前这一个概念。**
   读到 `select_related` 不认识 → 只查 `select_related`，查完立刻回到原文件。
   一旦顺着 Django 官方文档跳走，两小时后你会发现自己没在读这个项目的代码。

2. **每批必须改一行代码。**
   "看懂了"和"以为看懂了"的分界线，就是你有没有亲眼见过改坏之后报什么错。

3. **不懂就记账，不糊过去。**
   写进「存疑清单」。攒着不是逃避，是避免在一处卡死整条路线。

---

## 3. 每批的标准动作（五步法，约 2 小时）

| 步 | 时长 | 做什么 |
|---|---|---|
| ① 导读 | 10 min | 只读该批对应的 spec 相关章节 + `docs/api/` 对应分册。**不读完整篇。** |
| ② 逐行精读 | 60–90 min | 逐行读，按铁律 1 查概念。边读边在笔记里记行号区间。 |
| ③ 追一次真实请求 | 20 min | 用 curl 打该接口，对照终端里 `RequestIdMiddleware` 打的日志读代码。 |
| ④ 改一行做实验 | 20 min | 按该批"实验"栏操作，看测试红什么/响应怎么变，**然后改回来**。 |
| ⑤ 写笔记 + 验收 | 20 min | 按第 5 节模板写笔记，跑该 app 测试，对照第 6 节四条定义验收。 |

---

## 4. 批次表

### 阶段一 · 地基（P00–P03）

- [ ] **P00 · 把反馈回路建起来**（不读代码，纯实操）
  - 目标：建立"改一行 → 立刻看到结果"的完整回路。没有这一步，后面全部是纸上谈兵。
  - 步骤：
    1. 启动 Docker Desktop（开始菜单搜索，等托盘鲸鱼图标变绿）。
    2. `cd chatapp` → `docker compose -f docker-compose.dev.yml up -d`
    3. 验证 Redis：`Test-NetConnection 127.0.0.1 -Port 6379` 返回 True。
    4. `conda activate Django` → `python manage.py migrate`
    5. `python manage.py runserver` → 浏览器/curl 打 `http://127.0.0.1:8000/api/v1/health`
    6. 另开一个终端：`python manage.py test accounts` 跑到全绿。
    7. 认识三个进程的分工：**MySQL**（数据）、**Redis**（验证码缓存 + Celery 队列）、**Django**（HTTP）。Celery worker 本批不起，P10 再起。
  - 自查：为什么跑测试必须先把 Redis 起来？（提示：看 `.env.example` 第 18–21 行的注释）

- [ ] **P01 · 请求怎么进门**（94 行）
  - 文件：`manage.py`(22)、`config/__init__.py`(7)、`config/urls.py`(15)、`config/api_urls.py`(18)、`config/wsgi.py`(16)、`config/asgi.py`(16)
  - 概念：WSGI vs ASGI、URLconf 匹配、`include()` 拼接、`settings.DEBUG` 与静态文件
  - 导读：`docs/api/health.md`
  - 实验：在 `config/api_urls.py` 里自己加一条 `path("ping", ...)` 返回 JSON，用 curl 打通，再删掉。
  - 自查：一个请求打 `/api/v1/users/me`，Django 依次经过哪几个 urls.py？

- [ ] **P02 · settings.py 逐行（分 2 次读）**（308 行）
  - 文件：`config/settings.py`
  - 第一次：第 1–140 行（INSTALLED_APPS / MIDDLEWARE / DATABASES / CACHES / `CELERY_BROKER_URL`）
  - 第二次：第 141–308 行（`AUTH_USER_MODEL` / REST_FRAMEWORK / JWT 时长 / 限流 / `SMS_DEV_MODE` / `AUTO_APPROVE` / 日志）
  - 概念：Django 配置驱动、`os.getenv` + `python-dotenv`、自定义 User 模型必须在首次 migrate 前定好
  - 实验：注释掉 `REST_FRAMEWORK` 里某一条配置，观察响应变化，改回来。
  - 自查：`.env` 里为什么**禁用** `CELERY_` 前缀的键？（提示：见 CLAUDE.md 核心契约）
  - ⚠️ 这是新手最容易崩的一批（一段 300 行的配置没有"剧情"）。**允许分两次读，但不要跳过。**

- [ ] **P03 · 请求怎么出门**（约 107 行）
  - 文件：`config/middleware.py`(33)、`config/request_id.py`(22)、`config/exceptions.py`(36)、`config/error_codes.py`(8)、`config/pagination.py`(8)
  - 概念：中间件洋葱模型、`contextvars`、DRF 异常处理器、统一错误契约、业务码 = HTTP 前 3 位 + 2 位序号
  - 导读：`docs/api/conventions.md`、`docs/api/errors.md`
  - 实验：在某个视图里 `raise` 一个自定义异常，观察返回 JSON 与响应头 `X-Request-Id`。
  - 自查：为什么失败响应里要有 `request_id`？它和中间件、日志三者的关系是什么？

### 阶段二 · 八条业务链路（P04–P13）

- [ ] **P04 · 登录（上）：发验证码**（约 250 行）
  - 文件：`accounts/urls.py`(9)、`accounts/views.py` 前段、`accounts/sms_codes.py`(83)、`accounts/throttles.py`(20)、`accounts/services.py`(41)、`accounts/exceptions.py`(45)
  - 概念：DRF 视图、Redis 缓存、60 秒重发间隔、IP 限流、入队失败回滚 503
  - 导读：`docs/api/auth.md`
  - 实验：连续发两次验证码，拿到 42901 并读响应头 `Retry-After`。
  - 自查：验证码到底存在哪里？为什么开发期固定是 `123456`？

- [ ] **P05 · 登录（下）：校验、JWT、单设备登录**（约 180 行）
  - 文件：`accounts/views.py` 后段、`accounts/serializers.py`(19)、`accounts/models.py`(47)、`accounts/tokens.py`(25)、`accounts/authentication.py`(23)
  - 概念：自定义 User 模型、继承 simplejwt 的 Token 类、自定义 claim（`session_version`）、60 秒幂等重放、连错 5 次锁 15 分钟
  - 实验：手动把令牌里的 `session_version` 改掉，观察 401 + 业务码 40101。
  - 自查：JWT 的 `user_id` claim 为什么是**字符串**？`GET /users/me` 里的 `id` 和 `user_id` 分别是什么？

- [ ] **P06 · 资料（上）：模型与在线状态**（约 230 行）
  - 文件：`users/models.py`(133)、`users/presence.py`(58)、`users/services.py`(39)
  - 概念：ORM 字段/索引/外键、迁移文件是怎么生成的、120 秒在线窗口、45 秒心跳
  - 导读：`docs/api/users.md`、`docs/superpowers/specs/2026-09-13-online-presence-design.md`
  - 实验：在 `python manage.py shell` 里查一个用户的 presence 返回值。
  - 自查：「在线」的判定为什么放在请求链路里，而不是靠 WebSocket？

- [ ] **P07 · 资料（下）：序列化、视图、照片**（约 302 行）
  - 文件：`users/serializers.py`(110)、`users/views.py`(120)、`users/urls.py`(12)、`users/admin.py`(60)
  - 概念：Serializer 校验、multipart 上传、照片过审（`AUTO_APPROVE`）、资料"完善度"判定
  - 实验：PATCH `/users/me` 触发"未满 18 岁 400"。
  - 自查：`complete` / `incomplete` 的判定条件一共几项？

- [ ] **P08 · 滑卡与配对**（约 276 行）
  - 文件：`discovery/models.py`(49)、`discovery/services.py`(12)、`discovery/serializers.py`(26)、`discovery/views.py`(121)、`discovery/throttles.py`(10)、`discovery/urls.py`(8)、`discovery/management/commands/dev_reset_pair.py`(50)
  - 概念：候选查询的排除逻辑（自己/划过/已配对/资料未完善/无过审照片）、ORM 查询优化、swipe 幂等、`transaction.on_commit(fn, robust=True)`、互喜配对与灰条
  - 导读：`docs/api/discovery.md`
  - 实验：`python manage.py dev_reset_pair --a u8 --b u9` 重演一次配对。
  - 自查：`on_commit` 到底在什么时刻执行？为什么 IM 副作用必须放在它里面？

- [ ] **P09 · IM 抽象层与签名**（约 311 行）
  - 文件：`im/models.py`(3)、`im/signature.py`(55)、`im/client.py`(211)、`im/views.py`(35)、`im/urls.py`(7)
  - 概念：第三方 REST 封装、"对外永不抛异常"、userSig 的 HMAC 签名、超时与降级
  - 导读：`docs/api/im.md`、`docs/pitfalls/im.md`
  - 实验：把 client 的请求 mock 掉，走降级路径，看接口返回什么。
  - 自查：为什么 `im/client.py` 不许向上抛异常？抛了会怎样？

- [ ] **P10 · Celery 异步副作用**（约 309 行）
  - 文件：`im/tasks.py`(160)、`config/celery.py`(44)、`notifications/tasks.py`(8)、`notifications/backends.py`(18)、`im/management/commands/*`(79)
  - 概念：任务参数一律传 user_id、任务内自己查库、重试策略、Windows 只能 `--pool=solo`、自定义管理命令
  - 导读：`docs/api/im.md`
  - 实验：在任务里加一行日志 → **重启 worker**（改了任务代码必须重启）→ 观察日志。
  - 自查：为什么响应路径里禁止任何第三方网络调用？

- [ ] **P11 · 合规：举报、拉黑、封禁两级（分 2 次读）**（约 364 行）
  - 文件：`moderation/models.py`(79)、`moderation/services.py`(63)、`moderation/views.py`(65)、`moderation/serializers.py`(42)、`moderation/permissions.py`(24)、`moderation/text_check.py`(13)、`moderation/throttles.py`(10)、`moderation/urls.py`(9)、`moderation/admin.py`(59)
  - 概念：DRF 全局 permission 类、`banned_light` vs `banned_heavy`、全局 403 与白名单、敏感词
  - 导读：`docs/api/moderation.md`、`docs/superpowers/specs/2026-09-11-m3-compliance-design.md`、`2026-09-12-report-notice-design.md`
  - 实验：把某个用户置成 `banned_heavy`，打任意接口看 403，再打白名单接口看通。
  - 自查：为什么权限要做成**全局类**而不是每个视图各写一遍？

- [ ] **P12 · 广场 feed**（约 387 行）
  - 文件：`feed/models.py`(83)、`feed/serializers.py`(88)、`feed/services.py`(53)、`feed/views.py`(113)、`feed/throttles.py`(38)、`feed/urls.py`(12)
  - 概念：分页（回看 `config/pagination.py`）、点赞计数、多图上传、N+1 查询
  - 导读：`docs/api/feed.md`、`docs/superpowers/specs/2026-09-12-square-feed-design.md`
  - 实验：造 20 条动态，观察分页参数与返回结构。
  - 自查：什么叫 N+1？这个项目用什么手段规避？

- [ ] **P13 · 运维台 ops（Django 模板视图，不是 DRF）**（约 369 行）
  - 文件：`ops/views.py`(296)、`ops/urls.py`(34)、`ops/decorators.py`(16)、`ops/forms.py`(9)、`ops/context_processors.py`(14)
  - 概念：Django 传统模板视图、装饰器鉴权、context processor、服务端渲染
  - 导读：`docs/superpowers/specs/2026-09-11-ops-console-design.md`
  - 实验：启动服务后登录 ops 后台，把界面和 `ops/views.py` 的函数对应起来。
  - 自查：为什么同一项目里 ops 用模板视图，而 API 用 DRF？两者鉴权方式有何不同？

### 阶段三 · 收尾横扫（P14）

- [ ] **P14 · 文档门禁 + 全局横扫**
  - 文件：`config/api_doc_coverage.py`(88)、`config/tests.py`(184)
  - 概念：`ApiDocsCoverageTests` 双向门禁——改了接口不改文档，测试就红
  - 导读：`docs/api/README.md`、`docs/superpowers/specs/2026-09-21-api-documentation-design.md`
  - 实验：故意改一个接口的路径而不动 `docs/api/`，跑测试看它怎么红，再改回来。
  - 横扫动作（B 路线）：
    1. 把 8 个 `models.py` 连起来通读一遍，画一张表关系图
    2. 翻 migrations，理解"模型改了 → 生成了什么"
    3. 横向扫 9 个 `tests.py` 的结构，归纳这个项目的测试写法
    4. 读 `docs/pitfalls/backend.md`，与自己笔记的存疑清单对账
    5. **清空存疑清单**——这一批不读完不算结束

---

## 5. 笔记模板

每批新建 `docs/learning/backend-notes/P{编号}-{主题}.md`：

```markdown
# P07 · 资料（下）序列化、视图、照片

## 这条链路
- 输入：
- 处理：
- 副作用：

## 涉及文件与行号
| 文件 | 行号 | 这里在干什么 |
|---|---|---|

## 新学到的概念（≤5 个）
| 概念 | 一句话解释 |
|---|---|

## 我的实验
- 改了什么：
- 结果：
- 我的结论：

## 存疑清单
- [ ] （没懂的，留到 P14）

## 自查题
1. 问题 → 答案
```

---

## 6. 批次完成的定义（4 条全过才算完）

1. **合上代码**能说出这条链路的 输入 → 处理 → 副作用
2. 能回答"要新增一个同类接口，改哪几个文件"
3. 该 app 测试跑绿：`python manage.py test <app>`
4. 笔记里**没有整段照抄的代码**（照抄=没消化）

---

## 7. 常用命令速查

```powershell
# 环境（cwd = chatapp/）
conda activate Django                       # Python 3.10.19 + Django 5.2.9
docker compose -f docker-compose.dev.yml up -d   # Redis（跑测试/接口前必须起）

# 日常
python manage.py check                      # 配置自检
python manage.py runserver                  # :8000
python manage.py test                       # 全量（需 Redis）
python manage.py test users                 # 单 app
python manage.py shell                      # 交互式实验 ORM
python manage.py makemigrations && python manage.py migrate

# 手测工具
python manage.py im_send --from u2 --to u3 --text "你好"
python manage.py dev_reset_pair --a u8 --b u9
python manage.py seed_fake_users --count 20

# Celery worker（P10 起用；Windows 只能 solo；改了任务代码必须重启）
python -m celery -A config worker -l info --pool=solo
```

---

## 8. 进度记录

| 批次 | 状态 | 完成日期 | 笔记 |
|---|---|---|---|
| P00 | 环境已就绪（2026-10-09 实测） | — | |
| P01 | 未开始 | | |
| P02 | 未开始 | | |
| P03 | 未开始 | | |
| P04 | 未开始 | | |
| P05 | 未开始 | | |
| P06 | 未开始 | | |
| P07 | 未开始 | | |
| P08 | 未开始 | | |
| P09 | 未开始 | | |
| P10 | 未开始 | | |
| P11 | 未开始 | | |
| P12 | 未开始 | | |
| P13 | 未开始 | | |
| P14 | 未开始 | | |
