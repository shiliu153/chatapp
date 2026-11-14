---
状态: 生效中
复核: 每次接口变更时
---

# 发现与配对

本分册含 11 个接口:拉取候选卡、今日精选、提交滑卡动作、撤销上一次滑卡、查询每日喜欢额度、
查询配对列表、喜欢我的人列表、喜欢我的人数、解除配对、谁看过我、访客人数。

配对逻辑:双方都 `like` 即配对成功(滑卡时响应 `matched: true`,同时双方会各收到一条系统消息)。

批次 O 的两个接口(§3.9 撤销、§3.10 额度)配合 §3.2 使用:撤销窗口 30 秒,
额度默认关闭(`like_limit = 0` 时行为与加额度前完全一致)。

批次 S 的两项能力(§3.1 的筛选参数、§3.11 今日精选)都是**只读**的:筛选是查询参数,
**不写回**「想找的人」偏好(设置页仍是唯一持久化入口);今日精选复用同一套候选池与排除规则。

---

### 3.1 拉取候选卡

> `GET` `/api/v1/discovery/candidates` · 需要鉴权 · 无额外限流

**接口描述**

拉取一批供滑卡的候选用户。候选池的筛选规则:

- **排除**:自己、自己划过的人(不论 like/pass)、已配对的人、与你双向拉黑的人
- **只推资料完善的人**:`status = complete` 且**至少有 1 张已过审照片**
- **按你的择偶偏好过滤**(见 [users.md §2.6](users.md)):目标性别(未设置=不限)、城市(未设置=不限)、年龄区间
- **临时筛选**(批次 S):`age_min` / `age_max` / `city` / `tag_ids` 四个可选查询参数,
  **只在本次请求内**覆盖对应的偏好字段,**不写回偏好**;四个都不传时行为与加筛选前完全一致
- 返回顺序为**随机**(保证每次刷新看到的顺序不同)。服务端按预计算的随机列取一个
  池子(默认 200 人)再抽样,不是每次都对全表 `ORDER BY RAND()`,因此延迟不随用户量线性上升

**请求参数**(Query)

| 参数名称 | 必填 | 类型 | 描述 |
|----------|------|------|------|
| limit | 否 | Integer | 拉取条数,默认 10,上限 20;非法值按默认 10 处理 |
| age_min | 否 | Integer | 年龄下限(含),`18`–`99`;缺省沿用偏好 |
| age_max | 否 | Integer | 年龄上限(含),`18`–`99`;缺省沿用偏好 |
| city | 否 | String | 只看这个城市(≤ 50 字符);缺省沿用偏好,空串视为不筛 |
| tag_ids | 否 | String | 标签 ID,逗号分隔,**命中其一即可**;缺省不筛标签 |

筛选参数的约定:

- 只传一部分时,没传的字段继续沿用偏好(例如只传 `city` 不会改掉偏好里的年龄区间);
- `age_min > age_max`、年龄不是整数、标签不是正整数、城市过长 → **`400`**(不新增业务码);
- `tag_ids` 是**并集**:`tag_ids=1,2` 表示「至少有标签 1 或标签 2 之一」;两个都没有的人不出现;
- 同一个人的多个标签命中**只出现一次**(服务端用子查询而不是 JOIN 去重)。

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
| 400 | 400 | 筛选参数非法(`age_min`/`age_max` 非整数或超出 18–99、`age_min > age_max`、`tag_ids` 非正整数、`city` 超过 50 字符) | 按错误提示修正参数 |
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |

---

### 3.2 提交滑卡动作

> `POST` `/api/v1/discovery/swipe` · 需要鉴权 · 限流 300 次/小时(按用户)

**接口描述**

提交一次滑卡(喜欢 / 跳过)。**幂等**:同一目标重复提交,保留第一次的动作与结果,不会重复产生配对或消息。

互相喜欢时返回 `matched: true`,并触发配对:系统会向**双方**各推送一条配对系统消息(聊天页展示为灰条)。

配对成功时响应同时带 `shared_tags`(共同标签:对方标签与当前用户标签的交集),客户端**直接用它**渲染
「你们都喜欢 X、Y」的破冰文案,**不要**再去拉 `GET /users/{id}` —— 那会把这次配对记成一次访客访问。

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
| shared_tags | Object[] | 共同标签(元素结构 `{id,name,icon}`);未配对或无交集时为空数组 |

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
{ "matched": false, "shared_tags": [] }
```

滑卡成功、双方互相喜欢(已配对):

```json
{
  "matched": true,
  "shared_tags": [
    { "id": 1, "name": "运动", "icon": "sports" },
    { "id": 3, "name": "电影", "icon": "movie" }
  ]
}
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
| 429 | 42904 | 今天的喜欢次数已用完(`action=like` 超每日额度;默认额度为 0 时不出现) | 按 `Retry-After`(到次日 0 点)等待,或提示「明天再来」;`action=pass` 不受限 |
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |

---

### 3.3 配对列表

> `GET` `/api/v1/matches` · 需要鉴权 · 无额外限流

**接口描述**

分页查询自己的全部配对,按配对时间倒序。与你双向拉黑的人不会出现在列表中。

每项带 `shared_tags`(共同标签:对方标签与当前用户标签的交集),供「配对那一刻」的破冰文案使用;
整页一次批量求交,不随条数增加查询。没有交集时为空数组。

**请求参数**(Query)

| 参数名称 | 必填 | 类型 | 描述 |
|----------|------|------|------|
| limit | 否 | Integer | 每页条数,默认 20,上限 100 |
| before | 否 | String | 游标。首页不传;之后原样回传上一页的 `next_cursor`(见 [conventions.md §分页约定](conventions.md#分页约定)) |

**响应参数**

游标分页对象(`count` / `next_cursor` / `has_more` / `results`);带 `offset` 的老客户端
仍得到 `{count, next, previous, results}`。`results[]` 字段:

| 参数名称 | 类型 | 描述 |
|----------|------|------|
| user_id | Integer | 对方账号 ID |
| im_user_id | String | 对方 IM 账号,格式 `u{user_id}`;客户端聊天时使用 |
| nickname | String | 对方昵称 |
| avatar_url | String / null | 对方头像(取第一张已过审照片);无照片为 `null` |
| matched_at | String | 配对时间(UTC,ISO 8601) |
| shared_tags | Object[] | 共同标签(元素结构 `{id,name,icon}`,同 [users.md §2.1](users.md) 的 `tags[]`);无交集为空数组 |

**请求示例**

```bash
curl "http://<域名>/api/v1/matches?limit=20" \
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
      "user_id": 8,
      "im_user_id": "u8",
      "nickname": "Bob",
      "avatar_url": "http://<域名>/media/photos/2026/09/bob_avatar.png",
      "matched_at": "2026-09-19T04:38:32.767758Z",
      "shared_tags": [
        { "id": 1, "name": "运动", "icon": "sports" },
        { "id": 3, "name": "电影", "icon": "movie" }
      ]
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

### 3.4 喜欢我的人列表

> `GET` `/api/v1/discovery/likes` · 需要鉴权 · 无额外限流

**接口描述**

分页查询「喜欢我的人」。口径与候选池完全一致:

- 只含 `action = like` 的记录(对方喜欢我);
- 排除**我已经划过的人**(不论 like/pass)、双向拉黑的人;
- 只含资料完善(`status = complete`)且**至少有 1 张已过审照片**的人;
- 按对方喜欢我的时间倒序。

互喜后我已划过对方,因此该用户会立即从本列表消失。轻封禁可读;重封禁返回 `403`。

**请求参数**(Query)

| 参数名称 | 必填 | 类型 | 描述 |
|----------|------|------|------|
| limit | 否 | Integer | 每页条数,默认 20,上限 100 |
| before | 否 | String | 游标。首页不传;之后原样回传上一页的 `next_cursor` |

**响应参数**

游标分页对象(`count` / `next_cursor` / `has_more` / `results`);带 `offset` 的老客户端
仍得到 `{count, next, previous, results}`。注意 `count` 是「喜欢我的人」总数,与分页无关,
客户端拿它算入口角标。`results[]` 字段:

| 参数名称 | 类型 | 描述 |
|----------|------|------|
| user_id | Integer | 对方账号 ID |
| im_user_id | String | 对方 IM 账号,格式 `u{user_id}` |
| nickname | String | 昵称 |
| gender | String | `male` / `female` |
| age | Integer / null | 周岁;未填生日时为 `null` |
| city | String | 城市 |
| bio | String | 简介 |
| tags | Object[] | 标签,结构见 [users.md §2.1](users.md) |
| photos | Object[] | **只含已过审**的照片 |
| liked_at | String | 对方喜欢我的时间(UTC,ISO 8601) |

**请求示例**

```bash
curl "http://<域名>/api/v1/discovery/likes?limit=20" \
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
      "user_id": 30,
      "im_user_id": "u30",
      "nickname": "多多30",
      "gender": "female",
      "age": 25,
      "city": "南京",
      "bio": "咖啡续命,手冲入门中",
      "tags": [
        { "id": 7, "name": "游戏", "icon": "game" }
      ],
      "photos": [
        { "id": 41, "url": "http://<域名>/media/photos/2026/09/seed_30_0.jpg", "status": "approved", "order": 0 }
      ],
      "liked_at": "2026-10-20T02:30:00.000000Z"
    }
  ]
}
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 400 | 400 | 游标无效 | 清空列表,从第一页重拉 |
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |
| 403 | 403 | 账号已被封禁(重封禁) | 提示用户账号受限 |

---

### 3.5 喜欢我的人数

> `GET` `/api/v1/discovery/likes/count` · 需要鉴权 · 无额外限流

**接口描述**

返回「喜欢我的人」总数,口径与 §3.4 完全一致,仅用于客户端入口角标。

**请求参数**

无。

**响应参数**

| 参数名称 | 类型 | 描述 |
|----------|------|------|
| count | Integer | 喜欢我的人数(已套用 §3.4 的全部排除规则) |

**请求示例**

```bash
curl "http://<域名>/api/v1/discovery/likes/count" \
  -H "Authorization: Bearer <access>"
```

**响应示例**

```json
{ "count": 12 }
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |
| 403 | 403 | 账号已被封禁(重封禁) | 提示用户账号受限 |

---

### 3.6 解除配对

> `DELETE` `/api/v1/matches/{user_id}` · 需要鉴权 · 无额外限流

**接口描述**

解除与指定用户的配对。**不可恢复**:

- 双方配对列表中不再出现彼此;
- 双方 IM 侧互相拉黑,**都收不到、也发不出消息**;
- 再滑到对方也不会重新配对(已划过的人不会回到候选池)。

**幂等**:没有配对、已解除、解除自己都返回 `204`,客户端重试不会报错。

**路径参数**

| 参数名称 | 必填 | 类型 | 描述 |
|----------|------|------|------|
| user_id | 是 | Integer | 对方的账号 ID(与 `GET /matches` 条目里的 `user_id` 一致) |

**响应参数**

成功返回 `204 No Content`,无响应体。

**请求示例**

```bash
curl -X DELETE "http://<域名>/api/v1/matches/8" \
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
| 403 | 403 | 账号处于重封禁状态 | 联系客服申诉 |
---

### 3.7 谁看过我

> `GET` `/api/v1/discovery/visits` · 需要鉴权 · 限流 120 次/小时(按用户)

**接口描述**

分页查询「谁看过我的资料页」。口径与「喜欢我的人」一致:

- 打开我的资料页(`GET /users/{id}`)即记一次访问,同一人 30 分钟内重复访问只刷新最近时间;
- **只为「资料完善且至少有 1 张已过审照片」的访问者落库**——与列表展示口径一致,资料未完善的浏览不产生记录;
- 排除**我已经划过的人**(不论 like/pass)、双向拉黑的人;
- 只含资料完善(`status = complete`)且至少有 1 张已过审照片的人;
- 按最近访问时间倒序。已配对的人因「我已划过」自然不在列表内。

开启「隐身浏览」后,你的访问不会写进任何人的列表(只影响之后的访问,已产生的记录仍会展示)。

**请求参数**(Query)

| 参数名称 | 必填 | 类型 | 描述 |
|----------|------|------|------|
| limit | 否 | Integer | 每页条数,默认 20,上限 100 |
| before | 否 | String | 游标。首页不传;之后原样回传上一页的 `next_cursor` |

**响应参数**

游标分页对象(`count` / `next_cursor` / `has_more` / `results`);带 `offset` 的老客户端
仍得到 `{count, next, previous, results}`。`results[]` 字段:

| 参数名称 | 类型 | 描述 |
|----------|------|------|
| user_id | Integer | 访客账号 ID |
| im_user_id | String | 访客 IM 账号,格式 `u{user_id}` |
| nickname | String | 昵称 |
| gender | String | `male` / `female` |
| age | Integer / null | 周岁;未填生日时为 `null` |
| city | String | 城市 |
| bio | String | 简介 |
| tags | Object[] | 标签,结构见 [users.md §2.1](users.md) |
| photos | Object[] | **只含已过审**的照片 |
| visited_at | String | 最近一次访问时间(UTC,ISO 8601,精度 30 分钟) |

**请求示例**

```bash
curl "http://<域名>/api/v1/discovery/visits?limit=20" \
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
      "user_id": 30,
      "im_user_id": "u30",
      "nickname": "多多30",
      "gender": "female",
      "age": 25,
      "city": "南京",
      "bio": "咖啡续命,手冲入门中",
      "tags": [{ "id": 7, "name": "游戏", "icon": "game" }],
      "photos": [
        { "id": 41, "url": "http://<域名>/media/photos/2026/09/seed_30_0.jpg", "status": "approved", "order": 0 }
      ],
      "visited_at": "2026-11-01T04:30:00.000000Z"
    }
  ]
}
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 400 | 400 | 游标无效 | 清空列表,从第一页重拉 |
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |
| 403 | 403 | 账号已被封禁(重封禁) | 提示用户账号受限 |
| 429 | 429 | 触发限流(120 次/小时) | 按 `Retry-After` 等待 |

---

### 3.8 访客人数

> `GET` `/api/v1/discovery/visits/count` · 需要鉴权 · 限流 240 次/小时(按用户)

**接口描述**

返回「谁看过我」的去重人数,口径与 §3.7 完全一致,仅用于客户端入口角标。

**请求参数**

无。

**响应参数**

| 参数名称 | 类型 | 描述 |
|----------|------|------|
| count | Integer | 访客人数(已套用 §3.7 的全部排除规则) |

**请求示例**

```bash
curl "http://<域名>/api/v1/discovery/visits/count" \
  -H "Authorization: Bearer <access>"
```

**响应示例**

```json
{ "count": 12 }
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |
| 403 | 403 | 账号已被封禁(重封禁) | 提示用户账号受限 |
| 429 | 429 | 触发限流(240 次/小时) | 按 `Retry-After` 等待 |
---

### 3.9 撤销上一次滑卡

> `POST` `/api/v1/discovery/swipe/undo` · 需要鉴权 · 限流 120 次/小时(按用户)

**接口描述**

误划之后在 **30 秒**内撤销最近一次滑卡。可以撤销的范围只有一条:

- **最近一次**:更早的滑卡不会被撤销,即使它仍在 30 秒内;
- **30 秒内**:以前端拿到滑卡响应的时间为起点,超过 30 秒按钮应当置灰;
- **未产生配对**:那条滑卡如果已经配对成功(双方互喜),一律拒绝 —— 撤销配对要连带
  回滚配对记录、解除 IM 双向拉黑、回收两条灰条,风险远大于「误划」的收益。
  **已经解除的配对同样拒绝**:只要有配对记录存在(哪怕双方后来解除了配对),就按「已配对」
  处理 —— `Match` 行的存在意味着这段关系真实建立过(灰条发出、IM 双向拉黑都发生过),
  「解除配对」本身是不可恢复的,不允许再用「撤销滑卡」把它抹掉。

撤销成功后:

- 那条滑卡记录被**物理删除**;
- 该用户重新出现在 `GET /api/v1/discovery/candidates` 里(候选池缓存随之失效);
- 如果原来划的是 `like`,当天的喜欢额度会退回一次(见 §3.10)。

轻封禁(`banned_light`)账号调用返回 `403`,与 §3.2 同口径。

**请求参数**

无(不需要请求体)。

**响应参数**

| 参数名称 | 类型 | 描述 |
|----------|------|------|
| undone | Boolean | 是否撤销成功;失败走错误信封(`400` + `40003`) |
| target_user_id | Integer | 被撤销的那次滑卡的目标账号 ID(客户端据此把他放回卡堆) |

**请求示例**

```bash
curl -X POST http://<域名>/api/v1/discovery/swipe/undo \
  -H "Authorization: Bearer <access>"
```

**响应示例**

撤销成功:

```json
{ "undone": true, "target_user_id": 30 }
```

没有可撤销的滑卡(本来就滑过、超过 30 秒、或者已经配对成功):

```json
{
  "code": 40003,
  "message": "没有可撤销的滑卡",
  "request_id": "9b1fa8ea7d9d4f2ba7d5f4b0d1e2c3a4"
}
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 400 | 40003 | 没有可撤销的滑卡(`message` 会说明原因:本来就没有记录 / 超过 30 秒 / 已配对,**含已解除的配对**) | 把撤销按钮置灰,不要重试;按 `message` 提示用户。**已配对(含已解除)不是错误状态** —— 客户端的撤销按钮在配对成功后就不该再出现 |
| 403 | 403 | 账号已被限制,暂时无法滑卡(轻封禁) | 提示用户账号受限 |
| 429 | 429 | 触发限流(120 次/小时) | 按 `Retry-After` 等待 |
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |

---

### 3.10 每日喜欢额度

> `GET` `/api/v1/discovery/quota` · 需要鉴权 · 无额外限流

**接口描述**

查询「今天还能喜欢多少人」。额度按 **自然日(`Asia/Shanghai`)** 计算,次日 0 点自动重置。

- 只有 `action=like` 消耗额度;`action=pass`(跳过)不受限;
- 同一目标重复提交(幂等重放)不重复计数;
- 撤销一次喜欢会退回一次额度(§3.9);
- **额度默认关闭**:`like_limit = 0` 表示不限,此时 `likes_used` 恒为 `0`、
  `likes_remaining` 为 `null`,客户端据此**不显示**任何额度文案。

额度用完后 `POST /api/v1/discovery/swipe`(`action=like`)返回 `429` + `42904`。

**请求参数**

无。

**响应参数**

| 参数名称 | 类型 | 描述 |
|----------|------|------|
| like_limit | Integer | 每日喜欢上限;`0` = 不限 |
| likes_used | Integer | 今天已用掉的喜欢次数(不限时恒为 `0`) |
| likes_remaining | Integer / null | 今天还剩多少次(不小于 0);`like_limit = 0` 时为 `null` |

**请求示例**

```bash
curl "http://<域名>/api/v1/discovery/quota" \
  -H "Authorization: Bearer <access>"
```

**响应示例**

额度开启(每日 10 次,已用 3 次):

```json
{ "like_limit": 10, "likes_used": 3, "likes_remaining": 7 }
```

额度关闭(默认):

```json
{ "like_limit": 0, "likes_used": 0, "likes_remaining": null }
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |
| 403 | 403 | 账号已被封禁(重封禁) | 提示用户账号受限 |

---

### 3.11 今日精选

> `GET` `/api/v1/discovery/daily` · 需要鉴权 · 与候选卡同款限流

**接口描述**

每天固定 N 张「高匹配」候选,供发现页顶部的精选区块使用。候选来源与 §3.1 **完全同一套
候选池**(排除自己 / 已划过 / 已配对的 / 双向拉黑 / 资料不全 / 无过审照片,并按「想找的人」偏好过滤),
不另写一套规则。

排序口径(依次):

1. **共同标签数降序** —— 与「我」共有的兴趣标签越多越靠前;
2. **同城优先** —— 标签数相同时,与我同城市的人靠前;
3. **种子随机** —— 其余用 `(日期, 我的账号 ID)` 作为随机种子打散,避免所有人千篇一律。

因此**同一天内反复刷新,返回的卡片与顺序都不变**;跨天后种子变化,精选自动换一批。
响应里的 `date` 是服务端算种子用的日期,客户端据此判断「今天已看过」。

**请求参数**(Query)

| 参数名称 | 必填 | 类型 | 描述 |
|----------|------|------|------|
| limit | 否 | Integer | 精选张数,默认 6,上限 12;非法值 400,越界收敛到上限 |

**响应参数**

| 参数名称 | 类型 | 描述 |
|----------|------|------|
| date | Date | 本次精选对应的日期(服务端时区,`YYYY-MM-DD`) |
| candidates | Object[] | 精选卡片数组,字段与 §3.1 的候选卡一致 |

`candidates[]` 每张卡的字段同 §3.1:

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
curl "http://<域名>/api/v1/discovery/daily?limit=6" \
  -H "Authorization: Bearer <access>"
```

**响应示例**

```json
{
  "date": "2026-11-10",
  "candidates": [
    {
      "user_id": 30,
      "nickname": "多多30",
      "gender": "female",
      "age": 25,
      "city": "杭州",
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
}
```

候选池为空时 `candidates` 为 `[]`(`date` 照常返回)。

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 400 | 400 | `limit` 不是整数 | 按错误提示修正参数 |
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |
| 429 | 429 | 超过候选接口限流 | 稍后再试 |
