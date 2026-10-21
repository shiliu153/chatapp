# IM 会话凭证

本分册含 1 个接口:获取 IM 登录凭证。聊天消息本身走 IM 服务(腾讯云或自建),本接口只负责发放登录所需的凭证与后端地址。

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
