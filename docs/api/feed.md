# 广场动态

本分册含 19 个接口:动态流(列表/发布)、我的动态、详情/删除、点赞/取消、点赞列表、收藏/取消收藏、我的收藏、评论(列表/发表/回复列表/删除)、举报动态、关注/取消关注、关注流。

**可见性规则**(贯穿全分册):被双向拉黑或被重封禁的作者,其动态与评论对你看不到(列表过滤、详情 404)。动态作者本人是唯一能删除该动态的人。

**关注关系**(批次 I):`POST`/`DELETE /api/v1/users/{user_id}/follow` 建立/解除单向关注;`GET /api/v1/feed/following` 只看关注的人的动态。关注**不产生聊天权限、不发通知**(新粉丝不通知),只影响「关注」tab 的内容。

**收藏**(批次 U):`POST`/`DELETE /api/v1/posts/{post_id}/favorite` 收藏/取消收藏一条动态(恒 204 幂等),`GET /api/v1/feed/favorites` 拉「我的收藏」。收藏是**私密书签**:不通知作者、不产生聊天灰条;**排序按收藏时间倒序**(不是发帖时间);动态序列化器的 `is_favorited` 表示「当前用户是否已收藏这条」。

---

### 5.1 动态流

> `GET` `/api/v1/posts` · 需要鉴权 · 无额外限流

**接口描述**

分页拉取广场动态流,按发布时间倒序,包含全部用户的可见动态。

**请求参数**(Query)

| 参数名称 | 必填 | 类型 | 描述 |
|----------|------|------|------|
| limit | 否 | Integer | 每页条数,默认 20,上限 100 |
| before | 否 | String | 游标。首页不传;之后原样回传上一页的 `next_cursor`(见 [conventions.md §分页约定](conventions.md#分页约定)) |

**响应参数**

游标分页对象(见 [conventions.md §分页约定](conventions.md#分页约定)),`results[]` 为动态对象:

| 参数名称 | 类型 | 描述 |
|----------|------|------|
| id | Integer | 动态 ID |
| author | Object | 作者摘要,见下表 |
| text | String | 正文,可为空字符串 |
| images | String[] | 图片完整 URL 数组(最多 9 张) |
| like_count | Integer | 点赞数 |
| comment_count | Integer | 评论数 |
| liked_by_me | Boolean | 当前用户是否已点赞 |
| is_favorited | Boolean | 当前用户是否已收藏(批次 U;收藏是私密书签,见 [5.17 收藏动态](#517-收藏动态)) |
| created_at | String | 发布时间(ISO 8601) |

`author` 字段:

| 参数名称 | 类型 | 描述 |
|----------|------|------|
| user_id | Integer | 作者账号 ID |
| nickname | String | 作者昵称(未填资料为空字符串) |
| avatar_url | String / null | 作者头像;无照片为 `null` |

**请求示例**

```bash
curl "http://<域名>/api/v1/posts?limit=20" \
  -H "Authorization: Bearer <access>"

# 第二页:把上一页响应里的 next_cursor 原样带回来
curl "http://<域名>/api/v1/posts?limit=20&before=<next_cursor>" \
  -H "Authorization: Bearer <access>"
```

**响应示例**

```json
{
  "count": 9,
  "next_cursor": "MjAyNi0wOS0xOFQyMTozMzo0NC45NjI3NTErMDg6MDB8OQ",
  "has_more": true,
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
      "is_favorited": false,
      "created_at": "2026-09-18T21:33:44.962751+08:00"
    }
  ]
}
```

> **老客户端兼容**:请求里带 `offset`(且不带 `before`)时按 offset 分页,响应回到
> `{count, next, previous, results}`。新代码请用游标。

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 400 | 400 | 游标无效(`before` 不是合法游标) | 清空列表,从第一页重拉 |
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

同 [5.1 动态流](#51-动态流)(动态对象)。

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
| before | 否 | String | 游标。首页不传;之后原样回传上一页的 `next_cursor` |

**响应参数**

游标分页对象(`count` / `next_cursor` / `has_more` / `results`);
带 `offset` 的老客户端仍得到 `{count, next, previous, results}`。

同 [5.1 动态流](#51-动态流)(`results[]` 条目字段)。

**请求示例**

```bash
curl "http://<域名>/api/v1/posts/mine?limit=20" \
  -H "Authorization: Bearer <access>"
```

**响应示例**

```json
{
  "count": 1,
  "next_cursor": null,
  "has_more": false,
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
      "is_favorited": true,
      "created_at": "2026-09-21T18:24:54.674857+08:00"
    }
  ]
}
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 400 | 400 | 游标无效 | 清空列表,从第一页重拉 |
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

同 [5.1 动态流](#51-动态流)(动态对象)。

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
  "is_favorited": false,
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

> `GET` `/api/v1/posts/{post_id}/comments/{comment_id}/replies` · 需要鉴权 · 限流 360 次/小时(按用户)

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

分页对象,`results[]` 为回复对象(其中 `replies` 恒为空数组、`reply_count` 恒为 0)。

同 [5.8 评论列表](#58-评论列表)。

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
| 429 | 429 | 触发限流(360 次/小时) | 按 `Retry-After` 等待 |

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

---

### 5.13 关注

> `POST` `/api/v1/users/{user_id}/follow` · 需要鉴权 · 限流 120 次/小时(按用户)

**接口描述**

关注某人。**幂等**:已关注过也返回 204,不会重复建立关系。关注是**单向**关系,不建立聊天权限、不发通知(新粉丝不通知)。不能关注自己(400);与我互相拉黑、对方不存在或处于重封禁状态一律 404(统一按「用户不存在」处理,不泄漏账号是否存在)。

**请求参数**

| 参数名称 | 必填 | 类型 | 描述 |
|----------|------|------|------|
| user_id | 是 | Integer | 被关注的账号 ID(路径参数) |

**响应参数**

无(HTTP 204,响应体为空)。

**请求示例**

```bash
curl -X POST http://<域名>/api/v1/users/12/follow \
  -H "Authorization: Bearer <access>"
```

**响应示例**

```
HTTP/1.1 204 No Content
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 400 | 400 | 关注自己 | 隐藏关注按钮 |
| 404 | 404 | 对方不存在 / 与我互相拉黑 / 对方重封禁 | 从页面移除该用户 |
| 429 | 429 | 触发关注限流(120 次/小时) | 稍后重试 |
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |

---

### 5.14 取消关注

> `DELETE` `/api/v1/users/{user_id}/follow` · 需要鉴权 · 限流 120 次/小时(按用户)

**接口描述**

取消关注某人。**幂等**:没关注过也返回 204。取消关注只影响「关注」tab 的内容,不影响已配对关系与聊天权限。

**请求参数**

| 参数名称 | 必填 | 类型 | 描述 |
|----------|------|------|------|
| user_id | 是 | Integer | 被取消关注的账号 ID(路径参数) |

**响应参数**

无(HTTP 204,响应体为空)。

**请求示例**

```bash
curl -X DELETE http://<域名>/api/v1/users/12/follow \
  -H "Authorization: Bearer <access>"
```

**响应示例**

```
HTTP/1.1 204 No Content
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 400 | 400 | 取消关注自己 | 隐藏关注按钮 |
| 404 | 404 | 对方不存在 / 与我互相拉黑 / 对方重封禁 | 从页面移除该用户 |
| 429 | 429 | 触发关注限流(120 次/小时) | 稍后重试 |
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |

---

### 5.15 关注流

> `GET` `/api/v1/feed/following` · 需要鉴权 · 限流 240 次/小时(按用户)

**接口描述**

分页拉取**我关注的人**的动态,按发布时间倒序。口径与广场动态流一致(排除双向拉黑与重封禁作者),但作者范围收窄到我的关注列表;**不含自己的动态**(自己的动态见 [5.3 我的动态](#53-我的动态))。没关注任何人时返回空列表。

**请求参数**(Query)

| 参数名称 | 必填 | 类型 | 描述 |
|----------|------|------|------|
| limit | 否 | Integer | 每页条数,默认 20,上限 100 |
| before | 否 | String | 游标。首页不传;之后原样回传上一页的 `next_cursor`(见 [conventions.md §分页约定](conventions.md#分页约定)) |

**响应参数**

同 [5.1 动态流](#51-动态流)(游标分页对象,`results[]` 为动态对象)。

**请求示例**

```bash
curl "http://<域名>/api/v1/feed/following?limit=20" \
  -H "Authorization: Bearer <access>"

# 第二页:把上一页响应里的 next_cursor 原样带回来
curl "http://<域名>/api/v1/feed/following?limit=20&before=<next_cursor>" \
  -H "Authorization: Bearer <access>"
```

**响应示例**

```json
{
  "count": 2,
  "next_cursor": null,
  "has_more": false,
  "results": [
    {
      "id": 12,
      "author": {
        "user_id": 8,
        "nickname": "小雨8",
        "avatar_url": null
      },
      "text": "关注的人发的动态",
      "images": [],
      "like_count": 0,
      "comment_count": 0,
      "liked_by_me": false,
      "is_favorited": false,
      "created_at": "2026-11-07T01:20:00.000000+08:00"
    }
  ]
}
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 400 | 400 | 游标无效(`before` 不是合法游标) | 清空列表,从第一页重拉 |
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |
| 429 | 429 | 触发限流(240 次/小时) | 按 `Retry-After` 等待 |

---

### 5.16 点赞列表

> `GET` `/api/v1/posts/{post_id}/likes` · 需要鉴权 · 限流 120 次/小时(按用户)

**接口描述**

拉取「谁点了赞」,按**点赞时间倒序**(同一毫秒按主键倒序)。计数口径与列表一致:被双向拉黑(任一方向)或被重封禁的账号**既不出现也不计入** `count`,因此 `count` 是**过滤后**的可见人数,不是动态上的 `like_count`。

没人点赞返回 200 + `results: []`(不 404);动态不存在、与你互相拉黑、作者被重封禁一律 404。新接口没有老客户端,**不提供 `offset` 兼容分支**(与 [5.15 关注流](#515-关注流)同口径)。

**请求参数**

| 参数名称 | 必填 | 类型 | 描述 |
|----------|------|------|------|
| post_id | 是 | Integer | 动态 ID(路径参数) |
| limit | 否 | Integer | 每页条数,默认 20,上限 100 |
| before | 否 | String | 游标。首页不传;之后原样回传上一页的 `next_cursor`(见 [conventions.md §分页约定](conventions.md#分页约定)) |

**响应参数**

`results[]` 的元素:

| 参数名称 | 类型 | 描述 |
|----------|------|------|
| user_id | Integer | 点赞者的账号 ID |
| nickname | String | 点赞者昵称(未填资料为空字符串) |
| avatar_url | String / null | 点赞者头像;无已过审照片为 `null` |
| liked_at | String | 点赞时间(ISO 8601) |

**请求示例**

```bash
curl "http://<域名>/api/v1/posts/9/likes?limit=20" \
  -H "Authorization: Bearer <access>"

# 第二页:把上一页响应里的 next_cursor 原样带回来
curl "http://<域名>/api/v1/posts/9/likes?limit=20&before=<next_cursor>" \
  -H "Authorization: Bearer <access>"
```

**响应示例**

```json
{
  "count": 2,
  "next_cursor": null,
  "has_more": false,
  "results": [
    {
      "user_id": 8,
      "nickname": "小雨8",
      "avatar_url": null,
      "liked_at": "2026-11-10T14:02:11.482931+08:00"
    }
  ]
}
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 400 | 400 | 游标无效(`before` 不是合法游标) | 清空列表,从第一页重拉 |
| 404 | 404 | 动态不存在或不可见 | 返回上一页,从列表移除该条 |
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |
| 429 | 429 | 触发限流(120 次/小时) | 按 `Retry-After` 等待 |

---

### 5.17 收藏动态

> `POST` `/api/v1/posts/{post_id}/favorite` · 需要鉴权 · 限流 300 次/小时(按用户,与取消收藏共用额度)

**接口描述**

把一条动态加入「我的收藏」。**恒 204**,首次收藏与重复收藏都是 204(与 [5.13 关注](#513-关注)同口径:客户端只做乐观翻转,不需要知道「是不是第一次」)。

收藏是**私密书签**:不给作者发通知、不产生聊天灰条。收藏自己的动态允许。动态不可见时 404。

**请求参数**

| 参数名称 | 必填 | 类型 | 描述 |
|----------|------|------|------|
| post_id | 是 | Integer | 动态 ID(路径参数) |

**响应参数**

无(HTTP 204,响应体为空)。

**请求示例**

```bash
curl -X POST http://<域名>/api/v1/posts/9/favorite \
  -H "Authorization: Bearer <access>"
```

**响应示例**

```
HTTP/1.1 204 No Content
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 404 | 404 | 动态不存在或不可见 | 从列表移除该条,不要重试 |
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |
| 429 | 429 | 触发限流(300 次/小时) | 按 `Retry-After` 等待 |

---

### 5.18 取消收藏

> `DELETE` `/api/v1/posts/{post_id}/favorite` · 需要鉴权 · 限流 300 次/小时(按用户,与收藏共用额度)

**接口描述**

把一条动态移出「我的收藏」。**恒 204**:没收藏过也返回 204(幂等)。

**请求参数**

| 参数名称 | 必填 | 类型 | 描述 |
|----------|------|------|------|
| post_id | 是 | Integer | 动态 ID(路径参数) |

**响应参数**

无(HTTP 204,响应体为空)。

**请求示例**

```bash
curl -X DELETE http://<域名>/api/v1/posts/9/favorite \
  -H "Authorization: Bearer <access>"
```

**响应示例**

```
HTTP/1.1 204 No Content
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 404 | 404 | 动态不存在或不可见 | 从列表移除该条,不要重试 |
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |
| 429 | 429 | 触发限流(300 次/小时) | 按 `Retry-After` 等待 |

---

### 5.19 我的收藏

> `GET` `/api/v1/feed/favorites` · 需要鉴权 · 限流 120 次/小时(按用户)

**接口描述**

分页拉取我收藏过的动态,**按收藏时间倒序**(不是发帖时间:先收藏新帖、后收藏老帖时,老帖排在前面)。响应形状与 [5.1 动态流](#51-动态流)逐字段一致。

可见性沿用广场口径:收藏了但已不可见的动态(被双向拉黑、作者被重封禁)**既不返回也不计入 `count`**;动态被删除时收藏关系一并消失,列表自动少一条。新接口不提供 `offset` 兼容分支。

**请求参数**(Query)

| 参数名称 | 必填 | 类型 | 描述 |
|----------|------|------|------|
| limit | 否 | Integer | 每页条数,默认 20,上限 100 |
| before | 否 | String | 游标。首页不传;之后原样回传上一页的 `next_cursor` |

**响应参数**

同 [5.1 动态流](#51-动态流)(游标分页对象,`results[]` 为动态对象,含 `is_favorited`)。

**请求示例**

```bash
curl "http://<域名>/api/v1/feed/favorites?limit=20" \
  -H "Authorization: Bearer <access>"
```

**响应示例**

```json
{
  "count": 1,
  "next_cursor": null,
  "has_more": false,
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
      "is_favorited": true,
      "created_at": "2026-09-18T21:33:44.962751+08:00"
    }
  ]
}
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 400 | 400 | 游标无效(`before` 不是合法游标) | 清空列表,从第一页重拉 |
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |
| 429 | 429 | 触发限流(120 次/小时) | 按 `Retry-After` 等待 |
