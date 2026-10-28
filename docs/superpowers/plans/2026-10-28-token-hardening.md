# 令牌硬化实施计划（2026-10-28）

> 设计：[2026-10-28-token-hardening-design.md](../specs/2026-10-28-token-hardening-design.md)
> 范围：审计 H1 剩余项（Web token / App 证书绑定）+ L8（App 令牌明文）。
> 执行方式：`executing-plans` 内联逐任务完成，不派子 agent；每任务全绿再进下一个。
> 验收基线：后端 `python manage.py test`（需 Redis）、Web `npm run type-check && npm run lint && npm run test:run`、App `flutter analyze && flutter test`。

## T1. 后端常量与 Cookie 工具

- [x] `config/settings.py`：`REFRESH_COOKIE_NAME`（默认 `chatapp_rt`）、`REFRESH_COOKIE_PATH`（`/api/v1/auth/`）、`REFRESH_REUSE_GRACE`（默认 60 秒）。
- [x] `accounts/cookies.py`：`set_refresh_cookie` / `clear_refresh_cookie` / `wants_cookie`；`Secure` 跟 `HTTPS_ENABLED` 联动，`HttpOnly`、`SameSite=Strict`、`Max-Age` 跟 refresh 寿命一致。

## T2. 登录分支（sms_verify）

- [x] Web（`X-Client: web`）：下发 Cookie，响应去掉 `refresh`；App：行为不变。

## T3. 刷新（token/refresh）

- [x] 取 token：body 优先（App 兼容），否则 Cookie；空 body 不触发 `ParseError`（`_body_refresh`）。
- [x] 会话版本校验保持不变。
- [x] 轮换后把 `旧 jti → 新 refresh` 写缓存（`REFRESH_REUSE_GRACE`）。
- [x] 已拉黑但宽限内：用缓存 refresh 现签 access，不再轮换；超宽限 401。
- [x] Web 分支：下发新 Cookie、响应只给 `access`；App 分支不变。

## T4. 注销（POST /auth/logout，新接口）

- [x] 拉黑 refresh（幂等）、清 Cookie、204；无 token 也 204。
- [x] `accounts/urls.py` 挂载；`docs/api/auth.md` 同步（`ApiDocsCoverageTests` 双向门禁）。

## T5. 后端测试

- [x] Web/App 登录分支、Cookie 属性（`HttpOnly`/`SameSite`/`Path`）。
- [x] Cookie 刷新轮换 + 新 Cookie；body 刷新兼容。
- [x] 宽限内复用 200、超宽限 401、宽限不能复活被顶号会话（40101）。
- [x] 注销 204 + 黑名单 + Cookie 清空；重复注销 204。

## T6. Web 端

- [x] `token-store.ts`：access/refresh 内存化，只持久化 `userId`；加载时清掉旧版本遗留键。
- [x] `http.ts`：`X-Client: web`；刷新请求体 `{}`；401 分支适配。
- [x] `auth.ts`：`verify` 不读 refresh；新增 `logout()`。
- [x] `session.ts`：`restore()` 靠拦截器用 Cookie 换 access；`logout()` 调接口后再清内存。
- [x] vitest：localStorage 无令牌、刷新请求形状、启动恢复、退出调用、注销后清 Cookie。

## T7. App 安全存储（L8）

- [x] `flutter_secure_storage` 依赖 + `TokenStorage` 接口 + `SecureTokenStorage`。
- [x] `AndroidManifest.xml` 关掉 `allowBackup` / `fullBackupContent`（云备份与设备迁移不再带走本地数据）。
- [x] `TokenStore` 注入 storage；SharedPreferences → 安全存储一次性迁移（失败降级，不抛错）。
- [x] 测试：假 storage 存取/清空、迁移幂等、旧键被删、损坏时降级。
- [x] `test/flutter_test_config.dart` 给安全存储装内存 mock（组件测试里未注册的平台通道会永久挂起，表现成 `pumpAndSettle timed out`）。

## T8. App 证书绑定（H1 剩余）

- [x] `app/assets/certs/isrg-root-x1.pem`、`isrg-root-x2.pem`（letsencrypt.org 官方源，SHA-256 指纹已核对）。
- [x] `lib/core/pinned_tls_core.dart`（纯 Dart）+ `lib/core/pinned_tls.dart`（Flutter 封装）。
- [x] API Dio、IM HTTP Dio、WSS 客户端都接上；`--dart-define=CERT_PINNING=off|enforce`，默认 `kReleaseMode`。
- [x] `tool/verify_pinning.dart` 对真实域名握手验证：`HTTP 200`，只信 X1+X2 时通过。
- [x] 测试：PEM 可构造 context、空列表报错、未启用时走默认适配器。

## T9. 文档与回归

- [x] `docs/api/auth.md`、`docs/pitfalls/backend.md`、`docs/pitfalls/web.md`。
- [x] 审计报告 §10：H1、L8 改为「已修复」并附证据。
- [x] 后端全量、Web 全量（type-check/lint/vitest）、App analyze+test 全绿。

---

## 执行记录（2026-10-28）

| 项 | 结果 |
|---|---|
| 后端 | `python manage.py test`：**573 项全绿**（563 → +10：Cookie 分支/宽限/注销） |
| Web | `type-check` 零错误、`lint --max-warnings 0` 零告警、vitest **371 项全绿** |
| App | `flutter analyze` 无问题、`flutter test` **412 项全绿** |
| 证书绑定 | `dart run tool/verify_pinning.dart` → `HTTP 200`（仅信 ISRG Root X1 + X2） |

### 上线顺序与注意

1. 先发后端（App 老版本仍走请求体刷新，向后兼容），再发 Web `dist`，最后发 App。
2. **Web 老用户会掉线一次**：旧版本写在 localStorage 的令牌被直接删除，需要重新登录（没有安全通道把旧 refresh 换成 Cookie 会话）。
3. App 发版前必跑 `dart run tool/verify_pinning.dart`；release 包默认 `enforce`，可用 `--dart-define=CERT_PINNING=off` 应急关闭。
4. 换 CA 之前必须先发新版（当前只信 Let's Encrypt 的两张根）；`MIN_APP_VERSION` 不要为「回滚」而放宽。
5. `REFRESH_REUSE_GRACE` 可配；若把多标签并发做成了前端串行，可调小到 10 秒。
