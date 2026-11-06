# 接口文档(API Reference)

本目录是 chat_app 后端 `/api/v1` 接口的**对外交付文档**:每个接口包含功能说明、请求/响应参数表、请求示例与响应示例(取自真实响应)、该接口会出现的错误码。页面结构与腾讯云 API 文档一致。

> 最后更新:2026-09-21 · 适用版本:M4(测试环境)

## 目录

| 文件 | 内容 |
|---|---|
| [conventions.md](conventions.md) | 公共说明:Base URL、请求约定、鉴权、响应结构、分页、时间格式、限流(读接口前先看它) |
| [errors.md](errors.md) | 错误码总表、HTTP 状态码语义、封禁行为 |
| [auth.md](auth.md) | 账号与鉴权 |
| [users.md](users.md) | 用户资料 / 照片 / 择偶偏好 / 标签 / 他人资料 / 在线状态 |
| [discovery.md](discovery.md) | 发现与配对 |
| [moderation.md](moderation.md) | 举报与拉黑 |
| [feedback.md](feedback.md) | 意见反馈 |
| [feed.md](feed.md) | 广场动态 |
| [im.md](im.md) | IM 会话凭证与聊天媒体上传 |
| [app.md](app.md) | 应用版本配置(启动时最小版本拦截) |
| [telemetry.md](telemetry.md) | 客户端错误上报(前端未捕获异常 → 日志/指标) |
| [push.md](push.md) | 推送设备与通知偏好(极光 registration_id 上报、五类通知开关)。**该能力不启用**:通道固定 `PUSH_PROVIDER=off`,见分册首部说明 |
| [notifications.md](notifications.md) | 站内通知中心(列表 / 未读数 / 标记已读)。**这是「不推送」的替代品**,App 与网页端消息页铃铛入口 |
| [health.md](health.md) | 运维探针(供监控使用,客户端不需要调用) |
| [openapi.yml](openapi.yml) | **机器可读契约**(OpenAPI 3.0,由代码生成,请勿手改;规则见下「机器可读契约」) |

## 接口一览

共 **54** 个接口(按「方法 + 路径」计)。

| 方法 | 路径 | 说明 | 分册 |
|---|---|---|---|
| POST | `/api/v1/auth/sms/send` | 发送短信验证码 | [auth](auth.md) |
| POST | `/api/v1/auth/sms/verify` | 校验验证码并登录(未注册自动建号) | [auth](auth.md) |
| POST | `/api/v1/auth/token/refresh` | 刷新访问令牌 | [auth](auth.md) |
| POST | `/api/v1/auth/logout` | 注销(拉黑 refresh + 清 Cookie,幂等 204) | [auth](auth.md) |
| GET | `/api/v1/users/me` | 获取我的资料 | [users](users.md) |
| PATCH | `/api/v1/users/me` | 修改我的资料 | [users](users.md) |
| DELETE | `/api/v1/users/me` | 注销账号(手机号二次确认,立即硬删除) | [users](users.md) |
| GET | `/api/v1/users/tags` | 获取标签池 | [users](users.md) |
| POST | `/api/v1/users/me/photos` | 上传照片 | [users](users.md) |
| DELETE | `/api/v1/users/me/photos/{photo_id}` | 删除照片 | [users](users.md) |
| GET | `/api/v1/users/me/preference` | 获取择偶偏好 | [users](users.md) |
| PATCH | `/api/v1/users/me/preference` | 修改择偶偏好 | [users](users.md) |
| GET | `/api/v1/users/{user_id}` | 获取他人公开资料 | [users](users.md) |
| GET | `/api/v1/presence` | 批量查询在线状态 | [users](users.md) |
| GET | `/api/v1/discovery/candidates` | 拉取候选卡 | [discovery](discovery.md) |
| POST | `/api/v1/discovery/swipe` | 提交滑卡动作 | [discovery](discovery.md) |
| GET | `/api/v1/discovery/likes` | 喜欢我的人列表(分页) | [discovery](discovery.md) |
| GET | `/api/v1/discovery/likes/count` | 喜欢我的人数 | [discovery](discovery.md) |
| GET | `/api/v1/discovery/visits` | 谁看过我列表(分页) | [discovery](discovery.md) |
| GET | `/api/v1/discovery/visits/count` | 访客人数 | [discovery](discovery.md) |
| GET | `/api/v1/matches` | 配对列表(分页) | [discovery](discovery.md) |
| DELETE | `/api/v1/matches/{user_id}` | 解除配对 | [discovery](discovery.md) |
| POST | `/api/v1/im/user_sig` | 获取 IM 登录凭证 | [im](im.md) |
| POST | `/api/v1/im/images` | 上传聊天图片(返回签名 URL) | [im](im.md) |
| POST | `/api/v1/im/voices` | 上传聊天语音(转码 m4a,返回签名 URL) | [im](im.md) |
| GET | `/api/v1/im/images/auth` | 聊天图片验签(nginx 内部子请求) | [im](im.md) |
| GET | `/api/v1/app/config` | 获取应用最低版本配置 | [app](app.md) |
| POST | `/api/v1/reports` | 举报用户 | [moderation](moderation.md) |
| POST | `/api/v1/feedback` | 提交意见反馈 | [feedback](feedback.md) |
| POST | `/api/v1/client-errors` | 上报客户端未捕获异常 | [telemetry](telemetry.md) |
| POST | `/api/v1/push/devices` | 上报推送设备(幂等,单设备) | [push](push.md) |
| DELETE | `/api/v1/push/devices/{registration_id}` | 解绑推送设备(幂等 204) | [push](push.md) |
| GET | `/api/v1/push/preferences` | 读取通知偏好(五类开关) | [push](push.md) |
| PATCH | `/api/v1/push/preferences` | 修改通知偏好 | [push](push.md) |
| GET | `/api/v1/notifications` | 站内通知列表(游标分页) | [notifications](notifications.md) |
| GET | `/api/v1/notifications/unread_count` | 未读通知数(角标) | [notifications](notifications.md) |
| POST | `/api/v1/notifications/read` | 标记通知已读(按 ids 或全部) | [notifications](notifications.md) |
| GET | `/api/v1/blocks` | 拉黑列表(分页) | [moderation](moderation.md) |
| POST | `/api/v1/blocks` | 拉黑用户 | [moderation](moderation.md) |
| DELETE | `/api/v1/blocks/{user_id}` | 解除拉黑 | [moderation](moderation.md) |
| GET | `/api/v1/posts` | 动态流(分页) | [feed](feed.md) |
| POST | `/api/v1/posts` | 发布动态(可带图) | [feed](feed.md) |
| GET | `/api/v1/posts/mine` | 我的动态(分页) | [feed](feed.md) |
| GET | `/api/v1/posts/{post_id}` | 动态详情 | [feed](feed.md) |
| DELETE | `/api/v1/posts/{post_id}` | 删除我的动态 | [feed](feed.md) |
| POST | `/api/v1/posts/{post_id}/like` | 点赞 | [feed](feed.md) |
| DELETE | `/api/v1/posts/{post_id}/like` | 取消点赞 | [feed](feed.md) |
| GET | `/api/v1/posts/{post_id}/comments` | 评论列表(分页) | [feed](feed.md) |
| POST | `/api/v1/posts/{post_id}/comments` | 发表评论 | [feed](feed.md) |
| GET | `/api/v1/posts/{post_id}/comments/{comment_id}/replies` | 回复列表(分页) | [feed](feed.md) |
| DELETE | `/api/v1/posts/{post_id}/comments/{comment_id}` | 删除我的评论 | [feed](feed.md) |
| POST | `/api/v1/posts/{post_id}/report` | 举报动态 | [feed](feed.md) |
| GET | `/api/v1/health` | 存活探针 | [health](health.md) |
| GET | `/api/v1/readyz` | 就绪探针(DB/Redis) | [health](health.md) |

> 另有 **imserver 内部接口**(`/im/api/*`:会话列表、历史消息、聊天记录搜索)与 WS 帧,它们不走 `/api/v1` 门禁、不在本目录,文档见 [`docs/ops/imserver.md`](../ops/imserver.md)(§15 已读回执、§16 聊天记录搜索)。

## 如何调用

最短链路:**登录换令牌 → 带令牌调业务接口**。

```bash
# 1. 发送验证码(测试环境验证码固定为 123456,不需要真等短信)
curl -X POST http://<域名>/api/v1/auth/sms/send \
  -H "Content-Type: application/json" -d '{"phone": "13800000001"}'

# 2. 校验验证码换取令牌(响应里的 access / refresh 记下来)
curl -X POST http://<域名>/api/v1/auth/sms/verify \
  -H "Content-Type: application/json" -d '{"phone": "13800000001", "code": "123456"}'

# 3. 之后每个业务接口都带上 access
curl http://<域名>/api/v1/users/me -H "Authorization: Bearer <access>"
```

Base URL、鉴权细节、统一错误结构、分页约定、限流额度见 [conventions.md](conventions.md)。

## 机器可读契约(OpenAPI 3.0)

本目录除了人读的 `*.md`,还有一份**由代码生成**的机器可读契约:

| 项 | 说明 |
|---|---|
| 文件 | [openapi.yml](openapi.yml)(OpenAPI 3.0.3,45 paths / 54 operations) |
| 生成命令 | `cd chatapp && python manage.py spectacular --file ../docs/api/openapi.yml --validate` |
| 谁在读它 | Web 端类型生成(`web/src/api/schema.d.ts`)、CI 门禁、后续客户端工具链 |
| 能否手改 | **不能**。它是生成物,手改会在下一次生成时被覆盖,且 CI 会红 |

维护规则:

1. 改了 `views.py` / `serializers.py` 里任何**对外字段**(改名、增删、改类型)后,
   **同一次改动内**重新跑上面的命令,把 `openapi.yml` 的 diff 一起提交;
2. CI(`backend.yml`「校验 OpenAPI 生成物与代码一致」)会重新生成一次并用 `git diff --exit-code` 比对,
   忘记提交生成物 = 红;
3. 字段级契约写在视图的 `@extend_schema(...)` 上(本项目几乎全是 `@api_view` 函数视图,
   序列化器在函数体里临时构造,库推断不出来),**不要**为了生成 schema 而改视图写法。
4. 生成物对 `drf-spectacular` 版本敏感:升级该库后必须重新生成并提交 diff(否则 CI 会红,
   这是有意的 —— 生成物变了就是契约变了)。
5. **下游派生门禁**(改了 schema 就要一起跑):
   - Web:`cd web && npm run gen:api` → `src/api/schema.d.ts`(纯类型,`web.yml` 比对生成物);
     `src/api/contract.ts` 用 `Exclude<keyof 手写类型, keyof schema>` 做字段名编译期断言;
   - App:`python scripts/check_app_models.py`(静态扫描 `app/lib/features/**/models.dart`
     里所有 `json['...']` 键,断言都在 schema 字段全集里,`contract.yml` 里跑);
   - 版本号:`python scripts/sync_version.py --check`(`app/pubspec.yaml` 为唯一来源)。

## 维护规则(新增/修改接口时必须遵守)

### 1. 每个接口必须有「强制信息行」

每个接口小节标题下方,第一行**必须是**下列格式的信息行(单独一行,方法与路径各用一个反引号,后面用 ` · ` 分隔):

```markdown
> `POST` `/api/v1/auth/sms/send` · 无需鉴权 · 限流 20 次/小时(按 IP)
```

- 路径参数一律写 `{name}`(如 `/api/v1/users/me/photos/{photo_id}`),不写 Django 的 `<int:photo_id>`
- 鉴权写法:需要鉴权 / 无需鉴权;限流写法:无额外限流 或 具体额度(统一写**生产口径**)
- 这一行既是给读者的速览,也是自动检查测试的机器可读标记

### 2. 单接口小节固定 7 个元素

1. 标题:`### <分册号>.<序号> <中文接口名>`
2. 强制信息行(见上)
3. **接口描述**:一段话,含业务规则(有效期、幂等、拉黑/封禁表现、排序等)
4. **请求参数**表:`参数名称 | 必填 | 类型 | 描述`
5. **响应参数**表:`参数名称 | 类型 | 描述`
6. **请求示例**(curl)+ **响应示例**(成功与典型失败各一个,JSON)
7. **错误码**表:`错误码 | HTTP | 描述 | 处理建议`(只列本接口会出现的;全局错误见 [errors.md](errors.md))

`health.md` 为运维探针,用简化格式(信息行 + 描述 + 响应参数/示例 + 状态码含义),不要求 7 元素齐全。

**示例取值政策**:响应示例的结构与取值取自**真实响应**;手机号、令牌、临时文件名等敏感或一次性值做打码 / 替换为等价示例值(如手机号 `139****0010`、JWT 只留前缀)。`message` 文案不改写。

### 3. 新增 / 修改接口的完整步骤

1. 改后端代码(`views.py` / `urls.py` / `serializers.py`)
2. 在对应分册加(或改)接口小节——照上面 7 元素写;字段表以 `serializers.py` 为准,示例以**真实响应**为准,不臆造文案
3. 更新本页「接口一览」表
4. 给视图补/改 `@extend_schema(request=..., responses=...)`(字段级契约),再重新生成 `openapi.yml`
5. 跑 `cd chatapp && python manage.py test config` 确认门禁绿

### 4. 门禁:漏写或残留都会让测试变红

`chatapp/config/tests.py::ApiDocsCoverageTests` 会双向比对:

- URLconf 里有、文档里没有 → 失败(`接口 X 未写文档`)
- 文档里有、URLconf 里没有(接口已删/改名)→ 失败(`文档记录的 X 已不存在`)

也就是说:**新增接口必须同一次改动内补文档,删除接口必须同一次改动内删文档**。检查逻辑在 `chatapp/config/api_doc_coverage.py`,可随时手动查看缺口:

```bash
cd chatapp
python manage.py shell -c "import config.api_doc_coverage as c; [print(p) for p in c.find_problems()]"
```

另有 `chatapp/config/tests.py::OpenApiSchemaTests` 校验「生成出来的 OpenAPI 操作集合 == URLconf 操作集合」,
防止 schema 生成器静默漏掉某个视图。

### 5. 字段与另一接口完全相同时,不要复制表格

「**响应参数**」下单独一行写小节号引用即可,门禁会自动继承该小节的字段表:

```markdown
**响应参数**

同 [5.1 动态流](#51-动态流)(动态对象)。
```

只认「同 [X.Y ...」这个前缀,且只在同一分册内解析。复制表格会让同一份字段要改两处,迟早漂移。

### 6. 字段级门禁(OpenAPI ↔ 文档)

`chatapp/config/test_schema_contract.py` 会双向比对每个接口的「请求参数 / 响应参数」表与
`@extend_schema` 生成的字段:

- 文档表里有、schema 里没有 → 失败(文档承诺了代码没实现的字段)
- schema 里有、文档表里没有 → 失败(代码加了字段但没写文档)

只比**顶层字段**(嵌套结构按「结构见 §X」引用),分页信封(`count` / `next_cursor` / `has_more` / `results`)不参与比对。
每个「请求参数 / 响应参数」标记后只取**第一张**表,后面的子结构表(`tags[]` / `photos[]`)不算顶层字段。
