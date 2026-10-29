# chat_app 第二轮安全审计（2026-10-28）

> 审计日期：2026-10-28（第二轮）
> 报告版本：v1.0
> 审计对象：2026-10-27 首轮审计之后新增/变更的代码，以及首轮标注「部分修复 / 未关闭」的残留项
> 审计方式：只读静态代码审查（Django / imserver C++ / Web / App）+ 与首轮报告逐项对账
> 审计执行：AI 辅助静态审查；复核：待项目负责人
> 结论：首轮 P0/P1 的主体修复有效；本轮发现 **3 项高危残留 / 8 项中危 / 9 项低危**，
> 其中 H-1（IM HTTP 接口不校验会话版本）与 H-3（验证码明文日志）建议在公开测试前关闭。

---

## 1. 执行摘要

### 1.1 风险统计

| 等级 | 数量 | 说明 |
|---|---:|---|
| 严重 | 0 | 未发现「未授权即可接管账号」的新入口 |
| 高危 | 3 | 会话吊销不彻底、密钥漏配静默降级、验证码明文日志 |
| 中危 | 8 | 配额绕过、IM HTTP 无限流、后台 IP 白名单依赖部署、同步 ffmpeg 等 |
| 低危 | 9 | 并发竞态、探测面、开放重定向兜底、限流缺口等 |
| **合计** | **20** | |

### 1.2 与首轮的关系

| 首轮项 | 首轮结论 | 本轮复核 |
|---|---|---|
| H1 | 已修复（HTTPS + Cookie + 证书绑定） | **成立**；新增 `Origin` 校验缺口（L-4） |
| H2 | 未关闭（已接受） | **残留**：日志在 `SMS_DEV_MODE=0` 时仍打明文码（H-3） |
| H3 | 已修复（WS 侧 `sv` 校验） | **不完整**：`/im/api/*` 未校验 `sv`（H-1） |
| H5 | 部分（无机器审核） | 不变（外部依赖） |
| M5 | 部分（进程内加固） | 同步转码的可用性风险仍在（M-4） |
| M6 | 已修复 | 成立；imserver 侧密钥缺失仍静默降级（L-7） |
| M7 | 已修复 | **有绕过**：配额校验晚于落盘（M-1） |
| M8 | 未关闭（已接受） | **可低成本收敛**：`random` → `secrets`（H-3 同批） |
| L8 | 已修复 | 成立；安全存储失败时降级明文（已知取舍，建议在文档标注） |
| S1 | 未关闭（已接受） | 不变；但默认值 `SMS_DEV_MODE=1` 放大了漏配风险（L-9） |

---

## 2. 审计范围与方法

### 2.1 范围内

- 首轮之后新增的代码：令牌硬化（Cookie / 安全存储 / 证书绑定）、聊天语音、消息搜索、
  M7 存储配额与候选池、L9 imserver 入口防护、HTTPS/HSTS 部署文档。
- 首轮标注「部分 / 未关闭」的项：H2、H3、M5、M7、M9、L10。
- 重点链路：鉴权与刷新、媒体上传与签名、自建 IM（WS + HTTP + 内部 API）、ops 审核台、
  Web 令牌与渲染、App 令牌存储。

### 2.2 范围外

- 云控制台、安全组、操作系统、MySQL/Redis 网络暴露面。
- 短信商、内容安全、腾讯云 IM 的内部实现。
- 对生产环境的主动扫描与利用。
- 依赖 CVE（首轮 L6 已锁定版本；本轮不做 CVE 库比对）。

### 2.3 方法

- 逐接口核对鉴权、对象归属、入参校验、限流、错误处理与「响应路径无外部调用」纪律。
- 对新增的媒体链路（上传 → 落盘 → 签名 → nginx 验签）做端到端读代码核对。
- 对 imserver 的 WS 鉴权、HTTP API、内部 HMAC API、限流与缓存上限逐段核对。
- 所有结论均给出文件与行号；依赖部署配置的结论标注为「条件风险」。

### 2.4 限制

- 未连接生产服务器，生产 `.env`、nginx 实际配置以仓库文档为准。
- 未做动态渗透；并发类问题（配额竞态、举报重复）为代码推断，建议用测试固化。

---

## 3. 风险总表

| ID | 等级 | 标题 | 主要影响 | 状态 |
|---|---|---|---|---|
| H-1 | 高危 | `/im/api/*` 不校验会话版本 `sv` | 被顶下线的旧设备仍可读全部聊天历史/搜索，最长 24h | 已修复（2026-10-29） |
| H-2 | 高危 | 生产漏配 `SECRET_KEY` 时回落到公开常量 | JWT / 媒体签名 / 内部 HMAC 全部可伪造 | 已修复（2026-10-29） |
| H-3 | 高危 | 验证码明文日志 + 非 CSPRNG | 接真实短信商后日志即验证码；码可预测 | 已修复（2026-10-29） |
| M-1 | 中危 | 聊天图片配额校验晚于落盘 | 超配额仍写 5MB/次孤儿文件，磁盘放大 | 已修复（2026-10-29） |
| M-2 | 中危 | `/im/api/messages`、`/conversations` 无限流 | 单账号可高频打库 | 已修复（2026-10-29） |
| M-3 | 中危 | `client_ip()` 无条件信任 `X-Real-IP` | 后台 IP 白名单依赖 nginx 覆盖头，漏配即可绕过 | 已修复（2026-10-29） |
| M-4 | 中危 | 语音同步 ffmpeg（最长 30s/次 × 60 次/小时） | 2C2G 上单账号可占满 worker | 记录（异步化单独立项） |
| M-5 | 中危 | `user_sig` 响应路径同步调腾讯 REST | 第三方抖动拖垮登录后首个 IM 请求 | 记录 |
| M-6 | 中危 | OTP 通过标记无有效期 | 一次验证后 2 周内不再校验第二因子 | 已修复（2026-10-29） |
| M-7 | 中危 | `ops.photo_review` 用 `str.isdigit()` 过滤 id | Unicode 数字导致 500 | 已修复（2026-10-29） |
| M-8 | 中危 | WS `u<id>` 用 `stoull` 部分解析 | `u12abc` 被当作 uid 12 | 已修复（2026-10-29） |
| L-1 | 低危 | 新号并发登录 `get_or_create` 竞态 | 偶发 500 | 已修复（2026-10-29） |
| L-2 | 低危 | `PostReport` 无去重唯一约束 | 并发重复举报 | 已修复（2026-10-29） |
| L-3 | 低危 | 存在性差异可探测拉黑/封禁 | 隐私侧信道 | 记录 |
| L-4 | 低危 | Cookie 刷新端点无 Origin/CSRF 校验 | SameSite=Strict 兜底，子域场景可被 CSRF | 已修复（2026-10-29） |
| L-5 | 低危 | `/auth/logout` 无认证、无限流 | 可被用来刷黑名单表 | 已修复（2026-10-29） |
| L-6 | 低危 | `_safe_redirect` 在 `ALLOWED_HOSTS` 为空时放开任意主机 | 开放重定向 | 已修复（2026-10-29） |
| L-7 | 低危 | imserver 未配 `IM_MEDIA_SIGN_SECRET` 时静默不签名 | 媒体链接失效（非泄露） | 已修复（2026-10-29） |
| L-8 | 低危 | `match_list` 全量加载后内存分页 | 配对极多时内存放大 | 记录 |
| L-9 | 低危 | `DEBUG`/`SMS_DEV_MODE`/`HTTPS_ENABLED` 默认值偏开发 | 漏配时静默降级 | 记录 |

---

## 4. 详细发现

### 4.1 高危

#### H-1 `/im/api/*` 不校验会话版本 `sv`

**位置**：[imserver/src/net/http_api.cpp:235](../../imserver/src/net/http_api.cpp)（`authenticate`）、
[ws_server.cpp:375](../../imserver/src/net/ws_server.cpp)（WS 侧已校验，作为对照）。

**问题**：WS 握手会比对 token 里的 `sv` 与 `im_user.session_version`（H3 的修复），
但 HTTP API 的 `authenticate()` 只验签名、过期与封禁键，**完全没有比对 `sv`**。
nginx 把 `/im/api/` 直连到 9101，因此被顶下线的旧设备只要还握着旧 token，
就能继续调用 `/im/api/conversations`、`/im/api/messages`、`/im/api/search`
读取全部聊天历史与搜索结果，直到 token 过期（`IM_SELF_TOKEN_TTL` 默认 86400 秒）。

**影响**：单设备登录与「踢下线即吊销」在 HTTP 面失效；手机丢失/转卖后的旧设备仍可翻历史。

**验收**：用旧 `sv` 的 token 请求 `/im/api/messages` 返回 401/`40101`；新 token 正常。

#### H-2 生产漏配 `SECRET_KEY` 时回落到公开常量

**位置**：[chatapp/config/settings.py:33](../../chatapp/config/settings.py)。

**问题**：`SECRET_KEY = os.getenv("SECRET_KEY", "dev-insecure-change-me")`。
`DEBUG=0` 时没有启动断言。若生产 `.env` 漏配（或复制了模板却未改），
JWT（HS256）可用公开常量离线伪造任意用户令牌；`sms_codes.digest()` 的 HMAC 密钥、
Django session 签名同样失效。

**影响**：完全账号接管（与 S1 同级），且不会有任何报错。

**验收**：`DEBUG=0` 且 `SECRET_KEY` 为默认值时 `manage.py check` / 启动直接抛
`ImproperlyConfigured`。

#### H-3 验证码明文日志 + 非 CSPRNG

**位置**：[chatapp/accounts/services.py:44-46](../../chatapp/accounts/services.py)、
[chatapp/notifications/backends.py:19-26](../../chatapp/notifications/backends.py)。

**问题**：
1. `issue_code()` **无条件**执行 `logger.info("[开发模式] 验证码 phone=%s code=%s", ...)`，
   即使 `SMS_DEV_MODE=0`（接真实短信商后）也照打。首轮 H2 的「删验证码日志」并未真正落地。
2. `ConsoleSmsBackend.send_code()` 同样无条件打码，且 `get_sms_backend()` 在
   `SMS_DEV_MODE=0` 时仍返回控制台实现（既不发送也不报错）。
3. 验证码用 `random.randint` 生成，不是 CSPRNG（首轮 M8）。

**影响**：接入真实短信商后，任何能读日志的人（运维、日志采集、云日志服务）都能拿到
任意手机号的验证码并登录；`random` 的输出在拿到同进程其它随机数时可被预测。

**验收**：`SMS_DEV_MODE=0` 时日志不出现 6 位码；验证码由 `secrets` 生成。

### 4.2 中危

#### M-1 聊天图片配额校验晚于落盘

**位置**：[chatapp/im/views.py:141-154](../../chatapp/im/views.py)。

**问题**：`chat_image.file.save(..., save=False)` 会**立即**把文件写进存储
（`save=False` 只跳过模型保存），随后才调用 `storage.ensure_quota()`。
超配额时抛 413，但原图已经落盘，数据库没有对应行 → 孤儿文件。
30 次/小时 × 5MB = 150MB/小时，清理任务每天才跑一次。

**影响**：配额对磁盘实际占用失效；恶意账号可在清理窗口内持续放大磁盘。

**验收**：超配额上传返回 413 后，`media/chat/` 下不新增文件。

#### M-2 `/im/api/messages`、`/im/api/conversations` 无限流

**位置**：[http_api.cpp:466-551](../../imserver/src/net/http_api.cpp)。

**问题**：只有 `/im/api/search` 有按账号令牌桶（60/min、burst 20）；
会话列表与历史消息没有限流。两者每次都打 MySQL（`limit` 最大 100/200），
一个账号即可持续制造数据库负载。

**验收**：同一账号高频请求被 429/`42901`。

#### M-3 `client_ip()` 无条件信任 `X-Real-IP`

**位置**：[chatapp/config/net.py:22-27](../../chatapp/config/net.py)；
使用方：[ops/middleware.py:50-52](../../chatapp/ops/middleware.py)（IP 白名单）、
[accounts/backends.py:40](../../chatapp/accounts/backends.py)（登录锁定）。

**问题**：只要请求头里带 `X-Real-IP`，就无条件采信，不检查直连对端是否为可信代理。
当前安全性完全依赖 nginx 的 `proxy_set_header X-Real-IP $remote_addr;`
——而 `docs/ops/nginx-security.conf` 的 `/admin/`、`/ops/` 两个 location 依赖
`include .../proxy/<DOMAIN>.conf`，**没有显式写这一行**。若该 include 未覆盖此头
（或未来有人删掉 include），后台 IP 白名单即可用伪造头绕过。

**验收**：直连（非回环）请求伪造 `X-Real-IP` 不再改变白名单/锁定 key；
nginx 片段对 `/ops/`、`/admin/` 显式覆盖 `X-Real-IP` 与 `X-Forwarded-For`。

#### M-4 语音同步 ffmpeg 的可用性风险（记录）

**位置**：[chatapp/im/voice.py:86-107](../../chatapp/im/voice.py)、
[chatapp/im/views.py:189](../../chatapp/im/views.py)。

**问题**：每个语音上传在请求线程里同步跑 ffprobe + ffmpeg（各 15s 超时），
限流 60 次/小时/账号。2C2G 上多账号并发即可占满 worker/CPU。
首轮 M5 已做进程内加固（协议白名单、rlimit、最小环境），但**异步化与容器隔离未做**。
本轮不改代码，保留为上线前的容量风险。

#### M-5 `user_sig` 响应路径同步调腾讯 REST（记录）

**位置**：[chatapp/im/views.py:69-77](../../chatapp/im/views.py)。

**问题**：`ensure_account()` 与 `kick_user()` 在请求线程里同步调用
（腾讯分支 5s 超时）。这违反项目「响应路径禁止第三方调用」的纪律；
腾讯侧抖动会直接拖慢登录后第一次取 IM 凭证。自建分支是 localhost，风险小。

#### M-6 OTP 通过标记无有效期

**位置**：[chatapp/ops/otp.py:102](../../chatapp/ops/otp.py)、
[chatapp/ops/middleware.py:58-60](../../chatapp/ops/middleware.py)。

**问题**：`request.session["otp_verified"] = True` 后不再过期，直到 session 失效
（默认 2 周）。共用电脑或 session 被窃时，第二因子在两周内不再生效。
另外 TOTP 校验没有「同一码不可重复使用」的记录（±1 步窗口内可重放）。

**验收**：超过 `OPS_OTP_TTL`（默认 12 小时）后重新要求验证码。

#### M-7 `ops.photo_review` 的 id 过滤会 500

**位置**：[chatapp/ops/views.py:288-290](../../chatapp/ops/views.py)。

**问题**：用 `value.isdigit()` 过滤，但 `"²".isdigit()` 为真而 `int("²")` 抛
`ValueError`；`pk__in` 求值时 → 500。属于首轮 M10「非法参数 500」的同类残留。

**验收**：`ids=²` 返回 200（忽略非法 id），不再 500。

#### M-8 WS `u<id>` 部分解析

**位置**：[imserver/src/net/ws_server.cpp:412-416](../../imserver/src/net/ws_server.cpp)。

**问题**：`std::stoull(to.substr(1))` 对 `u12abc` 会成功返回 12（只解析前缀），
与 HTTP 侧 `parse_peer` 的严格行为不一致。目前受「必须配对 + 目标存在」兜底，
但会让日志/审计里的接收方与客户端意图不一致。

**验收**：`to="u12abc"` 返回 42201。

### 4.3 低危

| ID | 位置 | 问题 | 处理 |
|---|---|---|---|
| L-1 | [accounts/views.py:162](../../chatapp/accounts/views.py) | 全新手机号并发登录时 `get_or_create` 可能 `IntegrityError` → 500 | 捕获后回查 |
| L-2 | [feed/views.py:285](../../chatapp/feed/views.py) | `PostReport` 无 `dedupe_key` 唯一约束，并发可重复 | 加唯一约束 + 迁移 |
| L-3 | [users/views.py:108](../../chatapp/users/views.py)、`presence` | 404/省略可用于探测「是否被对方拉黑/封禁」 | 记录（产品取舍） |
| L-4 | [accounts/views.py:273](../../chatapp/accounts/views.py) | Cookie 刷新/注销端点不校验 `Origin` | 加同源校验 |
| L-5 | [accounts/views.py:323](../../chatapp/accounts/views.py) | `/auth/logout` 无认证、无限流，可反复写黑名单表 | 加 IP 限流 |
| L-6 | [ops/otp.py:126-129](../../chatapp/ops/otp.py) | `ALLOWED_HOSTS` 为空时 `url_has_allowed_host_and_scheme` 放开任意主机 | 空列表时只允许站内相对路径 |
| L-7 | [imserver/src/config.cpp:158-170](../../imserver/src/config.cpp) | 未配 `IM_MEDIA_SIGN_SECRET` 时静默降级为「不签名」 | 启动告警/报错 |
| L-8 | [discovery/views.py:184-187](../../chatapp/discovery/views.py) | 配对列表全量加载后内存分页 | 记录（数据量小） |
| L-9 | [config/settings.py:36/285/428](../../chatapp/config/settings.py) | `DEBUG=1`、`SMS_DEV_MODE=1`、`HTTPS_ENABLED=0` 为默认值 | 文档标注 + H-2 断言 |

---

## 5. 修复批次

| 批次 | 内容 | 项 | 状态 |
|---|---|---|---|
| A | 会话吊销与密钥/验证码 | H-1、H-2、H-3 | [x] |
| B | 配额、限流与输入解析 | M-1、M-2、M-3、M-6、M-7、M-8 | [x] |
| C | 并发与边角 | L-1、L-2、L-4、L-5、L-6、L-7 | [x] |
| D | 回归与文档 | 后端全量 + imserver + Web/App 检查 | [x] |

**本轮不做**（记录为已知风险）：M-4（语音异步化）、M-5（腾讯调用移出响应路径）、
L-3（探测面）、L-8（配对分页）、L-9（默认值，除 H-2 断言外）。
这些要么需要架构改动，要么属于产品取舍，建议单独立项。

### 5.1 修复证据（2026-10-29）

| 项 | 改动位置 | 验证 |
|---|---|---|
| H-1 | `imserver/src/net/http_api.cpp::authenticate` + `auth/token.cpp::session_version_matches` | `tests/integration/test_internal.py`：旧 `sv` 请求 `/im/api/conversations` → 401/40101，新 `sv` → 200 |
| H-2 | `chatapp/config/settings.py::assert_production_secret_key` | `config/tests.py::SecretKeyGuardTests` |
| H-3 | `accounts/services.issue_code`、`notifications/backends.py` | `accounts/tests.py` 与 `notifications/tests.py`（非开发模式日志无 6 位码） |
| M-1 | `im/views.upload_image` 配额前移 | `im/tests.py::test_quota_exceeded_rejects_upload` 断言媒体目录为空 |
| M-2 | `imserver/src/util/ratelimit.*::RateTable` | `tests/integration/test_internal.py` 连续 60 次请求出现 429/42901 |
| M-3 | `config/net.py`、`config/settings.TRUSTED_PROXY_IPS`、nginx 片段 | `config/tests.py::ClientIpTests` |
| M-6 | `ops/otp.py::mark_verified/is_verified` + `OPS_OTP_TTL` | `ops/tests.py::StaffOtpTests::test_expired_verification_is_rejected` |
| M-7 | `ops/views.photo_review` 改 `int()` 解析 | `ops/tests.py::test_unicode_digit_ids_are_dropped` |
| M-8 | `imserver/src/net/ws_server.cpp::parse_uid` | `tests/integration/test_internal.py`：`u12abc` → 42201 |
| L-1 | `accounts/views.sms_verify` 捕获 `IntegrityError` | 后端全量回归 |
| L-2 | `feed.PostReport.dedupe_key` + 迁移 `0004` | `feed/tests.py::PostReportTests` |
| L-4/L-5 | `accounts/cookies.same_origin`、`LogoutThrottle` | `accounts/tests.py::WebCookieAuthTests` |
| L-6 | `ops/otp._safe_redirect` | `ops/tests.py::OpsSafeRedirectTests` |
| L-7 | `imserver/src/config.cpp` 启动告警 `media_sign_disabled` | imserver 启动日志 |

**回归结果**：后端 `Ran 611 tests ... OK`；imserver unit `40/40`、db `18/18`、HTTP 集成 + `im_e2e` 全过；
Web `vue-tsc` / `eslint --max-warnings 0` / `vitest 371 passed`；App `flutter analyze` 零告警。

---

## 6. 回归命令

```bash
# 后端（需 Redis；本机 TEST_REDIS_PORT=16379）
cd chatapp && python manage.py test

# imserver
docker compose -f imserver/docker-compose.test.yml run --rm test bash /src/scripts/test_http.sh
docker compose -f imserver/docker-compose.test.yml run --rm test bash /src/scripts/test_integration.sh

# Web / App
cd web && npm run type-check && npm run lint && npm run test:run
cd app && ../flutter/bin/flutter.bat analyze
```

---

**报告结束（修复进展见 §5 勾选与 `docs/superpowers/plans/2026-10-28-security-round2.md`）**
