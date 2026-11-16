---
状态: 生效中
复核: 每次接口变更时
---

# 用户资料

本分册含 13 个接口:我的资料(查/改/注销)、标签池、照片(传/删)、资料语音(传/删/查转码状态)、择偶偏好(查/改)、他人公开资料、在线状态。

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
| visits_hidden | Boolean | 是否开启「隐身浏览」;开启后自己的访问不写进他人访客列表 |
| voice | Object | 资料语音自我介绍,见下表;没录过为 `null` |

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

`voice` 字段(没录过语音、或语音还在转码/转码失败时为 `null`;进度查 2.13):

| 参数名称 | 类型 | 描述 |
|----------|------|------|
| url | String | m4a 绝对地址,**限时签名**(带 `e`/`s`;过期或篡改后 403,TTL 与聊天媒体同源 `IM_MEDIA_SIGN_TTL`) |
| duration_ms | Integer | 服务端实测时长(毫秒),≤30000 |
| status | String | 转码状态,本字段里恒为 `ready`(`pending` / `failed` 时整个 `voice` 为 `null`) |

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
| visits_hidden | 否 | Boolean | 隐身浏览开关;不传表示不改 |

**响应参数**

同 [2.1 获取我的资料](#21-获取我的资料)(更新后的完整资料)。

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
| 41301 | 413 | 账号媒体存储已满(message 含已用/上限) | 提示用户删除部分照片,或等待聊天图片过期(默认 30 天) |
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

同 [2.6 获取择偶偏好](#26-获取择偶偏好)(更新后的完整偏好)。

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

**关注态**(批次 I):`is_followed` 是「我是否关注了对方」,`follower_count` / `following_count` 分别是对方的粉丝数与关注数。关注/取消关注见 [feed.md §5.13/§5.14](feed.md#513-关注)。

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
| shared_tags | Object[] | **共同标签**:对方标签与当前用户标签的交集(元素结构同 2.1 的 `tags[]`);无交集或未登录为空数组 |
| photos | Object[] | 已过审照片,同 2.1 |
| voice | Object | 资料语音自我介绍(元素结构同 2.1 的 `voice`);能看资料卡即可听,链接为限时签名,没录过为 `null` |
| is_followed | Boolean | 当前用户是否已关注对方 |
| follower_count | Integer | 对方的粉丝数(多少人关注了对方) |
| following_count | Integer | 对方的关注数(对方关注了多少人) |

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
  "shared_tags": [
    { "id": 1, "name": "运动", "icon": "sports" },
    { "id": 3, "name": "电影", "icon": "movie" }
  ],
  "photos": [
    { "id": 3, "url": "http://<域名>/media/photos/2026/09/bob_avatar.png", "status": "approved", "order": 0 }
  ],
  "is_followed": false,
  "follower_count": 3,
  "following_count": 1
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

---

### 2.10 注销账号

> `DELETE` `/api/v1/users/me` · 需要鉴权 · 无额外限流

**接口描述**

注销当前账号(不可恢复)。请求体必须带上当前账号的完整手机号做二次确认,不匹配则拒绝且**不删除任何数据**。校验通过后服务端立即硬删除账号及其全部关联数据(资料、照片与图片文件、滑卡记录、配对关系、广场动态与评论、拉黑与举报记录、封禁审计记录),并释放该手机号 —— 同一手机号可立即重新注册,得到的是一个**全新账号**。

服务端同时会清掉在线状态、异步删除 IM 账号。**重封禁(`banned_heavy`)账号无法自助注销**(返回 403),需联系客服;轻封禁(`banned_light`)可以注销。

**请求参数**

| 参数名称 | 必填 | 类型 | 描述 |
|----------|------|------|------|
| phone | 是 | String | 当前账号的完整手机号(请求体 JSON 字段,二次确认用) |

**响应参数**

无(HTTP 204,响应体为空)。

**请求示例**

```bash
curl -X DELETE http://<域名>/api/v1/users/me \
  -H "Authorization: Bearer <access>" \
  -H "Content-Type: application/json" \
  -d '{"phone": "13800138000"}'
```

**响应示例**

```
HTTP/1.1 204 No Content
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 400 | 400 | 请输入手机号 / 手机号与当前账号不一致 | 提示用户重新输入当前账号的手机号 |
| 403 | 403 | 账号已被封禁,如有疑问请联系客服 | 重封禁账号不能自助注销 |
| 401 | 401 | 未认证或令牌失效(账号已注销后再调用也会落到这里) | 重新登录或刷新令牌 |

---

### 2.11 上传 / 覆盖资料语音

> `POST` `/api/v1/users/me/voice` · 需要鉴权 · 限流 10 次/小时(按账号)

**接口描述**

给自己的资料录一段 **≤30 秒**的语音自我介绍。任何能看你资料的人都能播放(不做「仅配对后可听」);响应里的 `url` 是**限时签名**地址,过期需重新拉资料接口。

服务端行为说明:

- **统一转码**:与聊天语音同一条链路(`im.voice`),webm/ogg/m4a/aac 一律用 ffmpeg 转成 m4a/AAC 单声道 16kHz 32kbps,保证 iOS 也能播
- **时长以服务端为准**:用 `ffprobe` 读真实时长,**超过 30 秒直接 400**(不信任客户端声明,客户端也不需要传时长)
- **覆盖式**:一人只有一条,重复上传即替换内容,旧文件同时从磁盘删除
- **计入存储配额**:与照片/广场图/聊天媒体共用 `USER_STORAGE_QUOTA_MB` 额度,检查在**落盘之前**,超限不写任何文件
- **依赖 ffmpeg**:服务器缺 `ffmpeg`/`ffprobe` 时返回 503 + `50302`
- **全局单路转码**:与聊天语音上传共用一个转码槽,服务器同一时刻只跑一路 ffmpeg —— 资料语音一次要起 3 个子进程(`ffprobe` ×2 + `ffmpeg`),两路并发就会占满 2 个 worker,连登录都变慢。**抢不到槽不是错误**(M-3 起):走下面那条异步路径,返回 `202`
- **不影响「资料完善」判定**:语音不进 `missing_fields`,没录语音的老用户不会因此掉回 `incomplete`
- **抢到转码槽时同步完成**:转码在请求内做完(30 秒音频约 0.2–0.5 秒),直接返回 `201` 与 `url`;该路径没有第三方网络调用
- **抢不到槽时改走异步**(M-3):槽被别的上传占着时**不再回 503**,原始文件落进临时区、入队(`bulk` 队列),立即返回 `202 + status=pending + retry_after`;之后按 `retry_after` 轮询 2.13,`ready` 后再回资料页取 `voice`
- **异步路径的覆盖语义**:受理的同时旧语音就下线(旧文件删掉、`GET /users/me` 的 `voice` 变回 `null`),转码失败时该账号没有语音、重录即可(失败重试 UI 见客户端版本)
- **异步路径的校验顺序**:上传时只做浅校验(≤5MB、MIME 白名单);`ffprobe` 实测与「≤30 秒」上限、配额检查都在 worker 落盘之前做,失败体现为 `status=failed`,`code` 是业务码(配额超限 `41301`)
- **可选幂等键**:请求头带 `Idempotency-Key` 时,同一次上传的重试不会重复转码、不会多留一个文件 ——
  已完成的重放同一个 `201`(`url` 重新签名,`duration_ms` / `status` 与首次一致);异步路径记录了 `pending`,
  转码完成前重试拿回的是**同一个 `id`** 的 `202`,照旧按 `retry_after` 轮询 2.13 即可。上一次还没处理完时
  后到的请求返回 `409` + `40901`;失败(`400`/`413`/`503`)与转码失败(`status=failed`)都会释放 key。
  完整语义(取值、作用域、24 小时有效期)见 [conventions.md §幂等键](conventions.md#幂等键可选仅上传类接口)
- **地址限时签名**(2026-11-16 起,第五轮审计 L-7):`url` 是带 `e`/`s` 的签名绝对地址,签名规则与聊天图片/语音**同一套**(`im/media_sign.py`,与 imserver 逐字节一致),TTL 同源 `IM_MEDIA_SIGN_TTL`(默认 3600 秒,按整点对齐故同一小时内稳定)。过期、篡改或签名不符返回 **403**;`e` 失效后重新拉资料接口(或轮询 2.13)即可拿到新链接。**可见性没有变**:任何能看这份资料卡的人都能听("公开"指的是可见性,不是链接永久有效)。注意 nginx 侧 `/media/voices/` 的 `auth_request` 收口属于 `deploy/**`,尚未上线前直链仍可访问

**请求参数**(`multipart/form-data` + 可选请求头)

| 参数名称 | 类型 | 必填 | 描述 |
|----------|------|------|------|
| file | File | 是 | 音频文件;m4a/aac/webm/ogg,≤5MB |
| Idempotency-Key | String | 否 | **请求头**(不是表单字段)。可选幂等键:1–128 个字母、数字与 `.` `_` `:` `-`,重试时复用同一个值;规则见 [conventions.md §幂等键](conventions.md#幂等键可选仅上传类接口) |

**响应参数**

| 参数名称 | 类型 | 描述 |
|----------|------|------|
| url | String | m4a 绝对地址,**限时签名**(带 `e`/`s`;过期或篡改后 403,TTL 与聊天媒体同源 `IM_MEDIA_SIGN_TTL`) |
| duration_ms | Integer | 服务端实测时长(毫秒),≤30000 |
| status | String | 转码状态,本响应恒为 `ready` |

**响应参数(202:已受理,转码排队中)**

| 参数名称 | 类型 | 描述 |
|----------|------|------|
| id | Integer | 资料语音主键,用它轮询 2.13 |
| status | String | 恒为 `pending` |
| retry_after | Integer | 建议的轮询间隔(秒),默认 5 |

> `202` 的响应**不带 `url`**:文件还没转码落盘。

**请求示例**

```bash
curl -X POST http://<域名>/api/v1/users/me/voice \
  -H "Authorization: Bearer <access>" \
  -F "file=@/path/to/intro.m4a"
```

**响应示例**

```json
{
  "url": "https://<域名>/media/voices/2026/11/7-a1b2c3d4e5f6.m4a?e=1763424000&s=9f2c...",
  "duration_ms": 18000,
  "status": "ready"
}
```

**响应示例(202,槽被占用)**

```json
{
  "id": 7,
  "status": "pending",
  "retry_after": 5
}
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 400 | 400 | 格式不在白名单 / 超过 5MB / 音频无法解码 / 时长超过 30 秒(message 含「30 秒」)/ `Idempotency-Key` 不合规(长度或字符) | 提示用户重录或换文件;key 不合规时换一个新生成的 key |
| 41301 | 413 | 账号媒体存储已满(message 含已用/上限) | 提示用户删除部分照片,或等待聊天媒体 30 天后过期 |
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |
| 403 | 403 | 账号被重封禁,禁止使用(全域 403) | 提示用户账号受限 |
| 40901 | 409 | 同一个 `Idempotency-Key` 的上一次上传还在处理中 | 退避 1–2 秒后用**同一个 key** 重试(会拿到首次的 `201` 或同一个 `id` 的 `202`);**不要换 key** |
| 429 | 429 | 上传过于频繁(10 次/小时) | 稍后再试 |
| 50302 | 503 | 语音暂不可用:服务器缺少 ffmpeg/ffprobe | 联系运维安装 ffmpeg/ffprobe;客户端提示「语音暂不可用,请稍后重试」 |

> 转码槽被占用**不再**是错误:这种情况返回 `202`,按 `retry_after` 轮询 2.13 即可。
> 带 `Idempotency-Key` 时,`202` 期间的重试只会拿回**同一个 `id`**,不会多出第二条语音。

---

### 2.12 删除资料语音

> `DELETE` `/api/v1/users/me/voice` · 需要鉴权 · 限流 10 次/小时(按账号,与上传共用计数)

**接口描述**

删除自己的语音自我介绍,**幂等**:没有语音时同样返回 204。删除会同时删掉磁盘文件,之后 `GET /users/me` 与他人资料卡里的 `voice` 变回 `null`。

**请求参数**

无。

**响应参数**

无(HTTP 204,响应体为空)。

**请求示例**

```bash
curl -X DELETE http://<域名>/api/v1/users/me/voice \
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
| 403 | 403 | 账号被重封禁,禁止使用(全域 403) | 提示用户账号受限 |
| 429 | 429 | 操作过于频繁(10 次/小时) | 稍后再试 |

---

### 2.13 查询资料语音转码状态

> `GET` `/api/v1/users/me/voice` · 需要鉴权 · 限流 480 次/小时(按账号)

**接口描述**

2.11 返回 `202 + status=pending` 时,用本接口按 `retry_after` 轮询,直到 `status` 变成 `ready` 拿到 `url`,`failed` 则按 `code` / `message` 提示用户重录。

三态语义与聊天语音完全相同(见 im.md §6.5):`pending` 排队/转码中、`ready` 可播放、`failed` 转码失败。资料语音一人一条,所以本接口只查自己的,**没有路径参数**。

**请求参数**

无。

**响应参数**

| 参数名称 | 类型 | 描述 |
|----------|------|------|
| id | Integer | 资料语音主键 |
| status | String | `pending` / `ready` / `failed` |
| url | String | `ready` 时的 m4a 绝对地址,**限时签名**(带 `e`/`s`,与 2.11 的 `url` 同口径);否则 `null` |
| duration_ms | Integer | `ready` 时的实测时长(毫秒,≤30000);否则 `null` |
| size | Integer | `ready` 时的文件字节数;否则 `null` |
| code | String | `failed` 时的业务码(如 `41301`);否则 `null` |
| message | String | `failed` 时可直接展示的中文提示;否则 `null` |

**请求示例**

```bash
curl http://<域名>/api/v1/users/me/voice \
  -H "Authorization: Bearer <access>"
```

**响应示例**

```json
{
  "id": 7,
  "status": "ready",
  "url": "https://<域名>/media/voices/2026/11/7-a1b2c3d4e5f6.m4a?e=1763424000&s=9f2c...",
  "duration_ms": 18000,
  "size": 72000,
  "code": null,
  "message": null
}
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 404 | 404 | 还没录过语音(没有可查询的行) | 先走 2.11 上传 |
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |
| 403 | 403 | 账号被重封禁,禁止使用(全域 403) | 提示用户账号受限 |
| 429 | 429 | 轮询过于频繁(480 次/小时) | 按 `retry_after` 退避后再查 |
