# 发现与配对

本分册含 3 个接口:拉取候选卡、提交滑卡动作、查询配对列表。

配对逻辑:双方都 `like` 即配对成功(滑卡时响应 `matched: true`,同时双方会各收到一条系统消息)。

---

### 3.1 拉取候选卡

> `GET` `/api/v1/discovery/candidates` · 需要鉴权 · 无额外限流

**接口描述**

拉取一批供滑卡的候选用户。候选池的筛选规则:

- **排除**:自己、自己划过的人(不论 like/pass)、已配对的人、与你双向拉黑的人
- **只推资料完善的人**:`status = complete` 且**至少有 1 张已过审照片**
- **按你的择偶偏好过滤**(见 [users.md §2.6](users.md)):目标性别(未设置=不限)、城市(未设置=不限)、年龄区间
- 返回顺序为**随机**(保证每次刷新看到的顺序不同)

**请求参数**(Query)

| 参数名称 | 必填 | 类型 | 描述 |
|----------|------|------|------|
| limit | 否 | Integer | 拉取条数,默认 10,上限 20;非法值按默认 10 处理 |

**响应参数**

候选卡**数组**(不是分页对象),每张卡字段如下:

| 参数名称 | 类型 | 描述 |
|----------|------|------|
| user_id | Integer | 对方账号 ID,滑卡时作为 `target_user_id` |
| nickname | String | 昵称 |
| gender | String | 性别 |
| age | Integer | 年龄 |
| city | String | 城市 |
| bio | String | 简介 |
| tags | Object[] | 标签,结构见 [users.md §2.1](users.md) |
| photos | Object[] | 照片,**只含已过审**的,结构见 [users.md §2.1](users.md) |

**请求示例**

```bash
curl "http://<域名>/api/v1/discovery/candidates?limit=10" \
  -H "Authorization: Bearer <access>"
```

**响应示例**

```json
[
  {
    "user_id": 30,
    "nickname": "多多30",
    "gender": "female",
    "age": 25,
    "city": "南京",
    "bio": "咖啡续命,手冲入门中",
    "tags": [
      { "id": 7, "name": "游戏", "icon": "game" },
      { "id": 8, "name": "读书", "icon": "book" }
    ],
    "photos": [
      { "id": 41, "url": "http://<域名>/media/photos/2026/09/seed_30_0.jpg", "status": "approved", "order": 0 }
    ]
  }
]
```

候选池为空时返回空数组 `[]`。

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |

---

### 3.2 提交滑卡动作

> `POST` `/api/v1/discovery/swipe` · 需要鉴权 · 限流 300 次/小时(按用户)

**接口描述**

提交一次滑卡(喜欢 / 跳过)。**幂等**:同一目标重复提交,保留第一次的动作与结果,不会重复产生配对或消息。

互相喜欢时返回 `matched: true`,并触发配对:系统会向**双方**各推送一条配对系统消息(聊天页展示为灰条)。

轻封禁(`banned_light`)账号调用返回 `403`(账号已被限制,暂时无法滑卡)。

**请求参数**(Body,`application/json`)

| 参数名称 | 必填 | 类型 | 描述 |
|----------|------|------|------|
| target_user_id | 是 | Integer | 被滑的人的**账号 ID** |
| action | 是 | String | `like`(喜欢)/ `pass`(跳过) |

**响应参数**

| 参数名称 | 类型 | 描述 |
|----------|------|------|
| matched | Boolean | 是否已配对成功(双方都 like 过对方)。本接口幂等:重复提交同一目标返回值不变 |

**请求示例**

```bash
curl -X POST http://<域名>/api/v1/discovery/swipe \
  -H "Authorization: Bearer <access>" \
  -H "Content-Type: application/json" \
  -d '{"target_user_id": 30, "action": "like"}'
```

**响应示例**

滑卡成功、尚未配对:

```json
{ "matched": false }
```

滑卡成功、双方互相喜欢(已配对):

```json
{ "matched": true }
```

划自己:

```json
{
  "code": 400,
  "message": "不能划自己",
  "request_id": "3ea0c35cb51a44a4bff983837d576ada"
}
```

对方资料不完整:

```json
{
  "code": 400,
  "message": "对方资料不完整,无法操作",
  "request_id": "9696cb5b9bcc4c2199eec8dc3c1d296c"
}
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 400 | 400 | 不能划自己 | 检查 `target_user_id` |
| 400 | 400 | 对方资料不完整,无法操作 | 从候选池中移除该用户 |
| 400 | 400 | 参数不合法(`action` 不是 like/pass、缺 `target_user_id` 等) | 按 `message` 修正 |
| 403 | 403 | 账号已被限制,暂时无法滑卡(轻封禁) | 提示用户账号受限 |
| 404 | 404 | 目标用户不存在 | 从候选池中移除该用户 |
| 429 | 429 | 触发限流(300 次/小时) | 按 `Retry-After` 等待 |
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |

---

### 3.3 配对列表

> `GET` `/api/v1/matches` · 需要鉴权 · 无额外限流

**接口描述**

分页查询自己的全部配对,按配对时间倒序。与你双向拉黑的人不会出现在列表中。

**请求参数**(Query)

| 参数名称 | 必填 | 类型 | 描述 |
|----------|------|------|------|
| limit | 否 | Integer | 每页条数,默认 20,上限 100 |
| offset | 否 | Integer | 偏移量,默认 0 |

**响应参数**

分页对象(见 [conventions.md §分页约定](conventions.md#分页约定)),`results[]` 字段:

| 参数名称 | 类型 | 描述 |
|----------|------|------|
| user_id | Integer | 对方账号 ID |
| im_user_id | String | 对方 IM 账号,格式 `u{user_id}`;客户端聊天时使用 |
| nickname | String | 对方昵称 |
| avatar_url | String / null | 对方头像(取第一张已过审照片);无照片为 `null` |
| matched_at | String | 配对时间(UTC,ISO 8601) |

**请求示例**

```bash
curl "http://<域名>/api/v1/matches?limit=20&offset=0" \
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
      "im_user_id": "u8",
      "nickname": "Bob",
      "avatar_url": "http://<域名>/media/photos/2026/09/bob_avatar.png",
      "matched_at": "2026-09-19T04:38:32.767758Z"
    }
  ]
}
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |
