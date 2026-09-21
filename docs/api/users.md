# 用户资料

本分册含 9 个接口:我的资料(查/改)、标签池、照片(传/删)、择偶偏好(查/改)、他人公开资料、在线状态。

两个易混的 ID:`user_id` 是**账号 ID**(跨接口引用用户一律用它);`id` 只在 `GET /users/me` 里出现,是**资料表主键**,不要用它去调 `/users/{user_id}`。

---

### 2.1 获取我的资料

> `GET` `/api/v1/users/me` · 需要鉴权 · 无额外限流

**接口描述**

获取当前登录账号的完整资料,包含手机号、生日、择偶偏好等隐私字段(他人公开资料见 2.8)。同时返回**资料完善状态**:昵称、性别、生日、城市、简介均非空且至少有 1 张已过审照片时 `status` 为 `complete`,否则为 `incomplete` 并在 `missing_fields` 列出缺项。

**请求参数**

无。

**响应参数**

| 参数名称 | 类型 | 描述 |
|----------|------|------|
| id | Integer | 资料表主键(**不是**账号 ID) |
| user_id | Integer | 账号 ID,跨接口引用用户时使用 |
| phone | String | 注册手机号 |
| nickname | String | 昵称,可能为空字符串 |
| gender | String | `male` / `female`,未填为空字符串 |
| birthday | String | 生日 `YYYY-MM-DD`,未填为 `null` |
| age | Integer | 由生日实时计算,未填生日为 `null` |
| city | String | 城市 |
| bio | String | 个人简介 |
| status | String | 资料状态:`incomplete` 未完善 / `complete` 已完善 / `banned_light` 轻封禁 / `banned_heavy` 重封禁 |
| ban_reason | String | 封禁原因(未封禁为空字符串) |
| missing_fields | String[] | 未完善时列出缺项,取值 `nickname` / `gender` / `birthday` / `city` / `bio` / `photos`;已完善为空数组 |
| tags | Object[] | 已选标签,见下表 |
| photos | Object[] | 已上传照片(含未过审) |
| preference | Object | 择偶偏好,同 2.6 |

`tags[]` 字段:

| 参数名称 | 类型 | 描述 |
|----------|------|------|
| id | Integer | 标签 ID |
| name | String | 标签名 |
| icon | String | 图标标识(客户端映射图标用) |

`photos[]` 字段:

| 参数名称 | 类型 | 描述 |
|----------|------|------|
| id | Integer | 照片 ID,删除时使用 |
| url | String | 图片地址(完整 URL) |
| status | String | 审核状态:`pending` 待审核 / `approved` 已通过 / `rejected` 已驳回 |
| order | Integer | 展示顺序,从 0 开始 |

**请求示例**

```bash
curl http://<域名>/api/v1/users/me \
  -H "Authorization: Bearer <access>"
```

**响应示例**

```json
{
  "id": 18,
  "user_id": 21,
  "phone": "139****0010",
  "nickname": "可欣21",
  "gender": "female",
  "birthday": "1999-12-18",
  "age": 26,
  "city": "重庆",
  "bio": "旅行过 12 个城市,下一站西北",
  "status": "complete",
  "ban_reason": "",
  "missing_fields": [],
  "tags": [
    { "id": 1, "name": "运动", "icon": "sports" },
    { "id": 3, "name": "电影", "icon": "movie" }
  ],
  "photos": [
    { "id": 23, "url": "http://<域名>/media/photos/2026/09/seed_21_0.jpg", "status": "approved", "order": 0 },
    { "id": 24, "url": "http://<域名>/media/photos/2026/09/seed_21_1.jpg", "status": "approved", "order": 1 }
  ],
  "preference": { "target_gender": "male", "age_min": 18, "age_max": 99, "city": "" }
}
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |

---

### 2.2 修改我的资料

> `PATCH` `/api/v1/users/me` · 需要鉴权 · 无额外限流

**接口描述**

局部更新资料:只传要修改的字段即可,未传的字段保持不变。`tag_ids` 一旦传入即为**全量替换**(想保留原标签就要一起传)。昵称修改后会异步同步到 IM(聊天对方看到的昵称随之更新)。更新后服务端会自动重算完善状态。

**请求参数**(Body,`application/json`,所有字段可选)

| 参数名称 | 必填 | 类型 | 描述 |
|----------|------|------|------|
| nickname | 否 | String | 昵称,最长 20 字;含违规词返回 400 |
| gender | 否 | String | `male` / `female` |
| birthday | 否 | String | 生日 `YYYY-MM-DD`;**未满 18 周岁返回 400** |
| city | 否 | String | 城市,最长 50 字 |
| bio | 否 | String | 简介,最长 200 字;含违规词返回 400 |
| tag_ids | 否 | Integer[] | 标签 ID 数组(全量替换);ID 不存在返回 400;可传空数组清空 |

**响应参数**

与 2.1 完全一致(更新后的完整资料)。

**请求示例**

```bash
curl -X PATCH http://<域名>/api/v1/users/me \
  -H "Authorization: Bearer <access>" \
  -H "Content-Type: application/json" \
  -d '{"city": "上海"}'
```

**响应示例**

```json
{
  "id": 18,
  "user_id": 21,
  "phone": "139****0010",
  "nickname": "可欣21",
  "gender": "female",
  "birthday": "1999-12-18",
  "age": 26,
  "city": "上海",
  "bio": "旅行过 12 个城市,下一站西北",
  "status": "complete",
  "ban_reason": "",
  "missing_fields": [],
  "tags": [],
  "photos": [],
  "preference": { "target_gender": "male", "age_min": 18, "age_max": 99, "city": "" }
}
```

(响应为完整资料对象,上面为节选示意;实际 `tags` / `photos` 为真实内容。)

未满 18 岁:

```json
{
  "code": 400,
  "message": "未满 18 周岁,无法使用本应用",
  "request_id": "b818b73bbfa24f1dbe87855c1ffdacca"
}
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 400 | 400 | 参数不合法(生日格式、未满 18 岁、昵称/简介含违规词、标签 ID 无效) | 按 `message` 提示修正后重试 |
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |

---

### 2.3 获取标签池

> `GET` `/api/v1/users/tags` · 需要鉴权 · 无额外限流

**接口描述**

获取可选的兴趣标签池(共 12 个),用于资料编辑页让用户挑选;选中的标签通过 2.2 的 `tag_ids` 提交。

**请求参数**

无。

**响应参数**

标签对象数组:

| 参数名称 | 类型 | 描述 |
|----------|------|------|
| id | Integer | 标签 ID |
| name | String | 标签名 |
| icon | String | 图标标识 |

**请求示例**

```bash
curl http://<域名>/api/v1/users/tags \
  -H "Authorization: Bearer <access>"
```

**响应示例**

```json
[
  { "id": 1, "name": "运动", "icon": "sports" },
  { "id": 2, "name": "音乐", "icon": "music" },
  { "id": 3, "name": "电影", "icon": "movie" },
  { "id": 4, "name": "旅行", "icon": "travel" },
  { "id": 5, "name": "美食", "icon": "food" },
  { "id": 6, "name": "宠物", "icon": "pet" },
  { "id": 7, "name": "游戏", "icon": "game" },
  { "id": 8, "name": "读书", "icon": "book" },
  { "id": 9, "name": "摄影", "icon": "camera" },
  { "id": 10, "name": "健身", "icon": "fitness" },
  { "id": 11, "name": "动漫", "icon": "anime" },
  { "id": 12, "name": "咖啡", "icon": "coffee" }
]
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |

---

### 2.4 上传照片

> `POST` `/api/v1/users/me/photos` · 需要鉴权 · 无额外限流

**接口描述**

上传一张资料照片。单张不超过 **5MB**,每人最多 **6 张**。测试环境上传即过审(`status` 直接为 `approved`,见 [conventions.md §测试环境专用行为](conventions.md#测试环境专用行为));正式环境需等待审核。上传成功后服务端会重算资料完善状态。

**请求参数**(`multipart/form-data`)

| 参数名称 | 必填 | 类型 | 描述 |
|----------|------|------|------|
| file | 是 | File | 图片文件(表单字段名固定为 `file`) |

**响应参数**(HTTP 201)

| 参数名称 | 类型 | 描述 |
|----------|------|------|
| id | Integer | 照片 ID |
| url | String | 图片地址(完整 URL) |
| status | String | 审核状态 |
| order | Integer | 展示顺序 |

**请求示例**

```bash
curl -X POST http://<域名>/api/v1/users/me/photos \
  -H "Authorization: Bearer <access>" \
  -F "file=@photo.png"
```

**响应示例**

```json
{
  "id": 48,
  "url": "http://<域名>/media/photos/2026/09/example.png",
  "status": "approved",
  "order": 2
}
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 400 | 400 | 图片不能超过 5MB | 压缩后重新上传 |
| 400 | 400 | 请上传有效图片。您上传的该文件不是图片或者图片已经损坏。 | 检查文件格式(jpg/png 等) |
| 400 | 400 | 最多上传 6 张照片 | 先删除旧照片(见 2.5)再上传 |
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |

> 注:「最多上传 6 张」这一条为接口内直接校验,响应不含 `request_id`(见 [conventions.md §统一响应结构](conventions.md#统一响应结构))。

---

### 2.5 删除照片

> `DELETE` `/api/v1/users/me/photos/{photo_id}` · 需要鉴权 · 无额外限流

**接口描述**

删除自己的一张照片(连同图片文件一起删除)。删除后服务端会重算资料完善状态。

**请求参数**

| 参数名称 | 必填 | 类型 | 描述 |
|----------|------|------|------|
| photo_id | 是 | Integer | 照片 ID,取自 2.1 的 `photos[].id`(路径参数) |

**响应参数**

无(HTTP 204,响应体为空)。

**请求示例**

```bash
curl -X DELETE http://<域名>/api/v1/users/me/photos/48 \
  -H "Authorization: Bearer <access>"
```

**响应示例**

```
HTTP/1.1 204 No Content
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 404 | 404 | 照片不存在或不属于当前账号 | 刷新资料后重试 |
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |

---

### 2.6 获取择偶偏好

> `GET` `/api/v1/users/me/preference` · 需要鉴权 · 无额外限流

**接口描述**

获取「想找的人」的筛选条件,用于发现页候选卡的过滤(见 [discovery.md](discovery.md))。

**请求参数**

无。

**响应参数**

| 参数名称 | 类型 | 描述 |
|----------|------|------|
| target_gender | String | 想找的性别 `male` / `female`;**`null` 表示不限** |
| age_min | Integer | 最小年龄,默认 18 |
| age_max | Integer | 最大年龄,默认 99 |
| city | String | 想找的城市;空字符串表示不限 |

**请求示例**

```bash
curl http://<域名>/api/v1/users/me/preference \
  -H "Authorization: Bearer <access>"
```

**响应示例**

```json
{ "target_gender": "male", "age_min": 18, "age_max": 99, "city": "" }
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |

---

### 2.7 修改择偶偏好

> `PATCH` `/api/v1/users/me/preference` · 需要鉴权 · 无额外限流

**接口描述**

局部更新择偶偏好,未传的字段保持不变。

**请求参数**(Body,`application/json`,所有字段可选)

| 参数名称 | 必填 | 类型 | 描述 |
|----------|------|------|------|
| target_gender | 否 | String | `male` / `female`;传 `null` 表示不限 |
| age_min | 否 | Integer | 最小年龄,**不能小于 18** |
| age_max | 否 | Integer | 最大年龄 |
| city | 否 | String | 城市;传空字符串表示不限 |

**响应参数**

与 2.6 一致(更新后的完整偏好)。

**请求示例**

```bash
curl -X PATCH http://<域名>/api/v1/users/me/preference \
  -H "Authorization: Bearer <access>" \
  -H "Content-Type: application/json" \
  -d '{"age_min": 22, "age_max": 35}'
```

**响应示例**

```json
{ "target_gender": "male", "age_min": 22, "age_max": 35, "city": "" }
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 400 | 400 | 最小年龄不能小于 18 | 调整后重试 |
| 400 | 400 | 最小年龄不能大于最大年龄 | 调整后重试 |
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |

---

### 2.8 获取他人公开资料

> `GET` `/api/v1/users/{user_id}` · 需要鉴权 · 无额外限流

**接口描述**

获取某个用户的公开资料卡(用于资料页/发现卡片)。只返回公开字段:不含手机号、生日、择偶偏好与完善度。照片只返回**已过审**的。

**404 语义**:以下三种情况一律返回 `404`「用户不存在」,不区分、不泄露关系——对方不存在、对方与你**双向拉黑**、对方被重封禁。

**请求参数**

| 参数名称 | 必填 | 类型 | 描述 |
|----------|------|------|------|
| user_id | 是 | Integer | 对方账号 ID(路径参数) |

**响应参数**

| 参数名称 | 类型 | 描述 |
|----------|------|------|
| user_id | Integer | 对方账号 ID |
| nickname | String | 昵称 |
| gender | String | 性别 |
| age | Integer | 年龄(由生日计算) |
| city | String | 城市 |
| bio | String | 简介 |
| tags | Object[] | 标签,同 2.1 |
| photos | Object[] | 已过审照片,同 2.1 |

**请求示例**

```bash
curl http://<域名>/api/v1/users/8 \
  -H "Authorization: Bearer <access>"
```

**响应示例**

```json
{
  "user_id": 8,
  "nickname": "Bob",
  "gender": "male",
  "age": 28,
  "city": "成都",
  "bio": "hello",
  "tags": [
    { "id": 1, "name": "运动", "icon": "sports" },
    { "id": 2, "name": "音乐", "icon": "music" },
    { "id": 3, "name": "电影", "icon": "movie" }
  ],
  "photos": [
    { "id": 3, "url": "http://<域名>/media/photos/2026/09/bob_avatar.png", "status": "approved", "order": 0 }
  ]
}
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 404 | 404 | 用户不存在(含双向拉黑、重封禁) | 从列表移除该用户,不要重试 |
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |

---

### 2.9 批量查询在线状态

> `GET` `/api/v1/presence` · 需要鉴权 · 限流 600 次/小时(按用户)

**接口描述**

批量查询用户是否在线。**「在线」= 最近 120 秒内有过认证请求**(客户端约 45 秒一次心跳,App 打开着即在线)。

**结果省略规则**(不报错、不泄露关系):以下 id 直接从 `results` 里省略——自己、不存在的用户、与你双向拉黑的人、被重封禁的人。未活跃超过 7 天的用户仍在结果里,但 `last_active_at` 为 `null`。

**请求参数**(Query)

| 参数名称 | 必填 | 类型 | 描述 |
|----------|------|------|------|
| user_ids | 是 | String | 逗号分隔的账号 ID 列表;自动去重并保持顺序;**一次最多 100 个** |

**响应参数**

| 参数名称 | 类型 | 描述 |
|----------|------|------|
| results | Object[] | 结果数组,顺序与请求一致(省略的除外) |
| results[].user_id | Integer | 账号 ID |
| results[].online | Boolean | 是否在线(120 秒内有认证请求) |
| results[].last_active_at | String / null | 最后活跃时间(ISO 8601);无记录为 `null` |

**请求示例**

```bash
curl "http://<域名>/api/v1/presence?user_ids=8,21,999999" \
  -H "Authorization: Bearer <access>"
```

**响应示例**

```json
{
  "results": [
    { "user_id": 8, "online": false, "last_active_at": "2026-09-20T20:35:12+08:00" }
  ]
}
```

(请求了 8、21、999999 三个 id;21 是请求者自己被省略,999999 不存在被省略。)

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 400 | 400 | user_ids 不能为空 | 至少传一个用户 ID |
| 400 | 400 | user_ids 必须是数字 | 检查参数格式(逗号分隔的整数) |
| 400 | 400 | 一次最多查询 100 个用户 | 分批查询 |
| 429 | 429 | 触发限流(600 次/小时) | 降低轮询频率或按 `Retry-After` 等待 |
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |

> 注:本接口的 400 参数校验为接口内直接响应,不含 `request_id`。
