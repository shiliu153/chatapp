# 令牌硬化设计（Web refresh Cookie + App 安全存储 + 证书绑定）

> 日期：2026-10-28
> 状态：已获用户批准（方案 A + 直接 enforce）
> 依据：[接口安全审计](../security/2026-10-27-api-security-audit.md) H1 剩余项、L8
> 上游计划：[2026-10-28-security-remediation.md](../plans/2026-10-28-security-remediation.md) §4「仍未关闭」

## 1. 背景

审计 H1 的 HTTPS 部分已于 2026-10-28 上线，剩两条没关：

1. **Web 的 access/refresh 存在 `localStorage`**：任意 XSS、第三方脚本、浏览器扩展都能读走 30 天有效的 refresh，等价于长期账号接管。
2. **App 未做证书绑定**：系统信任链里任何 CA（含企业/杀软根证书）签的证书都能中间人解密。

另有 L8：App 令牌存 `SharedPreferences` 明文，root / 备份 / 恶意应用可读。

## 2. 目标与非目标

**目标**

- Web 端 JS **永远拿不到 refresh token**；access 只存内存，页面关闭即失效。
- App 令牌落 Android Keystore / iOS Keychain，老用户无感迁移（不被登出）。
- App 的 HTTPS 与 WSS 都只信任固定根（ISRG Root X1 + 备用 ISRG Root X2），release 包默认强制。

**非目标**

- 不做完整 BFF（同源部署下收益不抵改造成本）。
- 不改 App 的登录/刷新协议（仍走 body 里的 refresh），只改存储层。
- 不动腾讯 IM SDK 自己的网络栈（第三方，无法 pin）。

## 3. Web：refresh 进 HttpOnly Cookie

### 3.1 客户端识别

Web 的 axios 实例统一带 `X-Client: web` 头；App 不带。后端据此二选一：

| 分支 | 登录响应 | refresh 响应 |
|---|---|---|
| Web（`X-Client: web`） | `{access, is_new_user, user_id}` + `Set-Cookie` | `{access}` + 轮换后的 `Set-Cookie` |
| App（无该头） | `{access, refresh, is_new_user, user_id}`（不变） | `{access, refresh}`（不变） |

> 为什么用自定义头而不是 User-Agent：UA 可伪造且难测；自定义头跨域会触发预检，而生产 CORS 白名单为空，第三方站点发不出来。

### 3.2 Cookie 属性

```
Set-Cookie: chatapp_rt=<jwt>; Path=/api/v1/auth/; HttpOnly; SameSite=Strict; Max-Age=<30d>
                                      + Secure（仅 HTTPS_ENABLED=1 时）
```

- `Path=/api/v1/auth/`：只在 refresh / logout 两个请求上发送，其余接口不携带，缩小暴露面。
- `SameSite=Strict`：跨站请求不带，天然免疫 CSRF；本项目其余接口走 Bearer 头，本就不受 CSRF 影响。
- `Secure` 跟 `HTTPS_ENABLED` 联动，避免本地 http 调试时浏览器丢弃 cookie。

### 3.3 新增接口 `POST /auth/logout`

- 入参：无（从 cookie 或 body 的 `refresh` 取）。
- 行为：把该 refresh 拉黑（`BlacklistedToken`）+ 清 cookie（`Max-Age=0`）+ 返回 204。
- 幂等：没有 token / token 已失效 → 仍 204。
- 权限：`AllowAny`（令牌本身就是凭证）。

### 3.4 刷新轮换宽限（多标签防互踢）

现状 `BLACKLIST_AFTER_ROTATION=True`：两个标签页同时刷新，先到者把旧 refresh 拉黑，后到者 401 → 会话被清、用户被踢回登录页。

对策：轮换时把 `旧 jti → 新 refresh` 写入缓存 **`REFRESH_REUSE_GRACE`（默认 60 秒）**；命中「已拉黑但在宽限内」时，用缓存里的新 refresh 现签一个 access 返回（**不再轮换**）。超宽限的复用视为泄露重放 → 401。

### 3.5 Web 端改造

| 文件 | 改动 |
|---|---|
| `web/src/api/token-store.ts` | access/refresh 改模块内存变量；只保留 `userId` 在 localStorage |
| `web/src/api/http.ts` | 请求头加 `X-Client: web`；刷新请求 body 为空、靠 cookie；401 时先尝试刷新再判定失效 |
| `web/src/api/auth.ts` | `verify` 不再读 refresh；新增 `logout()` |
| `web/src/stores/session.ts` | `restore()` 先调 refresh 换 access 再 `/users/me`；`logout()` 调接口后清内存 |
| `web/src/api/types.ts` | `LoginResult.refresh` 改可选 |

## 4. App：安全存储（L8）

- 新增 `flutter_secure_storage`，抽 `TokenStorage` 接口（`read/write/delete`），生产实现走 Keystore/Keychain，测试注入内存假实现。
- `TokenStore` 构造器接受 `TokenStorage?`，默认安全实现。
- **一次性迁移**：首次读时若安全存储为空、而 `SharedPreferences` 里有旧键，则搬过去并删除旧键（避免线上用户被登出）。
- 迁移逻辑必须幂等：搬完即删，重复启动不会重复搬。

## 5. App：证书绑定（H1 剩余）

- 固定 **ISRG Root X1**（2035-06-04 到期）+ 备用 **ISRG Root X2**（ECDSA 根，2040 到期）；PEM 放 `app/assets/certs/`。
- `SecurityContext(withTrustedRoots: false)` 只信这两张根：任何其他 CA（含用户安装的企业根）签的证书握手失败。
- 覆盖面：**HTTPS（Dio）+ WSS（web_socket_channel 的 `customClient`）**，两者都从同一个 `PinnedTls` 工厂取 `HttpClient`。
- 开关：`--dart-define=CERT_PINNING=off|enforce`，默认 `kReleaseMode`（release 强制、debug 关闭，保证本地开发与 `flutter test` 不受影响）。
- **不固定叶子证书**：Let's Encrypt 90 天换证，固定叶子会让每次续期后全量 App 连不上。
- 发版前用 `app/tool/verify_pinning.dart` 对真实域名跑一次握手验证（脚本读同一份 PEM，证明固定链可用）。

## 6. 错误处理

| 场景 | 结果 |
|---|---|
| Web 刷新时 cookie 缺失/过期 | 401 + `40102`（会话失效），前端清内存回登录页 |
| 宽限内重复刷新 | 200，返回缓存的新 refresh 签出的 access |
| 超宽限重放 | 401（可能是令牌泄露） |
| 会话版本不一致（被顶号） | 保持现状：401 + `40101` |
| App 证书不匹配 | 握手失败 → `ApiException` 网络错误；不降级、不重试明文 |

## 7. 测试

**后端**（`accounts/tests.py`）
- Web 登录：响应无 `refresh`、有 `Set-Cookie`（`HttpOnly`、`Path`、`SameSite`）。
- App 登录：响应有 `refresh`、无 cookie。
- Cookie 刷新：轮换成功、响应只有 `access`、新 cookie 已下发。
- Body 刷新：行为不变（App 兼容）。
- 宽限：旧 refresh 120 秒内复用 → 200；超时 → 401。
- 注销：204、refresh 进黑名单、cookie 清空；无 token 也 204。
- 被顶号后刷新仍 40101。

**Web**（vitest）
- `tokenStore` 不再写 access/refresh 到 localStorage（读 localStorage 断言为空）。
- 刷新请求不带 body refresh、带 `X-Client` 头。
- 启动时无 access 但有 cookie → 调 refresh 成功进登录态。
- 退出调用 `/auth/logout`。

**App**（flutter test）
- `TokenStore` 走假 storage 的存取/清空。
- 迁移：旧 SharedPreferences 有值 → 搬到 secure storage 且旧键被删。
- `PinnedTls`：PEM 能构造 SecurityContext；`CERT_PINNING=off` 时返回默认客户端。

## 8. 上线与回滚

1. 先发后端（向后兼容：App 老版本仍走 body 刷新）。
2. 再发 Web（新 dist）。
3. App 发版前跑 `verify_pinning.dart`；release 包默认 enforce。
4. 回滚：Web 回滚 dist 即恢复 localStorage 逻辑（后端对 App 分支无影响）；App 只能靠版本回退（`MIN_APP_VERSION` 不放宽）。

## 9. 风险

| 风险 | 缓解 |
|---|---|
| 多标签并发刷新 | 120 秒宽限 + 缓存返回同一对新令牌 |
| Cookie 被浏览器策略拦（第三方 cookie 限制） | 同源部署，属第一方 cookie，不受影响 |
| 根证书固定后换 CA 导致全量不可用 | 同时内置 X1/X2；换 CA 前必须发新版；文档写明 |
| 迁移失败导致老用户登出 | 迁移失败时回退读 SharedPreferences，不抛错 |
