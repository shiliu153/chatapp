# 广场动态

本分册含 12 个接口:动态流(列表/发布)、我的动态、详情/删除、点赞/取消、评论(列表/发表/回复列表/删除)、举报动态。

**可见性规则**(贯穿全分册):被双向拉黑或被重封禁的作者,其动态与评论对你看不到(列表过滤、详情 404)。动态作者本人是唯一能删除该动态的人。

---

### 5.1 动态流

> `GET` `/api/v1/posts` · 需要鉴权 · 无额外限流

**接口描述**

分页拉取广场动态流,按发布时间倒序,包含全部用户的可见动态。

**请求参数**(Query)

| 参数名称 | 必填 | 类型 | 描述 |
|----------|------|------|------|
| limit | 否 | Integer | 每页条数,默认 20,上限 100 |
| offset | 否 | Integer | 偏移量,默认 0 |

**响应参数**

分页对象(见 [conventions.md §分页约定](conventions.md#分页约定)),`results[]` 为动态对象:

| 参数名称 | 类型 | 描述 |
|----------|------|------|
| id | Integer | 动态 ID |
| author | Object | 作者摘要,见下表 |
| text | String | 正文,可为空字符串 |
| images | String[] | 图片完整 URL 数组(最多 9 张) |
| like_count | Integer | 点赞数 |
| comment_count | Integer | 评论数 |
| liked_by_me | Boolean | 当前用户是否已点赞 |
| created_at | String | 发布时间(ISO 8601) |

`author` 字段:

| 参数名称 | 类型 | 描述 |
|----------|------|------|
| user_id | Integer | 作者账号 ID |
| nickname | String | 作者昵称(未填资料为空字符串) |
| avatar_url | String / null | 作者头像;无照片为 `null` |

**请求示例**

```bash
curl "http://<域名>/api/v1/posts?limit=20&offset=0" \
  -H "Authorization: Bearer <access>"
```

**响应示例**

```json
{
  "count": 9,
  "next": "http://<域名>/api/v1/posts?limit=20&offset=20",
  "previous": null,
  "results": [
    {
      "id": 9,
      "author": {
        "user_id": 12,
        "nickname": "小雨12",
        "avatar_url": "http://<域名>/media/photos/2026/09/seed_12_0.jpg"
      },
      "text": "今天去看了日落",
      "images": [],
      "like_count": 2,
      "comment_count": 0,
      "liked_by_me": false,
      "created_at": "2026-09-18T21:33:44.962751+08:00"
    }
  ]
}
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |

---

### 5.2 发布动态

> `POST` `/api/v1/posts` · 需要鉴权 · 限流 20 次/天(按用户)

**接口描述**

发布一条动态,文字与图片至少要有一样。正文与图片都会经过内容校验。

**请求参数**(`multipart/form-data`)

| 参数名称 | 必填 | 类型 | 描述 |
|----------|------|------|------|
| text | 否 | String | 正文,最长 500 字;含违规词返回 400。与 `images` 至少填一个 |
| images | 否 | File[] | 图片文件,可多张(表单字段名固定为 `images`,重复该字段多次);**最多 9 张、单张不超过 5MB**、必须是有效图片 |

**响应参数**(HTTP 201)

动态对象,结构见 5.1。

**请求示例**

```bash
curl -X POST http://<域名>/api/v1/posts \
  -H "Authorization: Bearer <access>" \
  -F "text=周末去哪儿玩?" \
  -F "images=@photo1.png" \
  -F "images=@photo2.png"
```

**响应示例**

```json
{
  "id": 10,
  "author": {
    "user_id": 12,
    "nickname": "小雨12",
    "avatar_url": "http://<域名>/media/photos/2026/09/seed_12_0.jpg"
  },
  "text": "周末去哪儿玩?",
  "images": ["http://<域名>/media/posts/2026/09/example.png"],
  "like_count": 0,
  "comment_count": 0,
  "liked_by_me": false,
  "created_at": "2026-09-21T18:24:54.674857+08:00"
}
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 400 | 400 | 写点文字或选张图片吧 | 至少填 `text` 或传一张图片 |
| 400 | 400 | 内容包含违规内容,请修改 | 修改正文后重试 |
| 400 | 400 | 最多 9 张图片 | 减少图片数量 |
| 400 | 400 | 单张图片不能超过 5MB | 压缩后重试 |
| 400 | 400 | 图片校验失败(非图片或已损坏) | 更换图片文件 |
| 41301 | 413 | 账号媒体存储已满(message 含已用/上限) | 提示用户删除部分照片,或等待聊天媒体过期 |
| 429 | 429 | 触发限流(20 次/天) | 按 `Retry-After` 等待 |
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |

---

### 5.3 我的动态

> `GET` `/api/v1/posts/mine` · 需要鉴权 · 无额外限流

**接口描述**

分页拉取自己发布过的全部动态,按发布时间倒序。与 5.1 的区别:不做可见性过滤,自己的动态全部返回。

**请求参数**(Query)

| 参数名称 | 必填 | 类型 | 描述 |
|----------|------|------|------|
| limit | 否 | Integer | 每页条数,默认 20,上限 100 |
| offset | 否 | Integer | 偏移量,默认 0 |

**响应参数**

与 5.1 相同的分页对象。

**请求示例**

```bash
curl "http://<域名>/api/v1/posts/mine?limit=20&offset=0" \
  -H "Authorization: Bearer <access>"
```

**响应示例**

```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 10,
      "author": {
        "user_id": 12,
        "nickname": "小雨12",
        "avatar_url": "http://<域名>/media/photos/2026/09/seed_12_0.jpg"
      },
      "text": "周末去哪儿玩?",
      "images": [],
      "like_count": 0,
      "comment_count": 0,
      "liked_by_me": false,
      "created_at": "2026-09-21T18:24:54.674857+08:00"
    }
  ]
}
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |

---

### 5.4 动态详情

> `GET` `/api/v1/posts/{post_id}` · 需要鉴权 · 无额外限流

**接口描述**

获取单条动态的详情。

**请求参数**

| 参数名称 | 必填 | 类型 | 描述 |
|----------|------|------|------|
| post_id | 是 | Integer | 动态 ID(路径参数) |

**响应参数**

动态对象,结构见 5.1。

**请求示例**

```bash
curl http://<域名>/api/v1/posts/9 \
  -H "Authorization: Bearer <access>"
```

**响应示例**

```json
{
  "id": 9,
  "author": {
    "user_id": 12,
    "nickname": "小雨12",
    "avatar_url": "http://<域名>/media/photos/2026/09/seed_12_0.jpg"
  },
  "text": "今天去看了日落",
  "images": [],
  "like_count": 2,
  "comment_count": 0,
  "liked_by_me": false,
  "created_at": "2026-09-18T21:33:44.962751+08:00"
}
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 404 | 404 | 动态不存在,或作者与你互相拉黑/被重封禁 | 从列表移除该条,不要重试 |
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |

---

### 5.5 删除动态

> `DELETE` `/api/v1/posts/{post_id}` · 需要鉴权 · 无额外限流

**接口描述**

删除自己发布的动态(连同图片与评论一起删除)。**只有作者本人能删**:非作者或动态不存在一律返回 404。

**请求参数**

| 参数名称 | 必填 | 类型 | 描述 |
|----------|------|------|------|
| post_id | 是 | Integer | 动态 ID(路径参数) |

**响应参数**

无(HTTP 204,响应体为空)。

**请求示例**

```bash
curl -X DELETE http://<域名>/api/v1/posts/10 \
  -H "Authorization: Bearer <access>"
```

**响应示例**

```
HTTP/1.1 204 No Content
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 404 | 404 | 动态不存在,或你不是作者 | 刷新列表后重试 |
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |

---

### 5.6 点赞

> `POST` `/api/v1/posts/{post_id}/like` · 需要鉴权 · 无额外限流

**接口描述**

给动态点赞。**幂等**:重复点赞不会重复计数(首次 201,重复 200),响应恒为 `liked: true`。

**请求参数**

| 参数名称 | 必填 | 类型 | 描述 |
|----------|------|------|------|
| post_id | 是 | Integer | 动态 ID(路径参数) |

**响应参数**

| 参数名称 | 类型 | 描述 |
|----------|------|------|
| liked | Boolean | 固定为 `true` |

**请求示例**

```bash
curl -X POST http://<域名>/api/v1/posts/9/like \
  -H "Authorization: Bearer <access>"
```

**响应示例**

```json
{ "liked": true }
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 404 | 404 | 动态不存在或不可见 | 从列表移除该条 |
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |

---

### 5.7 取消点赞

> `DELETE` `/api/v1/posts/{post_id}/like` · 需要鉴权 · 无额外限流

**接口描述**

取消点赞。**幂等**:未点赞过也返回 204。

**请求参数**

| 参数名称 | 必填 | 类型 | 描述 |
|----------|------|------|------|
| post_id | 是 | Integer | 动态 ID(路径参数) |

**响应参数**

无(HTTP 204,响应体为空)。

**请求示例**

```bash
curl -X DELETE http://<域名>/api/v1/posts/9/like \
  -H "Authorization: Bearer <access>"
```

**响应示例**

```
HTTP/1.1 204 No Content
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 404 | 404 | 动态不存在或不可见 | 从列表移除该条 |
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |

---

### 5.8 评论列表

> `GET` `/api/v1/posts/{post_id}/comments` · 需要鉴权 · 无额外限流

**接口描述**

分页拉取某条动态的**顶级评论**(回复不单独分页,内嵌在每条评论里)。作者被双向拉黑或被重封禁的评论不会返回;`reply_count` 与 `replies` 同样按可见性过滤。

**请求参数**

| 参数名称 | 必填 | 类型 | 描述 |
|----------|------|------|------|
| post_id | 是 | Integer | 动态 ID(路径参数) |
| limit | 否 | Integer | 每页条数,默认 20,上限 100(Query) |
| offset | 否 | Integer | 偏移量,默认 0(Query) |

**响应参数**

分页对象,`results[]` 字段:

| 参数名称 | 类型 | 描述 |
|----------|------|------|
| id | Integer | 评论 ID |
| author | Object | 评论者摘要(`user_id` / `nickname` / `avatar_url`,同 5.1) |
| text | String | 评论内容 |
| parent_id | Integer / null | 顶级评论为 `null`;回复为所属顶级评论 ID |
| reply_to | Object / null | 被回复者摘要 `{user_id, nickname}`;顶级评论为 `null` |
| reply_count | Integer | 该楼层的可见回复总数(回复对象恒为 0) |
| replies | Object[] | 内嵌的前 2 条回复,结构同本表(回复对象恒为空数组) |
| created_at | String | 评论时间(ISO 8601) |

**请求示例**

```bash
curl "http://<域名>/api/v1/posts/9/comments?limit=20&offset=0" \
  -H "Authorization: Bearer <access>"
```

**响应示例**

```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 3,
      "author": {
        "user_id": 12,
        "nickname": "小雨12",
        "avatar_url": "http://<域名>/media/photos/2026/09/seed_12_0.jpg"
      },
      "text": "好看!",
      "parent_id": null,
      "reply_to": null,
      "reply_count": 1,
      "replies": [
        {
          "id": 4,
          "author": {
            "user_id": 7,
            "nickname": "阿哲",
            "avatar_url": "http://<域名>/media/photos/2026/09/seed_7_0.jpg"
          },
          "text": "同问",
          "parent_id": 3,
          "reply_to": {"user_id": 12, "nickname": "小雨12"},
          "reply_count": 0,
          "replies": [],
          "created_at": "2026-10-20T10:05:00+08:00"
        }
      ],
      "created_at": "2026-09-21T18:25:27.828229+08:00"
    }
  ]
}
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 404 | 404 | 动态不存在或不可见 | 从列表移除该条 |
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |

---

### 5.9 发表评论

> `POST` `/api/v1/posts/{post_id}/comments` · 需要鉴权 · 限流 60 次/天(按用户)

**接口描述**

给动态发表评论或回复。`parent_id` 为空时是顶级评论,评论成功后动态作者会收到一条系统通知;`parent_id` 非空时是回复,被回复者会收到「X 回复了你」的系统通知(自己回复自己不提醒)。层级恒为两级:回复一条回复时,新回复仍挂在同一楼层,`reply_to` 记录真正被回复的人。

**请求参数**

| 参数名称 | 必填 | 类型 | 描述 |
|----------|------|------|------|
| post_id | 是 | Integer | 动态 ID(路径参数) |
| text | 是 | String | 评论内容,最长 200 字,不能为空(纯空白视为空);含违规词返回 400(Body,`application/json`) |
| parent_id | 否 | Integer | 被回复的评论 ID;不传 = 发表顶级评论。指向回复时服务端自动归到其顶级评论 |

**响应参数**(HTTP 201)

| 参数名称 | 类型 | 描述 |
|----------|------|------|
| id | Integer | 评论 ID |
| author | Object | 评论者摘要,同 5.1 |
| text | String | 评论内容 |
| parent_id | Integer / null | 顶级评论为 `null`;回复为所属顶级评论 ID |
| reply_to | Object / null | 被回复者摘要 `{user_id, nickname}`;顶级评论为 `null` |
| reply_count | Integer | 该楼层的可见回复总数(新回复恒为 0) |
| replies | Object[] | 内嵌的前 2 条回复(新回复恒为空数组) |
| created_at | String | 评论时间 |

**请求示例**

```bash
curl -X POST http://<域名>/api/v1/posts/9/comments \
  -H "Authorization: Bearer <access>" \
  -H "Content-Type: application/json" \
  -d '{"text": "好看!"}'
```

**响应示例**

```json
{
  "id": 3,
  "author": {
    "user_id": 12,
    "nickname": "小雨12",
    "avatar_url": "http://<域名>/media/photos/2026/09/seed_12_0.jpg"
  },
  "text": "好看!",
  "parent_id": null,
  "reply_to": null,
  "reply_count": 0,
  "replies": [],
  "created_at": "2026-09-21T18:25:27.828229+08:00"
}
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 400 | 400 | 评论不能为空 | 输入内容后重试 |
| 400 | 400 | 评论包含违规内容,请修改 | 修改后重试 |
| 404 | 404 | 动态不存在或不可见 | 从列表移除该条 |
| 429 | 429 | 触发限流(60 次/天) | 按 `Retry-After` 等待 |
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |

---

### 5.10 举报动态

> `POST` `/api/v1/posts/{post_id}/report` · 需要鉴权 · 限流 20 次/天(按用户)

**接口描述**

举报一条动态,提交运营人工处理。**幂等**:对同一条动态已有未处理举报时不重复创建(HTTP 200;首次 201);并发提交由数据库唯一约束兜底,不会产生两条待处理记录。举报被处理后可再次举报同一动态。不能举报自己的动态。

**请求参数**

| 参数名称 | 必填 | 类型 | 描述 |
|----------|------|------|------|
| post_id | 是 | Integer | 动态 ID(路径参数) |
| type | 是 | String | 举报类型:`harassment` 骚扰 / `porn` 色情 / `fraud` 诈骗 / `other` 其他(Body,`application/json`) |
| detail | 否 | String | 补充说明,最长 200 字 |

**响应参数**

| 参数名称 | 类型 | 描述 |
|----------|------|------|
| id | Integer | 举报记录 ID |
| status | String | 处理状态:`pending` 待处理 / `handled` 已处理 |

**请求示例**

```bash
curl -X POST http://<域名>/api/v1/posts/9/report \
  -H "Authorization: Bearer <access>" \
  -H "Content-Type: application/json" \
  -d '{"type": "other", "detail": "广告内容"}'
```

**响应示例**

首次举报(HTTP 201;重复举报 HTTP 200,返回同一记录):

```json
{ "id": 1, "status": "pending" }
```

举报自己的动态:

```json
{
  "code": 400,
  "message": "不能举报自己的动态",
  "request_id": "7dc2bb3ec6c64468adee44f155140b91"
}
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 400 | 400 | 不能举报自己的动态 | 检查 `post_id` |
| 400 | 400 | “xxx” 不是合法选项。(`type` 取值非法) | 使用 harassment/porn/fraud/other 之一 |
| 404 | 404 | 动态不存在或不可见 | 从列表移除该条 |
| 429 | 429 | 触发限流(20 次/天) | 按 `Retry-After` 等待 |
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |

---

### 5.11 回复列表

> `GET` `/api/v1/posts/{post_id}/comments/{comment_id}/replies` · 需要鉴权 · 无额外限流

**接口描述**

分页拉取某条顶级评论下的全部回复,按时间正序(早 → 晚)。作者被双向拉黑或被重封禁的回复不会返回。`comment_id` 不存在、不属于该动态、或本身就是一条回复时返回 404。

**请求参数**

| 参数名称 | 必填 | 类型 | 描述 |
|----------|------|------|------|
| post_id | 是 | Integer | 动态 ID(路径参数) |
| comment_id | 是 | Integer | 顶级评论 ID(路径参数) |
| limit | 否 | Integer | 每页条数,默认 20,上限 100(Query) |
| offset | 否 | Integer | 偏移量,默认 0(Query) |

**响应参数**

分页对象,`results[]` 为回复对象,字段见 5.8(其中 `replies` 恒为空数组、`reply_count` 恒为 0)。

**请求示例**

```bash
curl "http://<域名>/api/v1/posts/9/comments/3/replies?limit=20&offset=0" \
  -H "Authorization: Bearer <access>"
```

**响应示例**

```json
{
  "count": 2,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 5,
      "author": {
        "user_id": 12,
        "nickname": "小雨12",
        "avatar_url": "http://<域名>/media/photos/2026/09/seed_12_0.jpg"
      },
      "text": "同问",
      "parent_id": 3,
      "reply_to": {"user_id": 7, "nickname": "阿哲"},
      "reply_count": 0,
      "replies": [],
      "created_at": "2026-10-20T10:05:00+08:00"
    }
  ]
}
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 404 | 404 | 动态不可见,或评论不存在 / 不属于该动态 / 本身是回复 | 从列表移除该楼层,不要重试 |
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |

---

### 5.12 删除评论

> `DELETE` `/api/v1/posts/{post_id}/comments/{comment_id}` · 需要鉴权 · 无额外限流

**接口描述**

删除自己发表的评论。**只有作者本人能删**:非作者、评论不存在、不属于该动态一律返回 404。删除顶级评论会**连带删除该楼全部回复**;删除回复只删这一条。删除后动态的 `comment_count` 相应减少。

**请求参数**

| 参数名称 | 必填 | 类型 | 描述 |
|----------|------|------|------|
| post_id | 是 | Integer | 动态 ID(路径参数) |
| comment_id | 是 | Integer | 评论 ID(路径参数) |

**响应参数**

无(HTTP 204,响应体为空)。

**请求示例**

```bash
curl -X DELETE "http://<域名>/api/v1/posts/9/comments/3" \
  -H "Authorization: Bearer <access>"
```

**响应示例**

```
HTTP/1.1 204 No Content
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 404 | 404 | 动态不可见,或评论不存在 / 不属于该动态 / 不是自己发的 | 刷新评论列表后重试 |
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |
