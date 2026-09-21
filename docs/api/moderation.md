# 举报与拉黑

本分册含 4 个接口:举报用户、拉黑列表、拉黑、解除拉黑。

**拉黑的关键语义**:拉黑是**双向不可见**——拉黑后对方也看不到你,双方从彼此的候选卡、配对列表、在线状态里消失,对方访问你的资料返回「用户不存在」。设置与解除都会同步到 IM 黑名单。举报则只提交给运营处理,不影响双方可见性。

---

### 4.1 举报用户

> `POST` `/api/v1/reports` · 需要鉴权 · 限流 20 次/天(按用户)

**接口描述**

举报某个用户,提交给运营人工处理。**幂等**:同一对象已有未处理的举报时不会重复创建,直接返回已有记录(HTTP 200);首次举报返回 201。处理结果会通过系统消息通知相关方。

**请求参数**(Body,`application/json`)

| 参数名称 | 必填 | 类型 | 描述 |
|----------|------|------|------|
| target_user_id | 是 | Integer | 被举报人的**账号 ID** |
| type | 是 | String | 举报类型:`harassment` 骚扰 / `porn` 色情 / `fraud` 诈骗 / `other` 其他 |
| detail | 否 | String | 补充说明,最长 200 字,可留空 |

**响应参数**

| 参数名称 | 类型 | 描述 |
|----------|------|------|
| id | Integer | 举报记录 ID |
| type | String | 举报类型 |
| status | String | 处理状态:`pending` 待处理 / `handled` 已处理 |

**请求示例**

```bash
curl -X POST http://<域名>/api/v1/reports \
  -H "Authorization: Bearer <access>" \
  -H "Content-Type: application/json" \
  -d '{"target_user_id": 8, "type": "harassment", "detail": "言语骚扰"}'
```

**响应示例**

首次举报(HTTP 201):

```json
{ "id": 4, "type": "harassment", "status": "pending" }
```

重复举报同一人(HTTP 200,返回已有记录,未新建):

```json
{ "id": 4, "type": "harassment", "status": "pending" }
```

举报自己:

```json
{
  "code": 400,
  "message": "不能举报自己",
  "request_id": "9d8525d34dbf45f58b3c411a9c30d6db"
}
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 400 | 400 | 不能举报自己 | 检查 `target_user_id` |
| 400 | 400 | “xxx” 不是合法选项。(`type` 取值非法) | 使用 harassment/porn/fraud/other 之一 |
| 404 | 404 | 目标用户不存在 | 从列表移除该用户 |
| 429 | 429 | 触发限流(20 次/天) | 按 `Retry-After` 等待 |
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |

---

### 4.2 拉黑列表

> `GET` `/api/v1/blocks` · 需要鉴权 · 无额外限流

**接口描述**

分页查询自己拉黑过的人,按拉黑时间倒序。

**请求参数**(Query)

| 参数名称 | 必填 | 类型 | 描述 |
|----------|------|------|------|
| limit | 否 | Integer | 每页条数,默认 20,上限 100 |
| offset | 否 | Integer | 偏移量,默认 0 |

**响应参数**

分页对象(见 [conventions.md §分页约定](conventions.md#分页约定)),`results[]` 字段:

| 参数名称 | 类型 | 描述 |
|----------|------|------|
| user_id | Integer | 被拉黑人的**账号 ID** |
| nickname | String | 昵称(对方未填资料时为空字符串) |
| avatar_url | String / null | 头像(第一张已过审照片);无照片为 `null` |
| blocked_at | String | 拉黑时间(ISO 8601) |

**请求示例**

```bash
curl "http://<域名>/api/v1/blocks?limit=20&offset=0" \
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
      "user_id": 8,
      "nickname": "Bob",
      "avatar_url": "http://<域名>/media/photos/2026/09/bob_avatar.png",
      "blocked_at": "2026-09-21T18:23:15.732865+08:00"
    }
  ]
}
```

无拉黑记录时 `count` 为 0、`results` 为空数组。

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |

---

### 4.3 拉黑用户

> `POST` `/api/v1/blocks` · 需要鉴权 · 无额外限流

**接口描述**

拉黑一个用户。**幂等**:重复拉黑返回同一记录(HTTP 200;首次为 201)。拉黑后:双方互相不可见(候选卡、配对列表、在线状态、资料页都查不到对方),IM 黑名单同步生效。

**请求参数**(Body,`application/json`)

| 参数名称 | 必填 | 类型 | 描述 |
|----------|------|------|------|
| target_user_id | 是 | Integer | 要拉黑的用户**账号 ID** |

**响应参数**

与 4.2 的 `results[]` 单项结构一致(`user_id` / `nickname` / `avatar_url` / `blocked_at`)。

**请求示例**

```bash
curl -X POST http://<域名>/api/v1/blocks \
  -H "Authorization: Bearer <access>" \
  -H "Content-Type: application/json" \
  -d '{"target_user_id": 8}'
```

**响应示例**

首次拉黑(HTTP 201):

```json
{
  "user_id": 8,
  "nickname": "Bob",
  "avatar_url": "http://<域名>/media/photos/2026/09/bob_avatar.png",
  "blocked_at": "2026-09-21T18:23:15.732865+08:00"
}
```

拉黑自己:

```json
{
  "code": 400,
  "message": "不能拉黑自己",
  "request_id": "0aa02fa20aa147db9cc07e04255ea7e6"
}
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 400 | 400 | 不能拉黑自己 | 检查 `target_user_id` |
| 404 | 404 | 目标用户不存在 | 从列表移除该用户 |
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |

---

### 4.4 解除拉黑

> `DELETE` `/api/v1/blocks/{user_id}` · 需要鉴权 · 无额外限流

**接口描述**

解除对某人的拉黑(同时解除 IM 黑名单),之后双方恢复互相可见。**幂等**:未拉黑过的人也返回 204。

**请求参数**

| 参数名称 | 必填 | 类型 | 描述 |
|----------|------|------|------|
| user_id | 是 | Integer | 被拉黑人的**账号 ID**(路径参数) |

**响应参数**

无(HTTP 204,响应体为空)。

**请求示例**

```bash
curl -X DELETE http://<域名>/api/v1/blocks/8 \
  -H "Authorization: Bearer <access>"
```

**响应示例**

```
HTTP/1.1 204 No Content
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |
