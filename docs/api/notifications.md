# 站内通知

本分册含 3 个接口:通知列表、未读数、标记已读。它们是「站内通知中心」的全部后端能力
(批次 H),**与 IM 灰条并存**:灰条是聊天记录里的事实,通知是聚合索引,两者不互相替代。

**通知类型**(`kind`):

| 取值 | 含义 | 点击跳转 |
|---|---|---|
| `post_like` | 你的动态被点赞 | 动态详情 |
| `post_comment` | 你的动态被评论 | 动态详情 |
| `comment_reply` | 你的评论被回复 | 动态详情 |
| `match` | 配对成功(双方各一条) | 与对方聊天 |
| `report_handled` | 你提交的举报已处理 | 不跳转,只标已读 |
| `system` | 系统消息(预留,当前无调用方) | 由 `target` 决定 |

**公共规则**:

- **只返回 90 天内、只返回自己的**通知;更早的记录仍在库里,由管理命令
  `notifications_prune` 回收(默认 dry-run)。
- 偏好开关在 [push.md §2](push.md#2-通知偏好) 里:`post_like` / `post_comment` /
  `comment_reply` 受 `social` 控制,`match` 受 `matches`,`report_handled` / `system`
  受 `system` 控制;**关掉后不落库**,不只是不展示。
- 触发者是**你自己**时不产生通知(自己赞自己、自己评论自己)。
- 通知正文由服务端生成(`text`),客户端直接展示,不要自己拼文案。

---

### 1.1 通知列表

> `GET` `/api/v1/notifications` · 需要鉴权 · 限流 240 次/小时(按用户)

**接口描述**

分页拉取自己的站内通知,按时间倒序(同一秒内按 id 倒序)。

- 默认走**复合游标分页**(`?before=`),响应 `{count, next_cursor, has_more, results}`;
- 请求里带 `offset`(且不带 `before`)的老客户端仍走 offset 兼容路径,
  响应回到 `{count, next, previous, results}`;
- `actor` 为 `null` 表示系统消息或对方账号已注销;`target.kind=none` 时 `target.id` 为 `null`;
- 目标(动态/用户)被删除后通知仍然保留,客户端按 `target` 跳转失败时只需把该条标为已读。

**请求参数**(Query)

| 参数名称 | 必填 | 类型 | 描述 |
|----------|------|------|------|
| limit | 否 | Integer | 每页条数,默认 20,上限 100 |
| before | 否 | String | 游标。首页不传;之后原样回传上一页的 `next_cursor`(见 [conventions.md §分页约定](conventions.md#分页约定)) |

**响应参数**

游标分页对象(见 [conventions.md §分页约定](conventions.md#分页约定)),`results[]` 为通知对象:

| 参数名称 | 类型 | 描述 |
|----------|------|------|
| id | Integer | 通知 ID |
| kind | String | 通知类型,取值见本分册首部表格 |
| text | String | 服务端生成的通知正文,≤200 字 |
| is_read | Boolean | 是否已读 |
| created_at | String | 创建时间(ISO 8601) |
| actor | Object / null | 触发者摘要,见下表;系统消息为 `null` |
| target | Object | 跳转目标 `{kind, id}`,见下表 |

`actor` 字段:

| 参数名称 | 类型 | 描述 |
|----------|------|------|
| id | Integer | 触发者**账号 ID**(可直接拼 `/chat/{id}`) |
| nickname | String | 触发者昵称;未填资料为空字符串 |
| avatar | String / null | 触发者头像(首张已过审照片);无照片为 `null` |

`target` 字段:

| 参数名称 | 类型 | 描述 |
|----------|------|------|
| kind | String | `post` / `user` / `none` |
| id | Integer / null | 目标主键;`kind=none` 时为 `null` |

**请求示例**

```bash
curl "http://<域名>/api/v1/notifications?limit=20" \
  -H "Authorization: Bearer <access>"

# 第二页:把上一页响应里的 next_cursor 原样带回来
curl "http://<域名>/api/v1/notifications?limit=20&before=<next_cursor>" \
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
      "kind": "post_like",
      "text": "小明 赞了你的动态",
      "is_read": false,
      "created_at": "2026-11-06T12:30:00.123456+08:00",
      "actor": {
        "id": 7,
        "nickname": "小明",
        "avatar": "http://<域名>/media/photos/2026/11/seed_7_0.jpg"
      },
      "target": {
        "kind": "post",
        "id": 9
      }
    },
    {
      "id": 11,
      "kind": "system",
      "text": "你的举报已处理,感谢你的反馈",
      "is_read": true,
      "created_at": "2026-11-06T10:00:00+08:00",
      "actor": null,
      "target": {
        "kind": "none",
        "id": null
      }
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

### 1.2 未读通知数

> `GET` `/api/v1/notifications/unread_count` · 需要鉴权 · 限流 480 次/小时(按用户)

**接口描述**

返回自己的未读通知条数,供消息页铃铛角标使用。

- 口径与 [1.1 通知列表](#11-通知列表)完全一致(自己的、90 天内);
- 角标只增不减的客户端实现会读到旧值,进通知页后请重新拉一次本接口;
- **前端约定:铃铛角标的轮询间隔 ≥ 30 秒**(2026-11-08)。额度是 480 次/小时/账号,
  30 秒一次 = 120 次/小时、60 秒一次 = 60 次/小时,都留得下余量;若为了「更快看到红点」
  把间隔压到 10 秒(360 次/小时),**多端同时在线**(同一账号手机 + 网页各一个角标)就会
  把额度打满,此后的请求一律 `429`、角标直接不更新 —— 症状是「有未读但角标不动」,
  看上去像丢通知,其实是限流。真需要更快,先看 `Retry-After`,别缩间隔。

**响应参数**

| 参数名称 | 类型 | 描述 |
|----------|------|------|
| unread | Integer | 未读通知条数 |

**请求示例**

```bash
curl "http://<域名>/api/v1/notifications/unread_count" \
  -H "Authorization: Bearer <access>"
```

**响应示例**

```json
{
  "unread": 3
}
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |
| 429 | 429 | 触发限流(480 次/小时) | 按 `Retry-After` 等待 |

---

### 1.3 标记已读

> `POST` `/api/v1/notifications/read` · 需要鉴权 · 无额外限流

**接口描述**

把通知标记为已读,两种用法二选一:

- `{"ids": [1, 2]}`:只标指定几条(点开某条时用);
- `{"all": true}`:标全部未读(点「全部已读」时用)。

规则:

- **只影响自己的通知**:别人的 id 混进来会被静默过滤,仍返回 `204`(不泄漏该通知是否存在);
- **幂等**:已读的再标一次仍是 `204`;
- 只处理 90 天窗口内的通知(窗口外的旧通知不参与)。

**请求参数**(Body,`application/json`)

| 参数名称 | 必填 | 类型 | 描述 |
|----------|------|------|------|
| ids | 否 | Integer[] | 要标记的通知 ID 数组;与 `all` 二选一 |
| all | 否 | Boolean | `true` 表示标记全部未读;与 `ids` 二选一 |

**响应参数**

无响应体,HTTP `204`。

**请求示例**

```bash
# 标单条
curl -X POST "http://<域名>/api/v1/notifications/read" \
  -H "Authorization: Bearer <access>" \
  -H "Content-Type: application/json" \
  -d '{"ids":[12]}'

# 全部已读
curl -X POST "http://<域名>/api/v1/notifications/read" \
  -H "Authorization: Bearer <access>" \
  -H "Content-Type: application/json" \
  -d '{"all":true}'
```

**响应示例**

```
HTTP/1.1 204 No Content
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 400 | 400 | `ids` 与 `all` 都没给(空 body) | 至少给一个 |
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |
