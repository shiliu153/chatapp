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
| [feed.md](feed.md) | 广场动态 |
| [im.md](im.md) | IM 会话凭证 |
| [health.md](health.md) | 运维探针(供监控使用,客户端不需要调用) |

## 接口一览

共 **32** 个接口(按「方法 + 路径」计)。

| 方法 | 路径 | 说明 | 分册 |
|---|---|---|---|
| POST | `/api/v1/auth/sms/send` | 发送短信验证码 | [auth](auth.md) |
| POST | `/api/v1/auth/sms/verify` | 校验验证码并登录(未注册自动建号) | [auth](auth.md) |
| POST | `/api/v1/auth/token/refresh` | 刷新访问令牌 | [auth](auth.md) |
| GET | `/api/v1/users/me` | 获取我的资料 | [users](users.md) |
| PATCH | `/api/v1/users/me` | 修改我的资料 | [users](users.md) |
| GET | `/api/v1/users/tags` | 获取标签池 | [users](users.md) |
| POST | `/api/v1/users/me/photos` | 上传照片 | [users](users.md) |
| DELETE | `/api/v1/users/me/photos/{photo_id}` | 删除照片 | [users](users.md) |
| GET | `/api/v1/users/me/preference` | 获取择偶偏好 | [users](users.md) |
| PATCH | `/api/v1/users/me/preference` | 修改择偶偏好 | [users](users.md) |
| GET | `/api/v1/users/{user_id}` | 获取他人公开资料 | [users](users.md) |
| GET | `/api/v1/presence` | 批量查询在线状态 | [users](users.md) |
| GET | `/api/v1/discovery/candidates` | 拉取候选卡 | [discovery](discovery.md) |
| POST | `/api/v1/discovery/swipe` | 提交滑卡动作 | [discovery](discovery.md) |
| GET | `/api/v1/matches` | 配对列表(分页) | [discovery](discovery.md) |
| POST | `/api/v1/im/user_sig` | 获取 IM userSig | [im](im.md) |
| POST | `/api/v1/reports` | 举报用户 | [moderation](moderation.md) |
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
| POST | `/api/v1/posts/{post_id}/report` | 举报动态 | [feed](feed.md) |
| GET | `/api/v1/health` | 存活探针 | [health](health.md) |
| GET | `/api/v1/readyz` | 就绪探针(DB/Redis) | [health](health.md) |

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

`health.md` 为运维探针,用简化格式(信息行 + 描述 + 响应示例 + 状态码含义),不要求参数表。

### 3. 新增 / 修改接口的完整步骤

1. 改后端代码(`views.py` / `urls.py` / `serializers.py`)
2. 在对应分册加(或改)接口小节——照上面 7 元素写;字段表以 `serializers.py` 为准,示例以**真实响应**为准,不臆造文案
3. 更新本页「接口一览」表
4. 跑 `cd chatapp && python manage.py test config` 确认门禁绿

### 4. 门禁:漏写或残留都会让测试变红

`chatapp/config/tests.py::ApiDocsCoverageTests` 会双向比对:

- URLconf 里有、文档里没有 → 失败(`接口 X 未写文档`)
- 文档里有、URLconf 里没有(接口已删/改名)→ 失败(`文档记录的 X 已不存在`)

也就是说:**新增接口必须同一次改动内补文档,删除接口必须同一次改动内删文档**。检查逻辑在 `chatapp/config/api_doc_coverage.py`,可随时手动查看缺口:

```bash
cd chatapp
python manage.py shell -c "import config.api_doc_coverage as c; [print(p) for p in c.find_problems()]"
```
