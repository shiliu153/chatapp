---
状态: 生效中
复核: 每次接口变更时
---

# IM 会话凭证

本分册含 5 个接口:获取 IM 登录凭证、上传聊天图片、上传聊天语音、查询聊天语音的转码状态,以及 nginx 内部验签子请求 `GET /im/images/auth`(不是给客户端调的,见 6.3)。聊天消息本身走自建 IM(`imserver/`),这些接口只负责发放登录所需的凭证,以及提供发图/发语音前置的上传通道。

聊天记录搜索(`GET /im/api/search`)、会话列表、历史消息、会话置顶/免打扰(`POST /im/api/conversations/flags`)、多选删除(`POST /im/api/messages/delete`)与 WS 帧一样属于 imserver 的内部契约,**不在本分册**(它们不走 `/api/v1` 门禁);文档见 [`docs/ops/imserver.md`](../ops/imserver.md) §16(搜索)、§15(已读回执)、§19(置顶/免打扰,含会话列表新增的 `pinned`/`muted` 字段与排序口径)与 §21(多选删除,单方删除的产品口径与三处读口径)。

---

### 6.1 获取 IM 登录凭证

> `POST` `/api/v1/im/user_sig` · 需要鉴权 · 无额外限流

**接口描述**

返回自建 IM 的登录凭证:`token`(HS256 JWT,首帧 `auth` 使用)+ `ws_url` + `http_url`。腾讯云 IM 分支已于 2026-11-08 删除,响应里不再有 `user_sig` / `sdkappid`,`backend` 恒为 `self`。

服务端行为说明:

- **账号自动供给**:每次调用都会确保对应的 IM 账号存在(幂等,无需额外调用)
- **按端踢旧会话(多端在线)**:端类型取请求头 `X-Client`(填 `web` 为网页端,**缺省 `app`**)。登录顶掉的是**同一类端**的旧会话,服务端会在发放签名**之前**只踢这一端的旧 IM 会话 —— 一个网页登录**不会**把手机上的 IM 连接踢掉;被顶的那台同类设备会看到「账号已在其他设备登录」并被迫下线,属预期行为。需要踢掉所有端时用 `POST /api/v1/auth/logout/all`(见 [auth.md §1.5](auth.md#15-退出所有设备))
- 聊天双方的身份映射:IM 账号固定为 `u{user_id}`(如账号 21 → `u21`)
- **会话版本按端**:签发前会把账号在**该端**的会话版本同步到 imserver(按 `(uid, client_type)` 落库),同步失败返回 503(fail-closed,避免发出一个会被服务端拒绝的 token)

**请求参数**

无(Body 为空)。

**响应参数**

| 参数名称 | 类型 | 描述 |
|----------|------|------|
| backend | String | 恒为 `self`(保留字段以兼容老客户端) |
| token | String | HS256 JWT,首帧 `auth` 使用;带 `sv`(**该端**的会话版本)与 `ct`(端类型 `app` / `web`)|
| ws_url | String | WebSocket 地址 |
| http_url | String | 历史/会话接口基址 |
| im_user_id | String | 本账号的 IM 账号,格式 `u{user_id}` |
| expire | Integer | 凭证有效期(秒) |

**请求示例**

```bash
curl -X POST http://<域名>/api/v1/im/user_sig \
  -H "Authorization: Bearer <access>"
```

**响应示例**

```json
{
  "backend": "self",
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9…",
  "ws_url": "wss://<域名>/im/ws",
  "http_url": "https://<域名>/im/api",
  "im_user_id": "u21",
  "expire": 86400
}
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |
| 403 | 403 | 账号被重封禁,禁止使用(全域 403) | 提示用户账号受限 |

---

### 6.2 上传聊天图片

> `POST` `/api/v1/im/images` · 需要鉴权 · 限流 30 次/小时(按账号)

**接口描述**

发图分两步:先调本接口把图片落盘,拿到 `url`/`thumb_url`,
再把它们放进 WebSocket 的 `send` 帧(`kind=image`)。

服务端行为说明:

- **同步处理**:落盘 + 生成 240px 缩略图在请求内完成,不走异步队列(该路径没有第三方调用)
- **文件名不可枚举**:`chat/年/月/<账号 id>-<随机 uuid>.jpg`,防止顺着 URL 遍历别人的私聊图
- **EXIF 方向校正**:手机竖拍照片按显示方向记录 `width/height`;方向不为 1 时原图重编码成 JPEG,
  避免「服务端宽高」与「客户端渲染方向」不一致
- **可选幂等键**:请求头带 `Idempotency-Key` 时,同一次上传的重试**不会**再落一份文件、多建一条行 ——
  已完成的重放同一个 `201` 响应体(同一个 `id`,地址重新签名),上一次还没处理完时后到的请求返回
  `409` + `40901`;失败(`400`/`413`/`503`)会释放 key,改好文件用同一个 key 直接重传即可。
  完整语义(取值、作用域、有效期)见 [conventions.md §幂等键](conventions.md#幂等键可选仅上传类接口)
- **删除由运营执行**:`/ops/chat-images/` 可删除违规图片,删除后聊天里显示占位图

**请求参数**(`multipart/form-data` + 可选请求头)

| 参数名称 | 类型 | 必填 | 描述 |
|----------|------|------|------|
| file | File | 是 | 图片文件;jpg/png/webp,≤5MB,长边 ≤4096 |
| Idempotency-Key | String | 否 | **请求头**(不是表单字段)。可选幂等键:1–128 个字母、数字与 `.` `_` `:` `-`,重试时复用同一个值;规则见 [conventions.md §幂等键](conventions.md#幂等键可选仅上传类接口) |

**响应参数**

| 参数名称 | 类型 | 描述 |
|----------|------|------|
| id | Integer | 聊天图片主键 |
| url | String | 原图绝对地址(**带签名**,默认 24 小时有效) |
| thumb_url | String | 缩略图绝对地址(长边 240,**带签名**) |
| width | Integer | 显示宽度(已按 EXIF 方向校正) |
| height | Integer | 显示高度 |
| size | Integer | 文件字节数 |

> `url` / `thumb_url` 是**限时签名地址**(规则见 6.3):默认 24 小时、按整点对齐。
> 直接使用即可;签名过期或被运营删除后返回 403/404,客户端按加载失败占位处理。

**请求示例**

```bash
curl -X POST http://<域名>/api/v1/im/images \
  -H "Authorization: Bearer <access>" \
  -F "file=@/path/to/photo.jpg"
```

**响应示例**

```json
{
  "id": 123,
  "url": "https://<域名>/media/chat/2026/10/7-a1b2c3d4.jpg?e=1761782400&s=9f2c...e1",
  "thumb_url": "https://<域名>/media/chat/2026/10/7-a1b2c3d4_thumb.jpg?e=1761782400&s=1a2b...c3",
  "width": 1080,
  "height": 1440,
  "size": 345678
}
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 400 | 400 | 非图片 / 超过 5MB / 长边超 4096 / 格式不在白名单 / `Idempotency-Key` 不合规(长度或字符) | 提示用户换图或先压缩;key 不合规时换一个新生成的 key |
| 41301 | 413 | 账号媒体存储已满(message 含已用/上限) | 提示用户删除部分照片,或等待聊天图片 30 天后过期 |
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |
| 403 | 403 | 账号被重封禁,禁止使用(全域 403) | 提示用户账号受限 |
| 40901 | 409 | 同一个 `Idempotency-Key` 的上一次上传还在处理中 | 退避 1–2 秒后用**同一个 key** 重试(会拿到首次的结果);**不要换 key**,换 key 等于把重试当成新上传 |
| 429 | 429 | 上传过于频繁(30 次/小时) | 稍后再试 |

---

### 6.3 媒体验签(nginx 内部:聊天媒体与资料语音)

> `GET` `/api/v1/im/images/auth` · 无需鉴权 · 无额外限流

**接口描述**

生产 nginx 对受保护媒体前缀的请求先做一次内部子请求(`auth_request`),由本接口
校验 URL 上的签名与有效期:通过返回 204(nginx 放行静态文件),失败返回 403。
**不是给客户端调的**:请求头 `X-Original-URI` 由 nginx 注入,客户端直接调用只会拿到 403。

- 签名规则:`HMAC-SHA256(IM_MEDIA_SIGN_SECRET, path + "\n" + e)`,小写 hex(**算法未变,两侧仍逐字节一致**)
- 有效期:`e` 为过期时间戳,由服务端按整点对齐 + `IM_MEDIA_SIGN_TTL`(默认 24h)生成
- 可签名/可验签的路径白名单 = `im/media_sign.py::SIGN_PATH_PREFIXES`:`/media/chat/`(聊天图片与语音)+ `/media/voices/`(资料语音自我介绍,2026-11-16 起);用户资料图与广场图片不在此列
- 目前 nginx 只把这个子请求接在 `/media/chat/` 上;`/media/voices/` 的 `auth_request` 属于 `deploy/**`,上线前资料语音的直链仍可无签名访问

**请求参数**(请求头)

| 参数名称 | 类型 | 必填 | 描述 |
|----------|------|------|------|
| X-Original-URI | String | 是 | 原始 URI,形如 `/media/chat/2026/10/7-a1b2.jpg?e=1761782400&s=...` |

**响应参数**

通过:HTTP 204,无响应体。

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 403 | 403 | 缺 `X-Original-URI` / 路径越界 / 已过期 / 签名不符 | 重新进入聊天页刷新历史以拿到新链接 |

---

### 6.4 上传聊天语音

> `POST` `/api/v1/im/voices` · 需要鉴权 · 限流 60 次/小时(按账号)

**接口描述**

自建 IM(`backend=self`)发语音分两步:先调本接口把音频落盘并**统一转码为 m4a/AAC**,
拿到 `url`,再把它放进 WebSocket 的 `send` 帧(`kind=voice`)。

服务端行为说明:

- **统一转码**:浏览器录出的 webm/ogg 由服务端 ffmpeg 转成 m4a(单声道 16kHz 32kbps),
  保证 iOS 也能播放;App 录的 m4a 同样走一遍规范化
- **时长以服务端为准**:用 `ffprobe` 读真实时长,必须在 1–60 秒;与客户端声明的
  `duration_ms` 相差超过 2 秒按参数错误拒绝
- **抢到转码槽时同步完成**:转码在请求内做完(60 秒音频约 0.2–0.5 秒),直接返回 `201` 与 `url`;该路径没有第三方网络调用
- **抢不到槽时改走异步**(M-3):服务器同一时刻只跑**一路** ffmpeg(与资料语音自我介绍共用一个槽)。槽被别的上传占着时,本接口**不再回 503**,而是把原始文件落进临时区、入队(`bulk` 队列)并**立即**返回 `202 + status=pending + retry_after`;客户端此后按 `retry_after` 轮询 6.5 拿最终结果
- **异步路径的校验顺序**:上传时只做浅校验(≤5MB、MIME 白名单、声明时长上限);`ffprobe` 实测时长与配额检查都在 worker 落盘之前做 —— 异步没法同步回 400/413,失败一律体现为该语音 `status=failed`,原因见 6.5 的 `code` / `message`(配额超限是 `41301`)
- **依赖 ffmpeg**:服务器未安装 `ffmpeg`/`ffprobe` 时返回 503 + `50302`(异步路径同样在受理前就用 503 挡掉,不会先收 202 再失败),文本与图片不受影响
- **可选幂等键**:请求头带 `Idempotency-Key` 时,同一次上传的重试不会新建第二条语音 ——
  已完成的重放同一个 `201`(`id` 相同,地址重新签名);异步路径记录了 `pending`,在转码完成前
  重试拿回的是**同一个 `id`** 的 `202`,照旧按 `retry_after` 轮询 6.5 即可,不必重传。
  上一次还没处理完时后到的请求返回 `409` + `40901`;失败(`400`/`413`/`503`)与转码失败
  (`status=failed`)都会释放 key。完整语义见 [conventions.md §幂等键](conventions.md#幂等键可选仅上传类接口)
- **删除与过期**:运营可在 `/ops/chat-voices/` 试听并删除;超过 30 天由清理任务删除文件

**请求参数**(`multipart/form-data` + 可选请求头)

| 参数名称 | 类型 | 必填 | 描述 |
|----------|------|------|------|
| file | File | 是 | 音频文件;m4a/aac/webm/ogg,≤5MB |
| duration_ms | Integer | 是 | 客户端测得的时长(毫秒),1000–60000;服务端会与实测值比对 |
| Idempotency-Key | String | 否 | **请求头**(不是表单字段)。可选幂等键:1–128 个字母、数字与 `.` `_` `:` `-`,重试时复用同一个值;规则见 [conventions.md §幂等键](conventions.md#幂等键可选仅上传类接口) |

**响应参数**

| 参数名称 | 类型 | 描述 |
|----------|------|------|
| id | Integer | 聊天语音主键 |
| url | String | m4a 绝对地址(**带签名**,默认 24 小时有效) |
| duration_ms | Integer | 服务端实测时长(毫秒) |
| size | Integer | 转码后文件字节数(≤2MB) |
| status | String | 转码状态,本响应恒为 `ready` |

**响应参数(202:已受理,转码排队中)**

| 参数名称 | 类型 | 描述 |
|----------|------|------|
| id | Integer | 聊天语音主键,用它轮询 6.5 |
| status | String | 恒为 `pending` |
| retry_after | Integer | 建议的轮询间隔(秒),默认 5 |

> `202` 的响应**不带 `url`**:文件还没转码落盘,拿不到可播放地址。

> 与图片一样,`url` 是**限时签名地址**,放在 WS `send` 帧里发给对方;imserver 会去掉
> query 存规范 URL,读历史时重新签名,避免死链。

**请求示例**

```bash
curl -X POST http://<域名>/api/v1/im/voices \
  -H "Authorization: Bearer <access>" \
  -F "file=@/path/to/voice.m4a" \
  -F "duration_ms=12500"
```

**响应示例**

```json
{
  "id": 45,
  "url": "https://<域名>/media/chat/voices/2026/10/7-a1b2c3d4.m4a?e=1761782400&s=9f2c...e1",
  "duration_ms": 12500,
  "size": 48000,
  "status": "ready"
}
```

**响应示例(202,槽被占用)**

```json
{
  "id": 46,
  "status": "pending",
  "retry_after": 5
}
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 400 | 400 | 格式不在白名单 / 超过 5MB / 时长不在 1–60 秒 / 客户端时长与实测不符 / 音频无法解码 / `Idempotency-Key` 不合规(长度或字符) | 提示用户重录或换文件;key 不合规时换一个新生成的 key |
| 41301 | 413 | 账号媒体存储已满(message 含已用/上限) | 提示用户删除部分照片,或等待聊天媒体 30 天后过期 |
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |
| 403 | 403 | 账号被重封禁,禁止使用(全域 403) | 提示用户账号受限 |
| 40901 | 409 | 同一个 `Idempotency-Key` 的上一次上传还在处理中 | 退避 1–2 秒后用**同一个 key** 重试(会拿到首次的 `201` 或同一个 `id` 的 `202`);**不要换 key** |
| 429 | 429 | 上传过于频繁(60 次/小时) | 稍后再试 |
| 50302 | 503 | 语音暂不可用:服务器缺少 ffmpeg/ffprobe | 联系运维安装 ffmpeg/ffprobe;客户端提示「语音暂不可用,请稍后重试」 |

> 转码槽被占用**不再**是错误:这种情况返回 `202`,按 `retry_after` 轮询 6.5 即可。
> 带 `Idempotency-Key` 时,`202` 期间的重试只会拿回**同一个 `id`**,不会再多一条语音。

---

### 6.5 查询聊天语音转码状态

> `GET` `/api/v1/im/voices/{voice_id}` · 需要鉴权 · 限流 480 次/小时(按账号)

**接口描述**

6.4 返回 `202 + status=pending` 时,用本接口按 `retry_after` 轮询,直到 `status` 变成 `ready` 拿到 `url`,`failed` 则按 `code` / `message` 提示用户重录。

三态语义(聊天语音与资料语音同一套,见 users.md §2.13):

| status | 含义 | 客户端该做什么 |
|--------|------|----------------|
| `pending` | 排队/转码中 | 等 `retry_after` 秒后再查一次;不要重发上传 |
| `ready` | 可播放 | 取 `url` 放进 WS `send` 帧(`kind=voice`) |
| `failed` | 转码失败 | 提示用户重录;`code` 是业务码(如 `41301` 存储已满),没有业务码时看 `message` |

**请求参数**

| 参数名称 | 类型 | 必填 | 描述 |
|----------|------|------|------|
| voice_id | Integer | 是 | 6.4 返回的聊天语音主键 |

**响应参数**

| 参数名称 | 类型 | 描述 |
|----------|------|------|
| id | Integer | 聊天语音主键 |
| status | String | `pending` / `ready` / `failed` |
| url | String | `ready` 时的 m4a 绝对地址(**带签名**,默认 24 小时有效);`pending` / `failed` 为 `null` |
| duration_ms | Integer | `ready` 时的实测时长(毫秒);否则 `null` |
| size | Integer | `ready` 时的文件字节数;否则 `null` |
| code | String | `failed` 时的业务码(如 `41301`、`50302`);否则 `null` |
| message | String | `failed` 时可直接展示的中文提示;否则 `null` |

**请求示例**

```bash
curl http://<域名>/api/v1/im/voices/46 \
  -H "Authorization: Bearer <access>"
```

**响应示例**

```json
{
  "id": 46,
  "status": "ready",
  "url": "https://<域名>/media/chat/voices/2026/11/7-a1b2c3d4.m4a?e=1761782400&s=9f2c...e1",
  "duration_ms": 12500,
  "size": 48000,
  "code": null,
  "message": null
}
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 404 | 404 | 语音不存在,或不是当前账号上传的(不区分这两种情况) | 检查 `id` 是否来自自己的上传响应 |
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |
| 403 | 403 | 账号被重封禁,禁止使用(全域 403) | 提示用户账号受限 |
| 429 | 429 | 轮询过于频繁(480 次/小时) | 按 `retry_after` 退避后再查 |
