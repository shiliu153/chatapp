# 账号与鉴权

登录流程:**发送验证码 → 校验验证码换令牌 → 后续请求带 `access`**(access 过期时用 `refresh` 换新的)。

令牌规则:access 有效期 30 分钟,refresh 有效期 30 天;每次刷新都会轮换两个令牌(旧 refresh 立即失效);同一账号只允许一台设备在线(见 1.2 与 1.3 的单设备登录说明)。

---

### 1.1 发送短信验证码

> `POST` `/api/v1/auth/sms/send` · 无需鉴权 · 限流 20 次/小时(按 IP)

**接口描述**

向指定手机号下发 6 位短信验证码,用于登录。验证码 **5 分钟**内有效;同一手机号 **60 秒**内只能发送一次;校验连续错误 5 次会锁定 15 分钟。

测试环境验证码固定为 `123456`,不会真实发送短信(见 [conventions.md §测试环境专用行为](conventions.md#测试环境专用行为))。

**请求参数**(Body,`application/json`)

| 参数名称 | 必填 | 类型 | 描述 |
|----------|------|------|------|
| phone | 是 | String | 中国大陆手机号,11 位数字(格式 `^1[3-9]\d{9}$`),最长 20 字符 |

**响应参数**

| 参数名称 | 类型 | 描述 |
|----------|------|------|
| status | String | 固定为 `"ok"`,表示已受理(不代表已送达) |

**请求示例**

```bash
curl -X POST http://<域名>/api/v1/auth/sms/send \
  -H "Content-Type: application/json" \
  -d '{"phone": "13800000001"}'
```

**响应示例**

成功:

```json
{ "status": "ok" }
```

60 秒内重复发送(响应头带 `Retry-After: 60`):

```json
{
  "code": 42901,
  "message": "发送太频繁,请稍后再试 预计 60 秒后可用。",
  "request_id": "fa18f86214b442d0b1b1c2f5a95c45d9"
}
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 400 | 400 | 手机号格式不正确 | 检查号码是否为 11 位大陆手机号 |
| 42901 | 429 | 发送太频繁(同一手机号 60 秒间隔) | 按响应头 `Retry-After`(秒)等待后重试 |
| 429 | 429 | 触发 IP 限流(20 次/小时) | 按 `Retry-After` 等待;测试环境可换网络或稍后再试 |
| 50301 | 503 | 短信服务暂时不可用 | 稍后重试(服务端已回滚本次发送占位,可立即重试) |

---

### 1.2 校验验证码并登录

> `POST` `/api/v1/auth/sms/verify` · 无需鉴权 · 限流 60 次/小时(按 IP)

**接口描述**

校验短信验证码,通过后签发令牌。**未注册过的手机号会自动创建账号**(响应 `is_new_user: true`)。校验成功后有 60 秒的幂等重放窗口:响应丢失时用同样的号码与验证码再请求一次,会返回同一批令牌而不报错。

**单设备登录**:同一账号同时只允许一台设备在线。再次登录会使旧设备的令牌失效——旧设备的后续请求返回 `401` + `code: 40101`,应清空本地凭证回到登录页。

**Web 端令牌下发方式**:请求头带 `X-Client: web` 时,`refresh` 不再出现在响应体里,改为通过 `Set-Cookie` 下发(`HttpOnly`、`SameSite=Strict`、`Path=/api/v1/auth/`),页面脚本读不到它;此时响应只有 `access`。App 不带该头,行为保持不变。

**请求参数**(Body,`application/json`)

| 参数名称 | 必填 | 类型 | 描述 |
|----------|------|------|------|
| phone | 是 | String | 中国大陆手机号,11 位数字 |
| code | 是 | String | 6 位验证码(长度必须正好 6 位) |

**请求头**(可选)

| 参数名称 | 必填 | 类型 | 描述 |
|----------|------|------|------|
| X-Client | 否 | String | 填 `web` 表示浏览器客户端:refresh 走 HttpOnly Cookie,响应体不含 `refresh` |

**响应参数**

| 参数名称 | 类型 | 描述 |
|----------|------|------|
| access | String | 访问令牌(JWT),后续请求放在 `Authorization: Bearer <access>`,有效期 30 分钟 |
| refresh | String | 刷新令牌(JWT),用于 1.3 换新令牌,有效期 30 天。**`X-Client: web` 时不返回** |
| is_new_user | Boolean | 是否本次登录自动创建的新账号 |
| user_id | Integer | 账号 ID。注意:与 `GET /api/v1/users/me` 响应里的 `id`(资料主键)不是同一个值 |

**请求示例**

```bash
curl -X POST http://<域名>/api/v1/auth/sms/verify \
  -H "Content-Type: application/json" \
  -d '{"phone": "13800000001", "code": "123456"}'
```

**响应示例**

成功:

```json
{
  "access": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.…(JWT,略)",
  "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.…(JWT,略)",
  "is_new_user": false,
  "user_id": 21
}
```

验证码错误:

```json
{
  "code": 40002,
  "message": "验证码错误",
  "request_id": "d5303c4f1db0435dab78c089218a42ff"
}
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 400 | 400 | 参数不合法(手机号格式、验证码不是 6 位) | 检查请求参数 |
| 40001 | 400 | 验证码已过期,请重新获取 | 重新调用 1.1 获取新验证码 |
| 40002 | 400 | 验证码错误 | 提示用户核对;连续错误 5 次将锁定 15 分钟 |
| 42902 | 429 | 错误次数过多,请稍后再试(锁定 15 分钟) | 按 `Retry-After`(900 秒)等待 |
| 429 | 429 | 触发 IP 限流(60 次/小时) | 按 `Retry-After` 等待 |

---

### 1.3 刷新访问令牌

> `POST` `/api/v1/auth/token/refresh` · 无需鉴权 · 无额外限流

**接口描述**

用 `refresh` 换取新的 `access` 与 `refresh`。**每次刷新都会轮换**:响应的 `refresh` 是新的,旧的立即进入黑名单,不能再用。

**令牌来源**:请求体里的 `refresh` 优先(App 用法);没有时读 `chatapp_rt` Cookie(Web 用法)。带 `X-Client: web` 或请求里带该 Cookie 时,响应只返回 `access`,新 refresh 通过 `Set-Cookie` 下发。

**轮换宽限(60 秒)**:多个浏览器标签页同时刷新时,后到的请求可能拿着刚被轮换掉的旧 `refresh`。这类请求在 60 秒宽限内会拿到同一对新令牌而不报错;超过 60 秒的重复使用视为令牌泄露重放,返回 401。

被其他设备顶号(单设备登录)后,旧设备的 `refresh` 也一并失效,刷新时返回 `401` + `code: 40101`。

**请求参数**(Body,`application/json`)

| 参数名称 | 必填 | 类型 | 描述 |
|----------|------|------|------|
| refresh | 否 | String | 刷新令牌。Web 可省略,改由 Cookie 携带 |

**请求头**(可选)

| 参数名称 | 必填 | 类型 | 描述 |
|----------|------|------|------|
| X-Client | 否 | String | 填 `web` 时按浏览器客户端处理:响应不含 `refresh`,改为下发 Cookie |

**响应参数**

| 参数名称 | 类型 | 描述 |
|----------|------|------|
| access | String | 新的访问令牌(有效期 30 分钟) |
| refresh | String | **新的**刷新令牌(有效期 30 天),请覆盖旧值保存。Web 客户端不返回该字段 |

**请求示例**

App(请求体带 refresh):

```bash
curl -X POST http://<域名>/api/v1/auth/token/refresh \
  -H "Content-Type: application/json" \
  -d '{"refresh": "<refresh>"}'
```

Web(依赖 Cookie,请求体为空):

```bash
curl -X POST http://<域名>/api/v1/auth/token/refresh \
  -H "X-Client: web" \
  -b "chatapp_rt=<refresh>"
```

**响应示例**

App 成功:

```json
{
  "access": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.…(JWT,略)",
  "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.…(JWT,略)"
}
```

Web 成功(响应体只有 access,新 refresh 在 `Set-Cookie` 里):

```json
{ "access": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.…(JWT,略)" }
```

refresh 无效(格式错误 / 已过期 / 超出宽限期的重复使用):

```json
{
  "code": 401,
  "message": "登录状态已失效,请重新登录",
  "request_id": "355cf27ba8144811b15f04afa474f1b4"
}
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 401 | 401 | 刷新令牌无效或已过期 | 回到登录页,重新走 1.1 / 1.2 |
| 40101 | 401 | 账号已在其他设备登录,请重新登录 | 本机已被顶号,清空凭证回登录页 |

---

### 1.4 注销

> `POST` `/api/v1/auth/logout` · 无需鉴权 · 无额外限流

**接口描述**

结束当前会话:把本次的 `refresh` 加入黑名单,并清除 `chatapp_rt` Cookie。**幂等**——令牌缺失、已过期或已被拉黑都返回 204,客户端只需清空本地状态。

App 没有服务端会话可清时可以不调本接口(直接丢弃本地令牌即可);Web 因为 refresh 在 HttpOnly Cookie 里,必须调本接口才能真正清除。

**请求参数**(Body,`application/json`,可选)

| 参数名称 | 必填 | 类型 | 描述 |
|----------|------|------|------|
| refresh | 否 | String | 要拉黑的刷新令牌;Web 可省略,从 Cookie 读取 |

**响应参数**

无响应体(204),`Set-Cookie` 会清除 `chatapp_rt`。

**请求示例**

```bash
curl -X POST http://<域名>/api/v1/auth/logout \
  -H "Content-Type: application/json" \
  -d '{"refresh": "<refresh>"}'
```

**响应示例**

```
HTTP/1.1 204 No Content
Set-Cookie: chatapp_rt=""; expires=Thu, 01 Jan 1970 00:00:00 GMT; Max-Age=0; Path=/api/v1/auth/; HttpOnly; SameSite=Strict
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 405 | 405 | 使用了 GET 等非 POST 方法 | 改用 POST |
