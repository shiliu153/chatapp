# IM 会话凭证

本分册含 1 个接口:获取 IM userSig。聊天消息本身走腾讯云 IM(不经本服务端),本接口只负责发放登录 IM 所需的凭证。

---

### 6.1 获取 IM userSig

> `POST` `/api/v1/im/user_sig` · 需要鉴权 · 无额外限流

**接口描述**

换取腾讯云 IM 的 `userSig`,客户端用 `sdkappid` + `im_user_id` + `user_sig` 初始化 IM SDK 后即可收发消息。

服务端行为说明:

- **账号自动供给**:每次调用都会确保对应的 IM 账号存在(幂等,无需额外调用)
- **单设备登录联动**:若本次登录顶掉了旧设备,服务端会在发放签名**之前**踢掉旧的 IM 会话;客户端在旧设备上会看到「账号已在其他设备登录」并被迫下线,属预期行为
- 聊天双方的身份映射:IM 账号固定为 `u{user_id}`(如账号 21 → `u21`)

**请求参数**

无(Body 为空)。

**响应参数**

| 参数名称 | 类型 | 描述 |
|----------|------|------|
| user_sig | String | 登录 IM 用的签名串,有效期见 `expire` |
| sdkappid | String | 腾讯云 IM 应用 ID(SDK 初始化用) |
| im_user_id | String | 本账号的 IM 账号,格式 `u{user_id}` |
| expire | Integer | `user_sig` 有效期(秒),当前为 604800(7 天) |

**请求示例**

```bash
curl -X POST http://<域名>/api/v1/im/user_sig \
  -H "Authorization: Bearer <access>"
```

**响应示例**

```json
{
  "user_sig": "eJw1zEELgjAYxvGvIrsWslfGNoMOdegUHtyM6B…(签名串,略)",
  "sdkappid": "1600161711",
  "im_user_id": "u21",
  "expire": 604800
}
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |
| 403 | 403 | 账号被重封禁,禁止使用(全域 403) | 提示用户账号受限 |
