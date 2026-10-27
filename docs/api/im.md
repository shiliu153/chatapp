# IM 会话凭证

本分册含 3 个接口:获取 IM 登录凭证、上传聊天图片、上传聊天语音。聊天消息本身走 IM 服务(腾讯云或自建),这些接口只负责发放登录所需的凭证,以及为自建后端提供发图/发语音前置的上传通道。

---

### 6.1 获取 IM 登录凭证

> `POST` `/api/v1/im/user_sig` · 需要鉴权 · 无额外限流

**接口描述**

返回 `backend` 与对应凭证:腾讯分支用 `sdkappid` + `im_user_id` + `user_sig`;自建分支用 `token` + `ws_url` + `http_url`。

服务端行为说明:

- **账号自动供给**:每次调用都会确保对应的 IM 账号存在(幂等,无需额外调用)
- **单设备登录联动**:若本次登录顶掉了旧设备,服务端会在发放签名**之前**踢掉旧的 IM 会话;客户端在旧设备上会看到「账号已在其他设备登录」并被迫下线,属预期行为
- 聊天双方的身份映射:IM 账号固定为 `u{user_id}`(如账号 21 → `u21`)
- **灰度**:`IM_BACKEND=self` 且账号命中 `IM_SELF_GRAYLIST` 时返回自建分支,否则仍返回腾讯分支;灰度名单只能放隔离测试号

**请求参数**

无(Body 为空)。

**响应参数**

| 参数名称 | 类型 | 描述 |
|----------|------|------|
| backend | String | `tencent` 或 `self` |
| user_sig | String | 腾讯分支:登录 IM 用的签名串 |
| sdkappid | String | 腾讯分支:腾讯云 IM 应用 ID |
| token | String | 自建分支:HS256 JWT,首帧 `auth` 使用 |
| ws_url | String | 自建分支:WebSocket 地址 |
| http_url | String | 自建分支:历史/会话接口基址 |
| im_user_id | String | 本账号的 IM 账号,格式 `u{user_id}` |
| expire | Integer | 凭证有效期(秒) |

**请求示例**

```bash
curl -X POST http://<域名>/api/v1/im/user_sig \
  -H "Authorization: Bearer <access>"
```

**响应示例(腾讯)**

```json
{
  "backend": "tencent",
  "user_sig": "eJw1zEELgjAYxvGvIrsWslfGNoMOdegUHtyM6B…(签名串,略)",
  "sdkappid": "1600161711",
  "im_user_id": "u21",
  "expire": 604800
}
```

**响应示例(自建)**

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

自建 IM(`backend=self`)发图分两步:先调本接口把图片落盘,拿到 `url`/`thumb_url`,
再把它们放进 WebSocket 的 `send` 帧(`kind=image`)。腾讯分支由 SDK 自己上传,不需要调本接口。

服务端行为说明:

- **同步处理**:落盘 + 生成 240px 缩略图在请求内完成,不走异步队列(该路径没有第三方调用)
- **文件名不可枚举**:`chat/年/月/<账号 id>-<随机 uuid>.jpg`,防止顺着 URL 遍历别人的私聊图
- **EXIF 方向校正**:手机竖拍照片按显示方向记录 `width/height`;方向不为 1 时原图重编码成 JPEG,
  避免「服务端宽高」与「客户端渲染方向」不一致
- **删除由运营执行**:`/ops/chat-images/` 可删除违规图片,删除后聊天里显示占位图

**请求参数**(`multipart/form-data`)

| 参数名称 | 类型 | 必填 | 描述 |
|----------|------|------|------|
| file | File | 是 | 图片文件;jpg/png/webp,≤5MB,长边 ≤4096 |

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
| 400 | 400 | 非图片 / 超过 5MB / 长边超 4096 / 格式不在白名单 | 提示用户换图或先压缩 |
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |
| 403 | 403 | 账号被重封禁,禁止使用(全域 403) | 提示用户账号受限 |
| 429 | 429 | 上传过于频繁(30 次/小时) | 稍后再试 |

---

### 6.3 聊天图片验签(nginx 内部)

> `GET` `/api/v1/im/images/auth` · 无需鉴权 · 无额外限流

**接口描述**

生产 nginx 对 `/media/chat/` 的请求先做一次内部子请求(`auth_request`),由本接口
校验 URL 上的签名与有效期:通过返回 204(nginx 放行静态文件),失败返回 403。
**不是给客户端调的**:请求头 `X-Original-URI` 由 nginx 注入,客户端直接调用只会拿到 403。

- 签名规则:`HMAC-SHA256(IM_MEDIA_SIGN_SECRET, path + "\n" + e)`,小写 hex
- 有效期:`e` 为过期时间戳,由服务端按整点对齐 + `IM_MEDIA_SIGN_TTL`(默认 24h)生成
- 只接受 `/media/chat/` 下的路径;用户照片与广场图片不在此列

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
拿到 `url`,再把它放进 WebSocket 的 `send` 帧(`kind=voice`)。腾讯分支不支持语音,不会调用本接口。

服务端行为说明:

- **统一转码**:浏览器录出的 webm/ogg 由服务端 ffmpeg 转成 m4a(单声道 16kHz 32kbps),
  保证 iOS 也能播放;App 录的 m4a 同样走一遍规范化
- **时长以服务端为准**:用 `ffprobe` 读真实时长,必须在 1–60 秒;与客户端声明的
  `duration_ms` 相差超过 2 秒按参数错误拒绝
- **同步处理**:转码在请求内完成(60 秒音频约 0.2–0.5 秒),不走异步队列;该路径没有第三方网络调用
- **依赖 ffmpeg**:服务器未安装 `ffmpeg`/`ffprobe` 时返回 503 + `50302`,文本与图片不受影响
- **删除与过期**:运营可在 `/ops/chat-voices/` 试听并删除;超过 30 天由清理任务删除文件

**请求参数**(`multipart/form-data`)

| 参数名称 | 类型 | 必填 | 描述 |
|----------|------|------|------|
| file | File | 是 | 音频文件;m4a/aac/webm/ogg,≤5MB |
| duration_ms | Integer | 是 | 客户端测得的时长(毫秒),1000–60000;服务端会与实测值比对 |

**响应参数**

| 参数名称 | 类型 | 描述 |
|----------|------|------|
| id | Integer | 聊天语音主键 |
| url | String | m4a 绝对地址(**带签名**,默认 24 小时有效) |
| duration_ms | Integer | 服务端实测时长(毫秒) |
| size | Integer | 转码后文件字节数(≤2MB) |

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
  "size": 48000
}
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 400 | 400 | 格式不在白名单 / 超过 5MB / 时长不在 1–60 秒 / 客户端时长与实测不符 / 音频无法解码 | 提示用户重录或换文件 |
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |
| 403 | 403 | 账号被重封禁,禁止使用(全域 403) | 提示用户账号受限 |
| 429 | 429 | 上传过于频繁(60 次/小时) | 稍后再试 |
| 50302 | 503 | 服务器缺少 ffmpeg/ffprobe,语音暂不可用 | 联系运维安装 ffmpeg;客户端提示稍后再试 |
