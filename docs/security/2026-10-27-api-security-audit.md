# chat_app 接口安全审计报告

> 审计日期：2026-10-27  
> 报告版本：v1.0  
> 审计对象：Django/DRF 后端、`/ops` 审核台、自建 `imserver`、Web/App 鉴权与令牌存储  
> 审计方式：只读静态代码审查 + 部署配置核对 + 本地只读验证  
> 审计执行：AI 辅助静态审查；复核：待项目负责人  
> 结论：**当前不具备直接面向真实用户上线的安全条件**；P0 的 3 项必须在上线前关闭。

---

## 1. 执行摘要

### 1.1 风险统计

| 等级 | 数量 | 说明 |
|---|---:|---|
| 严重 | 1 | 未授权即可接管任意手机号账号 |
| 高危 | 6 | 可导致大规模账号/数据泄露、持久化控制或合规阻断 |
| 中危 | 12 | 需要一定条件，或造成局部数据/可用性/隐私影响 |
| 低危/加固 | 10 | 纵深防御、信息泄露与最佳实践 |
| **合计** | **29** | |

### 1.2 最高优先级

1. **S1（严重）**：生产 `SMS_DEV_MODE=1`，验证码固定 `123456`。知道手机号即可登录、读聊天、发消息、注销账号。
2. **H1（高危）**：全站 HTTP；Web 的 access/refresh token 存在 `localStorage`；`/admin/`、`/ops/` 密码明文传输。
3. **H2（高危）**：验证码明文写日志；且短信后端始终是 `ConsoleSmsBackend`，`SMS_DEV_MODE=0` 时既不发短信也继续写日志。
4. **H3（高危）**：自建 IM token 不绑定 `session_version`，踢下线不吊销 token；旧设备/被盗 token 可在 24 小时内重连收消息。
5. **H4（高危）**：任意登录用户可向任意 uid 发 IM 消息，无配对/关系校验，可绕过“配对后才能聊天”的产品规则。

### 1.3 上线建议

| 场景 | 建议 |
|---|---|
| 仅测试号、无真实用户数据 | 可继续封闭测试，但应尽快修 S1、H2；测试号也不要使用真实手机号 |
| 小范围真实用户内测 | 必须完成 P0 + P1；S1、H1、H2 不允许带病上线 |
| 公开上线/应用商店 | 必须完成 P0 + P1 + P2 中的隐私与 DoS 项，并完成内容审核接入 |

> 说明：本报告中的“生产配置”依据仓库内最新部署记录与 `CLAUDE.md` 判断；如果服务器 `.env` 已调整，请以实际配置为准，并同步更新本报告结论。

---

## 2. 审计范围与方法

### 2.1 范围内

- Django/DRF：`chatapp/accounts`、`users`、`discovery`、`im`、`moderation`、`feed`、`feedback`、`ops`、`appconfig`、`notifications`、`config`。
- 自建 IM：`imserver/src` 的 WS 鉴权、消息发送、HTTP API、媒体签名、MySQL/Redis 访问。
- Web：`web/src/api/http.ts`、`web/src/api/token-store.ts`、聊天搜索渲染。
- App：`app/lib/core/token_store.dart`、登录页、API 基址。
- 部署配置：`docs/superpowers/specs`、`docs/superpowers/plans`、`docs/ops` 中与生产相关的 nginx、`.env`、IM 部署记录。

### 2.2 范围外

- 云控制台、安全组、操作系统、SSH、MySQL/Redis 网络暴露面。
- 腾讯云 IM、短信商、内容安全 SDK 的内部实现。
- 对生产环境的主动扫描、爆破、漏洞利用。
- 代码质量、性能、UI/UX 等非安全问题（除非直接影响安全）。

### 2.3 方法

- 逐接口核对鉴权、权限、对象归属、入参校验、限流、错误处理。
- 对上传、媒体、IM、后台等高风险链路做重点审查。
- 本地运行 `python manage.py check --deploy`（只读）。
- 本地做两个内存级验证：Django 5.2 `ImageField` 扩展名校验、媒体签名空密钥行为。
- 所有结论均给出代码/配置证据；无法确认的生产项标注为“条件风险”。

### 2.4 限制

- 未连接生产服务器，未读取生产 `.env`；生产结论依赖仓库内文档。
- 未做动态渗透；M3、M5 等 DoS/解析器风险建议在隔离环境用受控样本复现。
- 未审计第三方依赖的已知 CVE 细节；仅给出依赖锁定建议。

---

## 3. 风险总表

| ID | 等级 | 标题 | 主要影响面 | 状态 |
|---|---|---|---|---|
| S1 | 严重 | 生产验证码固定 `123456` | 账号接管、聊天/照片/注销 | 阻断上线 |
| H1 | 高危 | 全站 HTTP + Web token 存 localStorage | 会话/后台密码泄露 | 阻断上线 |
| H2 | 高危 | 验证码明文日志 + Console 短信后端 | 任意账号登录 | 阻断上线 |
| H3 | 高危 | IM token 不绑定会话、踢下线不吊销 | 旧设备/被盗 token 重连 | 阻断 IM 全量 |
| H4 | 高危 | IM 任意 uid 可发消息 | 骚扰、绕过配对、DB/内存膨胀 | 阻断 IM 全量 |
| H5 | 高危 | `AUTO_APPROVE=1` + 无机器审核 | 违规内容分发、合规 | 阻断公开上线 |
| H6 | 高危 | Ops/Admin 无登录限流/2FA | 后台爆破、数据泄露 | 阻断生产运维 |
| M1 | 中危 | XFF 伪造绕过 IP 限流 | 短信轰炸、验证码爆破 | 尽快 |
| M2 | 中危 | 用户/资料枚举与抓取 | 隐私、骚扰目标列表 | 尽快 |
| M3 | 中危 | 图片解压炸弹/像素上限缺失 | 2C2G OOM、worker 崩溃 | 尽快 |
| M4 | 中危 | EXIF/GPS 未剥离 | 位置隐私泄露 | 尽快 |
| M5 | 中危 | ffmpeg 处理不可信音频 | SSRF/本地文件/解析器 RCE/CPU | 尽快 |
| M6 | 中危 | 媒体签名 URL 可转发、空密钥 fail-open | 私聊媒体泄露 | 尽快 |
| M7 | 中危 | 高开销接口无限流 + 磁盘配额缺失 | CPU/磁盘/成本 DoS | 尽快 |
| M8 | 中危 | 短信锁定 DoS + 验证码非 CSPRNG | 定向锁号、验证码预测 | 尽快 |
| M9 | 中危 | Ops 可浏览全部私聊媒体；资料图公开 | 内部人隐私、抓取 | 尽快 |
| M10 | 中危 | `limit=-1` 等非法参数 500 | 错误契约、低成本 DoS | 迭代 |
| M11 | 中危 | `swipe` 未校验拉黑关系 | 拉黑绕过、骚扰 | 迭代 |
| M12 | 中危 | 会话版本竞态；举报重复 | 单设备绕过、运营噪音 | 迭代 |
| L1 | 低危 | `/health`、`/readyz` 公开 | 信息泄露、低成本探测 | 加固 |
| L2 | 低危 | `X-Request-Id` 客户端可控 | 日志注入/终端转义 | 加固 |
| L3 | 低危 | Host 头影响绝对 URL | URL 污染 | 加固 |
| L4 | 低危 | CORS 允许 localhost 任意端口 | 本地页面跨域 | 加固 |
| L5 | 低危 | 图片格式面过大、未统一转码 | 元数据/解码攻击面 | 加固 |
| L6 | 低危 | 依赖未锁定 | 供应链/可复现性 | 加固 |
| L7 | 低危 | Web 静态页安全头缺失 | 点击劫持/纵深防御 | 加固 |
| L8 | 低危 | App 令牌存 SharedPreferences | 本地明文令牌 | 加固 |
| L9 | 低危 | imserver 信任头/无界缓存/探针 | 限流绕过、内存增长 | 加固 |
| L10 | 低危 | JWT 过期判断、短信重放窗口等细节 | 1 秒/60 秒边界 | 加固 |

---

## 4. 详细发现

### 4.1 严重

#### S1. 生产短信验证码固定为 `123456`，可登录任意手机号

- **等级**：严重（Critical）
- **位置**：`chatapp/accounts/services.py`、`chatapp/accounts/views.py`、`chatapp/config/settings.py`
- **证据**：
  - `SMS_DEV_MODE` 默认值为 `1`：[settings.py:245](../../chatapp/config/settings.py#L245)
  - 生产部署配置写 `SMS_DEV_MODE=1`：[部署设计:79](../superpowers/specs/2026-09-18-m4-deploy-runthrough-design.md#L79)
  - 部署记录确认生产 `.env` 没写该键，靠默认值 1，并列为“上线阻断项”：[部署计划:92-94](../superpowers/plans/2026-10-20-self-hosted-im-rollout.md#L92-L94)
  - 固定码逻辑：[accounts/services.py:42-46](../../chatapp/accounts/services.py#L42-L46)
  - 校验成功即签发 JWT，号码不存在自动建号：[accounts/views.py:147-177](../../chatapp/accounts/views.py#L147-L177)
- **攻击路径**：
  1. 攻击者知道/猜到目标手机号；
  2. `POST /api/v1/auth/sms/verify`，body `{"phone":"<目标手机号>","code":"123456"}`；
  3. 获得目标账号 `access`/`refresh`；
  4. `GET /api/v1/users/me` 读取资料（含手机号）；
  5. `POST /api/v1/im/user_sig` 取得 IM 凭证，读聊天、冒充发消息；
  6. `DELETE /api/v1/users/me`，body 带手机号，直接注销目标账号。
- **影响**：
  - 任意账号接管；聊天记录、照片、配对关系全部可读；
  - 可冒充受害者发送消息、实施诈骗；
  - 可注销受害者账号，造成不可恢复的数据丢失；
  - 结合 M2，可批量测试手机号是否注册。
- **修复方案**：
  1. 接入真实短信商（阿里云/腾讯云），实现 `notifications/backends.py::RealSmsBackend`；`SMS_DEV_MODE=0` 时使用真实后端。
  2. `settings.py` 增加启动断言：`if not DEBUG and SMS_DEV_MODE: raise ImproperlyConfigured(...)`；`SMS_DEV_MODE=0` 但没有真实后端时同样拒绝启动（fail-closed）。
  3. 删除固定码兜底：验证码统一用 `secrets.randbelow(1_000_000)` 生成，格式化为 6 位。
  4. 删除验证码明文日志（见 H2）。
  5. 上线后审计 `sms/verify` 成功记录：同一 IP 多手机号、同一手机号多 IP、异常时段登录。
  6. 若怀疑已被利用：轮换 `SECRET_KEY`（使所有 JWT 失效），强制所有用户重新登录。
- **验收标准**：
  - 生产 `SMS_DEV_MODE=0`，且真实短信可收到；
  - 用任意手机号 + `123456` 登录返回 4xx；
  - 日志中搜索不到 6 位验证码；
  - `manage.py check --deploy` 不再出现与开发开关相关的告警。
- **回归测试**：
  - 新增测试：`SMS_DEV_MODE=0` 时固定码不可登录；
  - 新增测试：未配置真实短信后端时启动失败；
  - 手工：真实手机号收码、登录、刷新 token。

---

### 4.2 高危

#### H1. 全站 HTTP，Web 的 JWT 存在 localStorage，管理后台密码明文传输

- **等级**：高危（High）
- **位置**：部署 nginx、`web/src/api/token-store.ts`、`chatapp/config/settings.py`
- **证据**：
  - 测试期部署形态为 `http://<SERVER_IP>`：[部署设计:10](../superpowers/specs/2026-09-18-m4-deploy-runthrough-design.md#L10)
  - Web 把 access/refresh token 存 `localStorage`：[token-store.ts:1-37](../../web/src/api/token-store.ts#L1-L37)
  - `check --deploy` 报 4 项：`SECURE_HSTS_SECONDS`、`SECURE_SSL_REDIRECT`、`SESSION_COOKIE_SECURE`、`CSRF_COOKIE_SECURE` 均未设置
  - `/admin/`、`/ops/` 走同一 HTTP 站点：[urls.py:14](../../chatapp/config/urls.py#L14)、[ops/urls.py:18-22](../../chatapp/ops/urls.py#L18-L22)
- **影响**：
  - 同一 Wi-Fi、路由器、运营商链路、代理可嗅探 Bearer token、refresh token、后台密码、session cookie；
  - refresh token 有效期 30 天，泄露后长期有效；
  - 一旦出现 XSS 或第三方脚本，localStorage 中的 token 可被直接读走；
  - 后台被劫持后可封禁/解封、删动态、查看举报与私聊媒体。
- **修复方案**：
  1. 域名/备案完成后，nginx 上 443 证书，80 强制 301 到 443。
  2. Django 配置：
     ```python
     SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
     SECURE_SSL_REDIRECT = True
     SESSION_COOKIE_SECURE = True
     CSRF_COOKIE_SECURE = True
     SECURE_HSTS_SECONDS = 3600          # 先 1 小时，确认无混合内容后升到 31536000
     SECURE_HSTS_INCLUDE_SUBDOMAINS = True
     SECURE_HSTS_PRELOAD = False         # 确认稳定后再开
     CSRF_TRUSTED_ORIGINS = ["https://<正式域名>"]
     ```
  3. nginx 传递 `X-Forwarded-Proto $scheme`，并确保外部不能伪造该头（只信任本机 nginx）。
  4. 后台/审核台加 IP 白名单或 VPN；不要把 `/admin/`、`/ops/` 暴露给公网。
  5. Web 令牌方案二选一：
     - 推荐：BFF + HttpOnly/Secure/SameSite cookie，浏览器 JS 拿不到 token；
     - 或保留 localStorage，但必须加严格 CSP、禁止第三方脚本、缩短 refresh 生命周期、增加 token 绑定（设备指纹/UA/IP 变更告警）。
  6. App 增加证书绑定（certificate pinning），至少对 API 域名。
- **验收标准**：
  - `http://` 访问 301 到 `https://`；
  - 响应头有 HSTS、Secure cookie；
  - `check --deploy` 无 W004/W008/W012/W016；
  - 用抓包工具确认登录/刷新/后台登录均为 TLS。
- **回归测试**：
  - Web 登录、刷新、聊天、图片/语音全链路；
  - App 冷启动、登录、IM WS（wss）；
  - 后台登录、HTMX 操作。

#### H2. 验证码明文写日志，且短信后端始终是 Console

- **等级**：高危（High）
- **位置**：`chatapp/accounts/services.py`、`chatapp/notifications/backends.py`
- **证据**：
  - 无论 `SMS_DEV_MODE` 是否为 0，都会执行 `logger.info("...验证码...code=%s")`：[accounts/services.py:46](../../chatapp/accounts/services.py#L46)
  - `get_sms_backend()` 两个分支都返回 `ConsoleSmsBackend`：[notifications/backends.py:36-38](../../chatapp/notifications/backends.py#L36-L38)
  - 该后端也把验证码打进日志：[notifications/backends.py:19-26](../../chatapp/notifications/backends.py#L19-L26)
- **影响**：
  - 任何能读日志、日志备份、日志平台或运维账号的人，都能用日志中的验证码登录任意账号；
  - `SMS_DEV_MODE=0` 时仍然写日志，只是不真正发短信，用户收不到码，属于“既泄露又不服务”；
  - 日志可能被同步到 ELK/云日志/备份，扩大暴露面。
- **修复方案**：
  1. 删除 `accounts/services.py` 中打印 `code` 的日志；只记录脱敏手机号（如 `138****1234`）和结果。
  2. `ConsoleSmsBackend` 只在 `SMS_DEV_MODE=1` 时启用；生产走真实后端。
  3. 生产启动时若 `SMS_DEV_MODE=0` 且没有真实后端，直接 `ImproperlyConfigured`，不要静默使用 Console。
  4. 清理历史日志/备份中的验证码；限制日志目录权限与保留期。
  5. 增加日志脱敏测试：断言日志中不出现 6 位连续数字验证码。
- **验收标准**：
  - 生产日志搜索 `code=` 无明文；
  - `SMS_DEV_MODE=0` 时真实短信可达；
  - 日志中手机号已脱敏。
- **回归测试**：
  - 发码、登录、错误码、锁定四条路径的日志检查。

#### H3. 自建 IM token 不绑定 `session_version`，踢下线不吊销 token

- **等级**：高危（High）
- **位置**：`chatapp/im/token.py`、`imserver/src/net/ws_server.cpp`、`imserver/src/service/session_registry.cpp`
- **证据**：
  - IM token 只有 `sub/uid/iat/exp/jti`，没有会话版本：[im/token.py:10-31](../../chatapp/im/token.py#L10-L31)
  - WS 认证只校验 token 和封禁键：[ws_server.cpp:307-349](../../imserver/src/net/ws_server.cpp#L307-L349)
  - `kick()` 只关闭当前 socket：[ws_server.cpp:591-605](../../imserver/src/net/ws_server.cpp#L591-L605)
  - 新会话注册会踢旧会话，但旧 token 仍可重连：[session_registry.cpp:21-35](../../imserver/src/service/session_registry.cpp#L21-L35)
- **影响**：
  - 被顶下线的旧设备、被盗 token 在 24 小时内可反复重连；
  - 攻击者可反过来把受害者的新会话踢掉，形成“互踢”；
  - “单设备登录”在 IM 层没有强制力，旧设备仍能收消息；
  - 结合 H4，可长期冒充/骚扰。
- **修复方案（推荐 Redis 会话纪元）**：
  1. Django 登录成功、`session_version += 1` 后，把新版本写入 imserver 使用的同一个 Redis DB：
     ```python
     # 伪代码；key 需与 imserver 约定
     im_redis.set(f"im:session_version:{user.id}", user.session_version)
     ```
  2. `mint_im_token()` 增加 claim：
     ```python
     {"sv": user.session_version, ...}
     ```
  3. imserver `verify_token` 解析 `sv`，并与 `redis.get("im:session_version:"+uid)` 比对；不一致返回 40101。
  4. `kick`/封禁/注销时递增该 key（或删除），旧 token 立即失效；`jti` 黑名单作为补充，TTL = token TTL。
  5. 注意 Django 默认 cache 是 Redis DB0，imserver 是 DB2；需要新增一个指向 DB2 的 Django Redis alias，或统一 DB 并更新文档。
- **验收标准**：
  - 新设备登录后，旧设备用旧 token 重连 WS 收到 40101；
  - 调用 `/internal/kick` 后，旧 token 不能重连；
  - 正常单设备收发不受影响。
- **回归测试**：
  - `imserver/scripts/verify_graylist.py` 增加“踢后重连被拒”断言；
  - Django 测试：登录后旧 token 失效、刷新 token 失效。

#### H4. 任意登录用户可向任意 uid 发 IM 消息，无配对/关系校验

- **等级**：高危（High）
- **位置**：`imserver/src/net/ws_server.cpp`、`imserver/src/service/message_service.cpp`、`imserver/src/store/user_repo.cpp`
- **证据**：
  - WS `send` 只校验 `to` 以 `u` 开头：[ws_server.cpp:351-392](../../imserver/src/net/ws_server.cpp#L351-L392)
  - `MessageService::send` 只校验 `to != 0`、`from != to`、`client_msg_id` 合法：[message_service.cpp:197-201](../../imserver/src/service/message_service.cpp#L197-L201)
  - 发送时 `users_.ensure(request.to, "")`，任意 uid 都会建行：[message_service.cpp:280](../../imserver/src/service/message_service.cpp#L280)
  - `known_` 缓存无上限：[user_repo.cpp:19-31](../../imserver/src/store/user_repo.cpp#L19-L31)
- **影响**：
  - 绕过“必须配对才能聊天”的产品规则，直接骚扰任意用户；
  - 可批量向随机/连续 uid 发消息，制造 `im_user` 行与 `known_` 内存增长；
  - 单连接 20 msg/s，多连接可放大，2C2G 上容易打满 MySQL；
  - 与 H3 组合，被盗 token 可持续骚扰。
- **修复方案**：
  1. 建立“允许通信”的权威数据：
     - 方案 A（推荐）：Django 在配对创建时写入 Redis `im:pair:{min}:{max}`，解除配对/拉黑时删除；imserver 发送前 `EXISTS` 校验。
     - 方案 B：在 `chatapp_im` 建 `im_match` 表，由 Django 任务同步；imserver 查询。
  2. imserver `send` 对 `from != 0` 的消息强制校验 `pair` 存在；系统通知（from=0）豁免。
  3. 目标用户必须已存在：把 `users_.ensure(request.to, "")` 改为“先 `get`，不存在则 422/403”；不要为任意 uid 建行。
  4. 增加发送配额：每发送者每分钟/每天上限、每收件人每分钟上限；`known_` 改为 LRU 或设上限。
  5. 记录被拒绝的发送（from/to/原因），用于风控。
- **验收标准**：
  - 未配对用户发送返回 40302（或约定错误码）；
  - 已配对用户正常收发；
  - 向不存在 uid 发送不产生 `im_user` 行；
  - 压测下 `known_` 内存有上限。
- **回归测试**：
  - `imserver` 单测：未配对拒绝、配对允许、系统通知允许；
  - 集成：App/Web 配对后聊天、解除配对后发送失败。

#### H5. `AUTO_APPROVE=1` + 图片/语音/文本无机器审核

- **等级**：高危（High，合规/滥用）
- **位置**：`chatapp/config/settings.py`、`chatapp/users/views.py`、`chatapp/moderation/text_check.py`
- **证据**：
  - 生产配置 `AUTO_APPROVE=1`：[部署设计:80](../superpowers/specs/2026-09-18-m4-deploy-runthrough-design.md#L80)
  - 上传即过审：[users/views.py:132-137](../../chatapp/users/views.py#L132-L137)
  - 聊天图片/语音没有机器审核；文本审核只有 6 个词的子串匹配：[text_check.py:8](../../chatapp/moderation/text_check.py#L8)
- **影响**：
  - 色情、违法、诈骗内容可直接分发；
  - 聊天图片/语音仅靠人工抽审，属于已知上线阻断项；
  - 应用商店审核、监管检查、PIPL/未成年人保护均有风险；
  - 一旦出现违法内容，平台承担连带责任。
- **修复方案**：
  1. 生产 `AUTO_APPROVE=0`；新照片 `status=pending`，审核通过后才进入公开资料/候选池。
  2. 接入云内容安全（图片/语音/文本），异步审核；审核中不可见，拒绝则通知用户。
  3. 聊天图片/语音：先发后审 + 快速下架 + 举报联动；高风险场景可先审后发。
  4. 文本审核替换为真实内容安全 API；保留关键词兜底。
  5. 运营台增加“待审核/已拒绝/申诉”队列与审计。
- **验收标准**：
  - 新上传照片默认 `pending`，未过审不出现在 `PublicProfileSerializer`/候选池；
  - 违规样本被拒绝并记录；
  - 聊天媒体有审核状态与下架能力。
- **回归测试**：
  - 上传→待审→通过/拒绝→资料页/候选池可见性；
  - 举报→下架→通知。

#### H6. Ops/Admin 登录无速率限制、无 2FA，且公网暴露

- **等级**：高危（High）
- **位置**：`chatapp/ops/urls.py`、`chatapp/config/urls.py`、`chatapp/ops/decorators.py`
- **证据**：
  - `/ops/login/` 使用 Django `LoginView`：[ops/urls.py:18-22](../../chatapp/ops/urls.py#L18-L22)
  - `/admin/` 直接挂载：[urls.py:14](../../chatapp/config/urls.py#L14)
  - 代码中无 `django-axes`、无登录 throttle、无 2FA
  - 审核台与后台均走 HTTP（见 H1）
- **影响**：
  - 可对运营/管理员账号做密码爆破、撞库；
  - 进入审核台可封禁/解封、删动态、查看全部举报与私聊媒体；
  - 进入 admin 可改用户、照片、举报、封禁记录；
  - 结合 H1，密码在 HTTP 上明文传输。
- **修复方案**：
  1. 登录失败锁定：`django-axes` 或自研 cache 计数（账号 + IP 双维度，5 次锁 15 分钟）。
  2. 强制 2FA（`django-otp` 或 TOTP）；管理员必须开启。
  3. `/admin/`、`/ops/` 加 IP 白名单/VPN；至少不要对公网开放。
  4. 生产可禁用 `/admin/` 或改非默认路径（仅降低扫描噪音，不是主要防护）。
  5. 增加异地/异常登录告警；定期审计 `is_staff` 账号。
- **验收标准**：
  - 连续 5 次失败后锁定；
  - 管理员登录需要第二因子；
  - 非白名单 IP 访问 `/admin/`、`/ops/` 被拒绝。
- **回归测试**：
  - 登录成功/失败/锁定/解锁；
  - 2FA 绑定、验证、恢复码；
  - HTMX 操作仍正常。

---

### 4.3 中危

#### M1. `X-Forwarded-For` 可伪造，DRF 的 IP 限流可被绕过

- **等级**：中危（Medium）
- **位置**：`chatapp/accounts/throttles.py`、`chatapp/config/settings.py`、nginx
- **证据**：
  - 短信发码/校验按 IP 限流：[accounts/throttles.py:27](../../chatapp/accounts/throttles.py#L27)、[accounts/throttles.py:45](../../chatapp/accounts/throttles.py#L45)
  - 项目未设置 `NUM_PROXIES`；DRF 3.18 在 `NUM_PROXIES=None` 时直接使用完整的 `X-Forwarded-For` 作为 ident
  - nginx 使用 `$proxy_add_x_forwarded_for`：[部署计划:376](../superpowers/plans/2026-09-18-m4-deploy-runthrough.md#L376)
- **影响**：
  - 每次请求换一个 `X-Forwarded-For` 即可绕过 20/h、60/h 的 IP 限额；
  - 用于短信轰炸、验证码爆破、锁定 DoS；
  - 增加短信费用与日志噪音。
- **修复方案**：
  1. `REST_FRAMEWORK["NUM_PROXIES"] = 1`（按实际代理层数；只有一层 nginx 就是 1）。
  2. nginx 覆盖客户端传入的 XFF：
     ```nginx
     proxy_set_header X-Forwarded-For $remote_addr;
     ```
     或使用 `real_ip_header` + `set_real_ip_from` 只信任自己的代理。
  3. 增加按手机号、按设备的独立限额；短信发送加图形验证码/行为验证。
  4. 监控同一 IP/手机号的发送频率。
- **验收标准**：
  - 伪造 `X-Forwarded-For` 不改变限流 key；
  - 同一 IP 第 21 次发码返回 429；
  - 同一手机号 60 秒内重发返回 42901。
- **回归测试**：
  - 用 `curl -H 'X-Forwarded-For: 1.2.3.4'` 连续请求，确认限流仍生效；
  - 正常多设备同 IP 不被误伤（测试号）。

#### M2. 用户/资料枚举与批量抓取

- **等级**：中危（Medium）
- **位置**：`chatapp/users/views.py`、`chatapp/accounts/views.py`
- **证据**：
  - `GET /users/{id}` 对任意 id 返回公开资料，无频率限制：[users/views.py:86-108](../../chatapp/users/views.py#L86-L108)
  - `GET /presence` 单次可查 100 个 id：[users/views.py:162-195](../../chatapp/users/views.py#L162-L195)
  - `is_new_user` 直接暴露手机号是否注册：[accounts/views.py:172-177](../../chatapp/accounts/views.py#L172-L177)
  - 举报/拉黑/滑卡对不存在用户返回 404/400，存在用户返回其他状态
- **影响**：
  - 批量枚举用户 id，抓取昵称、性别、年龄、城市、简介、照片；
  - 探测手机号是否注册、用户是否在线；
  - 为骚扰/诈骗提供目标列表。
- **修复方案**：
  1. 给 `public_profile` 加用户/IP 限流（如 120/h），给 `candidates` 加 60/h，`presence` 降到 120/h。
  2. 非配对关系只返回最小字段（如昵称、头像、年龄区间，不返回城市/简介全文）。
  3. `is_new_user` 改为统一响应，或仅在完成验证码后返回；至少加限流。
  4. 对连续 id 遍历、短时间大量 404 做风控与告警。
  5. 图片 URL 增加防盗链/限速（见 M9）。
- **验收标准**：
  - 连续请求触发 429；
  - 非配对用户看不到敏感字段；
  - 枚举行为出现在风控日志。
- **回归测试**：
  - 正常浏览资料/候选/在线状态不受影响；
  - 限流阈值可配置。

#### M3. 图片解压炸弹/像素上限缺失

- **等级**：中危（Medium）
- **位置**：`chatapp/im/views.py`、`chatapp/users/serializers.py`、`chatapp/feed/serializers.py`
- **证据**：
  - 聊天图先 `Image.open` + `exif_transpose`，之后才检查 `max(width,height) > 4096`：[im/views.py:121-130](../../chatapp/im/views.py#L121-L130)
  - 资料图只校验大小：[users/serializers.py:198-217](../../chatapp/users/serializers.py#L198-L217)
  - 广场图只校验大小 + PIL 可解码：[feed/serializers.py:200-209](../../chatapp/feed/serializers.py#L200-L209)
- **影响**：
  - 5MB 的纯色 PNG 可声明 12000×12000（1.44 亿像素），Pillow 默认只在约 8900 万像素时告警、约 1.78 亿才报错；
  - `exif_transpose` 可能直接分配数百 MB，2C2G 上可打爆 gunicorn worker；
  - 多请求并发可造成服务不可用。
- **修复方案**：
  1. 解码前先读 header 检查 `width * height` 上限（建议 2000 万像素）。
  2. 设置 `Image.MAX_IMAGE_PIXELS = 20_000_000`，捕获 `Image.DecompressionBombError` 返回 400。
  3. 资料图/广场图增加自定义校验器：`Image.open` 后先查 `size`，再 `exif_transpose`/重编码。
  4. 统一缩略图/重编码，限制最大边（如 4096）。
  5. 上传处理加超时、内存限制与并发上限。
- **验收标准**：
  - 构造超大像素 PNG 返回 400，进程内存不暴涨；
  - 正常 5MB 图片仍可上传；
  - 三个上传入口（资料/广场/聊天）行为一致。
- **回归测试**：
  - 单测：`12000x12000` 纯色 PNG、`5000x5000` JPEG、正常图片；
  - 压测：并发 10 个上传，观察 RSS。

#### M4. EXIF/GPS 未剥离

- **等级**：中危（Medium）
- **位置**：`chatapp/users/models.py`、`chatapp/feed/models.py`、`chatapp/im/views.py`
- **证据**：
  - 资料照片原样存储：[users/models.py:199](../../chatapp/users/models.py#L199)
  - 广场图片原样存储：[feed/models.py:41](../../chatapp/feed/models.py#L41)
  - 聊天图片仅在 EXIF 方向不为 1 时才重编码；方向为 1 时直接存原始字节：[im/views.py:132-138](../../chatapp/im/views.py#L132-L138)
- **影响**：
  - 手机原图可能带 GPS 坐标、拍摄时间、设备型号；
  - 资料图/广场图对所有登录用户可见，聊天图对接收方可见；
  - 造成住址/常去地点泄露。
- **修复方案**：
  1. 所有图片统一 `ImageOps.exif_transpose` 后重编码（JPEG/WebP），剥离 EXIF/GPS。
  2. 聊天图无论 orientation 是否为 1 都重编码；不再直接存原始字节。
  3. 资料图/广场图同样重编码；保留视觉质量，去掉元数据。
  4. 上传页提示用户；隐私政策说明。
- **验收标准**：
  - 上传带 GPS 的样本，下载后 `exiftool` 看不到 GPS；
  - 图片方向正确、质量可接受；
  - 三个入口一致。
- **回归测试**：
  - 单测：带 EXIF 的 JPEG/PNG/WebP；
  - 手工：手机原图上传后下载检查。

#### M5. ffmpeg 处理不可信音频，无协议白名单/沙箱

- **等级**：中危（Medium）
- **位置**：`chatapp/im/voice.py`、`chatapp/im/views.py`
- **证据**：
  - `ffprobe`/`ffmpeg` 直接处理用户上传文件：[im/voice.py:79-104](../../chatapp/im/voice.py#L79-L104)
  - 参数数组调用，未经过 shell（这点是好的），但没有 `-protocol_whitelist`、没有容器隔离/ seccomp
  - 上传路径同步执行，15 秒超时：[im/views.py:180-191](../../chatapp/im/views.py#L180-L191)
- **影响**：
  - 恶意媒体可触发 ffmpeg 解析器漏洞；
  - 某些容器/协议可让 ffmpeg 访问外部 URL 或本地文件（SSRF/本地文件读取，取决于编译与容器权限）；
  - 60 次/小时/账号的同步转码可占满 CPU。
- **修复方案**：
  1. ffprobe/ffmpeg 增加：
     ```bash
     -protocol_whitelist file,pipe
     ```
     并明确 `-f` 输入格式；禁用 `http/tcp/udp/concat` 等不必要协议。
  2. 在独立容器/低权限用户/只读文件系统中运行，`--cap-drop=ALL`、`--security-opt no-new-privileges`、`--pids-limit`、`--memory`。
  3. 转码改 Celery 异步队列，限制并发与超时；上传接口只做入队与快速校验。
  4. 定期升级 ffmpeg；监控异常退出与高 CPU。
- **验收标准**：
  - 正常 m4a/aac/webm/ogg 可转码；
  - 恶意 playlist/concat 样本无法访问网络/本地文件；
  - 转码并发不超过配置上限。
- **回归测试**：
  - `imserver`/Django 语音单测；
  - 隔离环境用受控样本验证协议白名单。

#### M6. 聊天媒体签名 URL 可转发 24 小时，且密钥为空时 fail-open

- **等级**：中危（Medium）
- **位置**：`chatapp/im/media_sign.py`、`chatapp/im/views.py`、`chatapp/config/settings.py`
- **证据**：
  - 未配置密钥时 `verify()` 恒为 `True`：[im/media_sign.py:123-146](../../chatapp/im/media_sign.py#L123-L146)
  - 签名有效期默认 86400 秒：[settings.py:334](../../chatapp/config/settings.py#L334)
  - 签名只绑定 path + exp，不绑定查看者；`/im/images/auth` 是 `AllowAny`：[im/views.py:207-230](../../chatapp/im/views.py#L207-L230)
  - `.env.example` 中密钥默认为空：[.env.example:44](../../chatapp/.env.example#L44)
- **影响**：
  - 任何拿到链接的人（转发、截图、日志、Referer）在 24 小时内都能查看私聊图片/语音；
  - 若生产漏配 `IM_MEDIA_SIGN_SECRET`，所有 `/media/chat/` 直接公开；
  - 当前生产部署记录显示已配置，但代码层是 fail-open，漏配即事故。
- **修复方案**：
  1. 生产启动强制要求 `IM_MEDIA_SIGN_SECRET`，缺失直接 `ImproperlyConfigured`。
  2. TTL 缩短到 1 小时（或按场景 15 分钟）；过期返回 403。
  3. 签名加入查看者/会话维度：`path + uid + exp`；nginx `auth_request` 同时校验登录态与成员关系（需调整 nginx 传递 Authorization/Cookie）。
  4. 支持一次性 token 或撤销列表；记录媒体访问日志与异常下载告警。
  5. 若暂不做查看者绑定，至少加防盗链、限速、审计，并在隐私政策中说明“链接可转发”。
- **验收标准**：
  - 无签名/过期/篡改均 403；
  - 非会话成员即使拿到链接也不能访问（若实现绑定）；
  - 生产未配密钥时启动失败。
- **回归测试**：
  - 签名 URL 正常 200；
  - 过期 403、篡改 403、跨用户 403；
  - `IM_MEDIA_SIGN_SECRET` 为空时启动失败（测试环境可 override）。

#### M7. 高开销接口无限流 + 磁盘配额缺失

- **等级**：中危（Medium）
- **位置**：`chatapp/discovery/views.py`、`chatapp/im/views.py`、`chatapp/feed/views.py`、`chatapp/moderation/views.py`
- **证据**：
  - 候选池 `order_by("?")` 无频率限制：[discovery/views.py:43-92](../../chatapp/discovery/views.py#L43-L92)
  - `/im/user_sig` 同步调用腾讯/自建 IM，无频率限制：[im/views.py:52-99](../../chatapp/im/views.py#L52-L99)
  - 点赞、拉黑/解除拉黑无频率限制：[feed/views.py:134-152](../../chatapp/feed/views.py#L134-L152)、[moderation/views.py:63-118](../../chatapp/moderation/views.py#L63-L118)
  - 聊天图 30 次/小时 × 5MB；动态 20 条/天 × 9 张 × 5MB；无全局磁盘配额
  - 媒体清理只覆盖聊天图/语音，资料图与广场图无保留期
- **影响**：
  - 单账号按上限估算：聊天图约 3.6GB/天、动态图约 900MB/天，30 天可到上百 GB；
  - 2C2G 服务器磁盘/CPU/MySQL 都容易被单账号或小号批量打满；
  - `user_sig` 同步外部调用还会拖慢请求。
- **修复方案**：
  1. 加 DRF throttle：`candidates` 60/h、`user_sig` 30/h、`post_like` 120/h、`blocks` 60/h、`upload_photo` 20/h。
  2. 候选池改预计算随机列或缓存（Redis，短 TTL）。
  3. `user_sig` 的建号/踢人改异步或缓存；避免每次同步外部调用。
  4. 增加全局/单用户存储配额（如 200MB/用户）、保留期、磁盘告警。
  5. 资料图/广场图也纳入清理策略（或迁 COS/OSS）。
- **验收标准**：
  - 超限返回 429；
  - 候选池 P95 延迟下降；
  - 磁盘使用有监控与告警；
  - 单用户达到配额后上传被拒。
- **回归测试**：
  - 正常浏览/聊天不受影响；
  - 限流阈值可配置；
  - 磁盘清理任务 dry-run 正确。

#### M8. 短信锁定 DoS + 验证码非 CSPRNG

- **等级**：中危（Medium）
- **位置**：`chatapp/accounts/sms_codes.py`、`chatapp/accounts/services.py`
- **证据**：
  - 同一手机号连错 5 次锁定 900 秒：[sms_codes.py:20-42](../../chatapp/accounts/sms_codes.py#L20-L42)
  - 验证码用 `random.randint` 生成：[accounts/services.py:44](../../chatapp/accounts/services.py#L44)
  - 校验接口的 IP 限流可被 XFF 绕过（见 M1）
- **影响**：
  - 知道目标手机号即可故意提交 5 次错码，把对方锁 15 分钟，反复操作可长期阻止登录；
  - `random` 不是密码学安全随机数，理论上存在状态预测风险（远程利用门槛较高，但不应使用）。
- **修复方案**：
  1. 验证码改用 `secrets.randbelow(1_000_000)`。
  2. 锁定策略改为渐进延迟 + 图形验证码/行为验证，不要直接锁死账号；或锁定只针对“错误尝试”，允许重新发码后解锁。
  3. 对同一手机号的失败尝试做设备/IP 关联分析；异常时人工审核。
  4. 提供解锁/申诉通道；监控定向锁号。
- **验收标准**：
  - 验证码由 CSPRNG 生成；
  - 连续错码触发延迟/验证码，而不是长期锁死；
  - 正常用户可重新发码登录。
- **回归测试**：
  - 单测：5 次错码后的状态机；
  - 手工：锁定后重新发码/等待恢复。

#### M9. Ops 可浏览全部私聊媒体；资料图/广场图公开直出

- **等级**：中危（Medium）
- **位置**：`chatapp/ops/views.py`、nginx `/media/`
- **证据**：
  - 审核台“聊天图片/语音”列表默认查全量，不要求关联举报：[ops/views.py:583-598](../../chatapp/ops/views.py#L583-L598)、[ops/views.py:626-641](../../chatapp/ops/views.py#L626-L641)
  - 通用 `/media/` 由 nginx 直接 alias，无鉴权；资料图、广场图均走这里：[部署计划:369](../superpowers/plans/2026-09-18-m4-deploy-runthrough.md#L369)
- **影响**：
  - 任一运营账号可浏览所有用户的私聊图片/语音，超出“处理举报”的最小必要范围；
  - 资料图/广场图 URL 一旦泄露，无需登录即可访问；
  - 不符合 PIPL 最小必要与访问审计要求。
- **修复方案**：
  1. 审核台媒体列表按举报/案件维度过滤，默认只看与当前举报相关的最近 N 天。
  2. 增加查看审计（谁看了谁的媒体、时间、原因）。
  3. 资料图/广场图至少加防盗链/限速，敏感场景改签名 URL。
  4. 明确运营权限分级：普通客服只看举报证据，高级管理员才可全量检索。
  5. 媒体保留期与删除策略写入隐私政策。
- **验收标准**：
  - 普通运营账号不能无理由浏览全量私聊媒体；
  - 媒体访问有审计记录；
  - 资料图/广场图有防盗链或限速。
- **回归测试**：
  - 举报详情页仍可看到证据；
  - 权限分级生效。

#### M10. `candidates?limit=-1` 触发 500；其他非法参数也可能 500

- **等级**：中危（Medium）
- **位置**：`chatapp/discovery/views.py`、`chatapp/ops/views.py`
- **证据**：
  - `limit = min(int(...), MAX_LIMIT)`，没有下限；`qs[: -1]` 会抛 `ValueError: Negative indexing is not supported`：[discovery/views.py:84-91](../../chatapp/discovery/views.py#L84-L91)
  - 已在本地只读验证该异常
  - `/ops/chat-images/?user=abc` 直接 `filter(owner_id="abc")`，可能 ValueError：[ops/views.py:595-597](../../chatapp/ops/views.py#L595-L597)
- **影响**：
  - 攻击者可低成本制造 500 与错误日志；
  - 违反项目“失败一律 4xx + 统一错误信封”的契约；
  - 可能掩盖真实故障。
- **修复方案**：
  ```python
  try:
      limit = int(request.query_params.get("limit", DEFAULT_LIMIT))
  except (TypeError, ValueError):
      limit = DEFAULT_LIMIT
  limit = max(1, min(limit, MAX_LIMIT))
  ```
  所有 query 参数先校验类型/范围，非法返回 400；ops 的 `user`、`ids`、`date` 同样处理。
- **验收标准**：
  - `limit=-1`、`limit=abc`、`limit=0`、`limit=999` 分别返回 400 或合理值，不再 500；
  - 错误响应符合统一信封。
- **回归测试**：
  - 参数化测试覆盖 `limit` 边界；
  - ops 非法参数测试。

#### M11. `swipe` 未校验拉黑关系，可向拉黑自己的人滑卡并触发配对灰条

- **等级**：中危（Medium）
- **位置**：`chatapp/discovery/views.py`
- **证据**：
  - 候选池、喜欢我的人、配对列表都用了 `blocked_user_ids`，但 `swipe` 没有：[discovery/views.py:124-135](../../chatapp/discovery/views.py#L124-L135)
  - 只要对方资料 `COMPLETE`，就能创建 `Swipe`；若对方之前喜欢过我，还会创建 `Match` 并 `notify_match`
- **影响**：
  - 拉黑后仍可被对方“喜欢”，甚至生成配对与 IM 灰条；
  - 拉黑在匹配层不是完全失效，但存在绕过与骚扰窗口；
  - 会产生无意义的 Match 行与通知。
- **修复方案**：
  1. `swipe` 先检查双向 `Block`，有拉黑关系直接 404/400。
  2. 同时检查轻/重封禁状态。
  3. 配对通知前再校验一次拉黑关系。
- **验收标准**：
  - A 拉黑 B 后，B 对 A 滑卡返回 404；
  - 不产生 Match/灰条；
  - 正常滑卡不受影响。
- **回归测试**：
  - 单测：双向拉黑、单向拉黑、正常滑卡。

#### M12. 会话版本并发竞态；举报可重复创建

- **等级**：中危（Medium）
- **位置**：`chatapp/accounts/views.py`、`chatapp/moderation/views.py`、`chatapp/moderation/models.py`
- **证据**：
  - `session_version` 是“读—加一—保存”，无 `F()` 或行锁：[accounts/views.py:152-156](../../chatapp/accounts/views.py#L152-L156)
  - `Report.get_or_create` 没有唯一约束兜底：[moderation/views.py:56-59](../../chatapp/moderation/views.py#L56-L59)、[moderation/models.py:31-62](../../chatapp/moderation/models.py#L31-L62)
- **影响**：
  - 两个并发登录可能都读到同一个旧版本，最终都拿到“有效”token，单设备登录被绕过；
  - 并发举报可产生重复待处理记录，增加运营噪音；
  - `get_or_create` 并发还可能抛 IntegrityError 500。
- **修复方案**：
  1. 会话版本：
     ```python
     from django.db.models import F
     User.objects.filter(pk=user.pk).update(session_version=F("session_version") + 1)
     user.refresh_from_db(fields=["session_version"])
     ```
     或 `select_for_update()`。
  2. 举报去重：MySQL 8 不支持部分唯一索引，可用“可空 dedupe_key + 唯一约束”：
     - `dedupe_key = f"{reporter_id}:{target_id}:pending"`；
     - 处理时置 `NULL`；
     - 唯一约束允许多个 NULL，MySQL 可用。
  3. 并发创建捕获 `IntegrityError`，回查已有记录返回 200。
- **验收标准**：
  - 并发登录测试中只有一个 token 有效；
  - 并发举报只产生一条 pending；
  - 不出现 500。
- **回归测试**：
  - 并发测试（线程/事务）；
  - 举报幂等测试。

---

### 4.4 低危/加固

#### L1. `/health`、`/readyz` 公开

- **证据**：[accounts/views.py:67-91](../../chatapp/accounts/views.py#L67-L91)
- **影响**：暴露依赖状态；`readyz` 每次打 DB + Redis，可被低成本刷。
- **建议**：仅内网/监控访问；加限流；返回最小信息。

#### L2. `X-Request-Id` 客户端可控并回显/落日志

- **证据**：[middleware.py:39-50](../../chatapp/config/middleware.py#L39-L50)
- **影响**：日志伪造、终端转义；不直接影响业务。
- **建议**：限制长度/字符集；日志转义；只接受 UUID/短字符串。

#### L3. Host 头影响绝对 URL

- **证据**：`build_absolute_uri` 用于头像/图片 URL：[feed/serializers.py:33](../../chatapp/feed/serializers.py#L33)、[moderation/serializers.py:72](../../chatapp/moderation/serializers.py#L72)
- **影响**：依赖 `ALLOWED_HOSTS`；配置错误时可能返回被污染的绝对地址。
- **建议**：生产严格 `ALLOWED_HOSTS`；不要使用 `*`；需要时用 `USE_X_FORWARDED_HOST` 且只信任 nginx。

#### L4. CORS 允许 localhost 任意端口

- **证据**：[settings.py:237-240](../../chatapp/config/settings.py#L237-L240)
- **影响**：本地恶意页面可发起跨域请求；当前无 cookie 凭证，风险较低。
- **建议**：生产移除 localhost 规则；开发用精确端口；不要把 `CORS_ALLOW_CREDENTIALS=True`。

#### L5. 图片格式面过大、未统一转码

- **证据**：Django 5.2 `ImageField` 允许 GIF/BMP/TIFF/PDF 等大量格式；资料/广场图未重编码。
- **影响**：元数据泄露、解码攻击面、格式兼容问题。
- **建议**：只允许 jpg/png/webp；统一重编码；限制像素；剥离元数据。

#### L6. 依赖未锁定

- **证据**：[requirements.txt:1-13](../../chatapp/requirements.txt#L1-L13)、[package.json:17-41](../../web/package.json#L17-L41)
- **影响**：供应链/可复现性；可能引入已知 CVE。
- **建议**：`pip-compile`/`uv lock`、`npm ci` + lockfile；定期 `pip-audit`/`npm audit`；Dependabot。

#### L7. Web 静态页安全头缺失

- **证据**：部署文档中的 nginx 片段未见 CSP/X-Frame-Options/X-Content-Type-Options；Django 的 `XFrameOptionsMiddleware` 只覆盖 Django 响应。
- **影响**：点击劫持/纵深防御不足。
- **建议**：nginx 统一加：
  ```nginx
  add_header X-Content-Type-Options nosniff always;
  add_header X-Frame-Options DENY always;
  add_header Referrer-Policy same-origin always;
  add_header Content-Security-Policy "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self' ws: wss:; script-src 'self'; style-src 'self' 'unsafe-inline';" always;
  ```
  按实际 IM/CDN 域名调整 `connect-src`。

#### L8. App 令牌存 SharedPreferences

- **证据**：[token_store.dart:15-52](../../app/lib/core/token_store.dart#L15-L52)
- **影响**：本地明文令牌；root/备份/恶意应用可读。
- **建议**：`flutter_secure_storage`；关闭/排除备份；聊天页 `FLAG_SECURE`；证书绑定。

#### L9. imserver 信任头/无界缓存/探针

- **证据**：[ws_server.cpp:110-130](../../imserver/src/net/ws_server.cpp#L110-L130)、[user_repo.cpp:19-31](../../imserver/src/store/user_repo.cpp#L19-L31)、[http_api.cpp:329-340](../../imserver/src/net/http_api.cpp#L329-L340)
- **影响**：若 9100/9101 直接暴露，`X-Real-IP` 可伪造绕过 IP 限流；`Origin` 为空放行；`known_`/`auth_buckets_` 无上限；`healthz/readyz` 无 HMAC（仅 loopback）。
- **建议**：端口只绑 127.0.0.1；防火墙限制；`IM_ALLOWED_ORIGINS` 配置；缓存 LRU/上限；探针仅内网。

#### L10. 其他细节

- IM JWT 过期判断用 `exp < now` 而非 `<=`（1 秒边界）：[token.cpp:151-157](../../imserver/src/auth/token.cpp#L151-L157)。
- 短信验证码成功后 60 秒内可重放（设计如此）：[sms_codes.py:39-41](../../chatapp/accounts/sms_codes.py#L39-L41)；确认产品可接受。
- `/ops` 的 `user`、`ids` 等参数非法时可能 500：统一参数校验。

---

## 5. 修复计划

### 5.1 P0（立即，阻断上线）

| 编号 | 动作 | 关键文件 | 验收 | 预估 |
|---|---|---|---|---|
| S1 | 接真实短信商 + `SMS_DEV_MODE=0` + 启动断言 + 删除固定码 | `accounts/services.py`、`settings.py`、`notifications/backends.py` | 任意手机号+123456 登录失败；真实短信可达 | 1–2 天（含短信商） |
| H1 | HTTPS/HSTS/Secure cookie；后台 IP 白名单 | `settings.py`、nginx | `check --deploy` 无告警；80→443 | 0.5–1 天（证书+域名） |
| H2 | 删除验证码日志；生产禁用 Console 后端 | `accounts/services.py`、`notifications/backends.py` | 日志无 6 位验证码；真实短信可达 | 0.5 天 |

> **注意**：不要只把 `SMS_DEV_MODE` 改成 0 而不接短信商——当前 `ConsoleSmsBackend` 不发送短信，会导致所有用户无法登录。S1 必须“接真实短信商 + 置 0”同批完成。

### 5.2 P1（本周，公开测试前）

| 编号 | 动作 | 验收 |
|---|---|---|
| H3 | IM token 加 `sv` + Redis 会话纪元 + 吊销 | 旧 token 重连 40101；踢后不能重连 |
| H4 | IM 发送校验配对 + 目标存在 + 配额 | 未配对发送 40302；不存在 uid 不建行 |
| H5 | `AUTO_APPROVE=0` + 内容安全接入 | 新照片 pending；违规样本拒绝 |
| H6 | 后台登录限流 + 2FA + IP 白名单 | 5 次失败锁定；2FA 生效 |
| M1 | `NUM_PROXIES=1` + nginx XFF 清洗 | 伪造 XFF 不绕过限流 |
| M3 | 像素上限 + 重编码 | 超大图 400，内存稳定 |
| M6 | 媒体签名密钥启动校验 + 短 TTL | 无签名/过期 403；漏配启动失败 |

### 5.3 P2（迭代，公开上线前）

| 编号 | 动作 |
|---|---|
| M2 | 资料/候选/在线状态限流；非配对最小字段 |
| M4 | 全量剥离 EXIF/GPS |
| M5 | ffmpeg 协议白名单 + 容器隔离 + 异步 |
| M7 | 高开销接口限流 + 磁盘配额 + 候选池缓存 |
| M8 | `secrets` + 渐进锁定 + 验证码 |
| M9 | Ops 媒体按举报过滤 + 审计；资料图防盗链 |
| M10 | 参数校验统一 400 |
| M11 | swipe 校验拉黑 |
| M12 | `F()`/行锁 + 举报去重 |
| L1–L10 | 按低危清单逐步加固 |

### 5.4 不建议的临时方案

- ❌ 只改 `SMS_DEV_MODE=0`，不接短信商 → 用户收不到码，等于全站登录故障。
- ❌ 只在 App 登录页隐藏“123456”提示，不改后端 → 固定码仍可利用。
- ❌ 只靠随机文件名/长 URL 保护聊天媒体 → URL 可转发，且空密钥 fail-open。
- ❌ 只在 nginx 加限流，不改 DRF `NUM_PROXIES` → 应用层仍按伪造 XFF 计数。
- ❌ 把 `AUTO_APPROVE=0` 但不上审核队列 → 用户照片永远 pending，资料无法完善。

---

## 6. 回归与验证

### 6.1 通用命令

```bash
# 后端（需 Redis；cwd = chatapp/）
python manage.py check --deploy
python manage.py test

# Web（cwd = web/）
npm run type-check
npm run lint
npm run test:run

# App（cwd = app/）
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test

# imserver
docker compose -f imserver/docker-compose.test.yml run --rm test bash /src/scripts/test_http.sh
```

### 6.2 安全专项测试建议

| 编号 | 测试 |
|---|---|
| S1 | `SMS_DEV_MODE=0` 下固定码登录失败；真实短信登录成功 |
| H1 | `curl -I http://...` 返回 301；HSTS/Secure cookie 存在 |
| H2 | 日志 grep 6 位数字；确认无 `code=` |
| H3 | 登录新设备 → 旧 WS 重连 40101；`/internal/kick` 后旧 token 拒绝 |
| H4 | 未配对发送 40302；配对后成功；随机 uid 不建行 |
| H5 | 新照片 pending；违规样本拒绝；资料页不可见 |
| H6 | 5 次失败锁定；2FA 必填；非白名单 IP 403 |
| M1 | 伪造 XFF 连续请求仍 429 |
| M3 | 12000×12000 PNG 返回 400；RSS 稳定 |
| M4 | 带 GPS 图片下载后无 GPS |
| M5 | 恶意 playlist 不访问网络/本地文件 |
| M6 | 无签名/过期/篡改 403；空密钥启动失败 |
| M10 | `limit=-1/abc/0/999` 不 500 |
| M11 | 拉黑后滑卡 404，不产生 Match |
| M12 | 并发登录只有一个 token 有效；并发举报一条 pending |

### 6.3 发布前检查清单

- [ ] 生产 `SMS_DEV_MODE=0`，真实短信可达
- [ ] 生产 `AUTO_APPROVE=0`，审核队列可用
- [ ] 生产 `DEBUG=0`，`SECRET_KEY` 随机且未泄露
- [ ] HTTPS 全站，HSTS/Secure cookie 生效
- [ ] `/admin/`、`/ops/` 仅白名单/VPN 可访问
- [ ] 日志无验证码、无完整手机号、无 token
- [ ] IM token 可吊销；未配对不能发消息
- [ ] 媒体签名密钥已配，TTL 合理
- [ ] 上传像素上限/EXIF 剥离生效
- [ ] 限流在 nginx + DRF 双层生效
- [ ] 磁盘/内存/连接数监控与告警
- [ ] 备份与恢复演练完成

---

## 7. 已排除项（避免误报）

以下项已核对，**本次未发现可利用问题**：

| 类别 | 结论 | 依据 |
|---|---|---|
| SQL 注入 | 未发现 | Django 全部 ORM；imserver 用 prepared statement、数值 id 拼接、字符串 `mysql_real_escape_string`/LIKE 转义 |
| IDOR | 未发现直接越权 | 删除照片/动态/评论、解除配对/拉黑均限定 `request.user` |
| CSRF | API 不适用；Ops 已防护 | API 用 Bearer JWT；`/ops` HTMX 带 `X-CSRFToken`，未发现 `csrf_exempt` |
| 上传扩展名 XSS | 未发现 | Django 5.2 `ImageField` 校验扩展名，本地验证 `evil.html` 被拒；聊天图强制后缀 |
| Mass assignment | 未发现 | 资料/偏好/反馈/举报/滑卡均为显式字段 |
| 命令注入 | 未发现 | ffmpeg 使用参数数组、不经 shell |
| 开放重定向 | 未发现 | Django `LoginView` 使用安全 `next` 校验 |

---

## 8. 附录

### 8.1 生产配置基线（建议）

| 配置 | 建议值 | 说明 |
|---|---|---|
| `DEBUG` | `0` | 禁止堆栈/配置泄露 |
| `SECRET_KEY` | 50+ 随机字符 | 不与开发共用 |
| `ALLOWED_HOSTS` | `<正式域名>,127.0.0.1` | 不要用 `*` |
| `SMS_DEV_MODE` | `0` | 必须接真实短信商 |
| `AUTO_APPROVE` | `0` | 必须接内容审核 |
| `IM_MEDIA_SIGN_SECRET` | 32+ 随机字节 | 与 imserver 完全一致 |
| `IM_MEDIA_SIGN_TTL` | `3600` 或更短 | 降低链接转发风险 |
| `REST_FRAMEWORK["NUM_PROXIES"]` | `1` | 按实际代理层数 |
| `SECURE_SSL_REDIRECT` | `True` | HTTPS 后开启 |
| `SESSION_COOKIE_SECURE` | `True` | HTTPS 后开启 |
| `CSRF_COOKIE_SECURE` | `True` | HTTPS 后开启 |
| `SECURE_HSTS_SECONDS` | 先 `3600`，稳定后 `31536000` | 谨慎开启 preload |
| `CSRF_TRUSTED_ORIGINS` | `https://<正式域名>` | HTTPS 后配置 |

### 8.2 关键文件索引

| 文件 | 用途 |
|---|---|
| [settings.py](../../chatapp/config/settings.py) | 安全开关、限流、JWT、媒体签名 |
| [accounts/services.py](../../chatapp/accounts/services.py) | 验证码生成/日志 |
| [accounts/views.py](../../chatapp/accounts/views.py) | 登录、刷新、探针 |
| [accounts/throttles.py](../../chatapp/accounts/throttles.py) | 短信 IP 限流 |
| [notifications/backends.py](../../chatapp/notifications/backends.py) | 短信后端 |
| [users/views.py](../../chatapp/users/views.py) | 资料、照片、在线状态 |
| [discovery/views.py](../../chatapp/discovery/views.py) | 候选、滑卡、配对 |
| [feed/views.py](../../chatapp/feed/views.py) | 动态、点赞、评论、举报 |
| [im/views.py](../../chatapp/im/views.py) | IM 凭证、图片/语音上传、验签 |
| [im/voice.py](../../chatapp/im/voice.py) | ffmpeg 转码 |
| [im/media_sign.py](../../chatapp/im/media_sign.py) | 媒体签名 |
| [ops/views.py](../../chatapp/ops/views.py) | 审核台 |
| [ws_server.cpp](../../imserver/src/net/ws_server.cpp) | WS 鉴权/发送/踢人 |
| [message_service.cpp](../../imserver/src/service/message_service.cpp) | IM 发送逻辑 |
| [user_repo.cpp](../../imserver/src/store/user_repo.cpp) | IM 用户缓存 |
| [token-store.ts](../../web/src/api/token-store.ts) | Web 令牌存储 |
| [token_store.dart](../../app/lib/core/token_store.dart) | App 令牌存储 |

### 8.3 等级定义

| 等级 | 定义 |
|---|---|
| 严重 | 未授权即可接管账号、读取全量敏感数据、远程代码执行或造成不可恢复破坏 |
| 高危 | 可导致大规模数据泄露、持久化控制、后台失陷或合规阻断 |
| 中危 | 需要一定条件（登录、特定输入、网络位置），或造成局部数据/可用性/隐私影响 |
| 低危 | 纵深防御、信息泄露、最佳实践；不直接导致失陷 |

---

## 9. 审计声明

- 本报告为**只读静态审计**，未修改任何代码或配置，未对生产环境发起主动扫描/利用。
- 报告中的生产配置结论基于仓库内最新文档；如服务器 `.env`、nginx、IM 容器环境已变更，请以实际为准并更新本报告。
- 本报告包含可利用细节，请按内部安全文档管理，不要公开传播。
- 建议在每项修复后，由非修改人按“验收标准”复核，并保留测试记录。

---

## 10. 整改进展（2026-10-28）

> 本轮范围：P0+P1（含 imserver H3/H4），**S1/H2/M8 的短信部分按产品决定不修**。
> 代码分支：`fix/security-remediation`；后端全量 563 项、imserver unit 22 / db 18 / 集成脚本全绿。
> 2026-10-28 下午补第二批（M2/M5/M9/L6，保守加固口径），详见
> `docs/superpowers/plans/2026-10-28-security-remediation.md` §4。

| ID | 状态 | 说明 / 证据 |
|---|---|---|
| S1 | **未关闭（已接受）** | 产品决定暂不接短信商、保留固定码；仅限封闭测试，不得对真实用户开放 |
| H1 | **已修复** | HTTPS 已于 2026-10-28 上线；Web 的 refresh 改走 `HttpOnly; SameSite=Strict; Path=/api/v1/auth/` Cookie，access 只留内存（JS 不再持有长期凭证）；App 用 `SecurityContext(withTrustedRoots:false)` 固定 ISRG Root X1 + X2，覆盖 HTTPS 与 WSS，release 包默认强制（`tool/verify_pinning.dart` 已对生产域名握手验证通过）。证据见 `docs/superpowers/plans/2026-10-28-token-hardening.md` |
| H2 | **未关闭（已接受）** | 与 S1 同批；接入短信商时必须一并删除验证码日志 |
| H3 | 已修复 | IM token 增加 `sv`；`im_user.session_version` + `/internal/session_version`；登录任务与 `user_sig` 双重同步，同步失败 503；旧 token 重连 40101 |
| H4 | 已修复 | `im_pair` 表 + `/internal/pair`；发送校验配对（40302）、目标必须存在（不再建行）、每分钟配额、`known_` 上限；上线需跑 `im_sync_pairs` |
| H5 | 部分 | 生产默认 `AUTO_APPROVE=0`，新资料图进 ops 审核队列；机器审核（云内容安全）未接 |
| H6 | 已修复 | 登录失败锁定（账号+IP，5 次/15 分钟）+ TOTP 2FA + `/admin/`、`/ops/` IP 白名单 |
| M1 | 已修复 | `NUM_PROXIES=1`；nginx 模板改为覆盖 `X-Forwarded-For` |
| M2 | 部分 | 资料卡/候选/在线状态已限流；新增抓取广度监控（`PROFILE_SCRAPE_ALERT_PER_HOUR`，超阈值 WARNING）；非配对最小字段按产品决定不做 |
| M3 | 已修复 | 20M 像素上限、解码前检查、`DecompressionBombError` 转 400 |
| M4 | 已修复 | 资料图/广场图/聊天图统一 `exif_transpose` + 重编码，元数据不落盘 |
| M5 | 已修复（进程内） | ffmpeg/ffprobe 加 `-protocol_whitelist file,pipe`、`-nostdin`、`-map_metadata -1`、`-sn -dn`、`-threads 1`；`stdin=DEVNULL`、最小环境、POSIX `setrlimit`（CPU/内存/输出）；**异步化与容器隔离未做**（2C2G 上当前同步转码可接受） |
| M6 | 已修复 | 生产缺密钥启动失败；验签 fail-closed；默认 TTL 3600（整点对齐且至少 1 小时） |
| M7 | 部分 | 候选/`user_sig`/点赞/拉黑/照片上传已限流；磁盘配额与候选池缓存未做 |
| M8 | **未关闭（已接受）** | 短信部分不修；验证码仍固定 |
| M9 | 部分 | 聊天媒体列表加「仅被举报」筛选 + `ops.MediaAccessLog` 访问审计；**资料图/广场图公开直出与防盗链未做**（需签名 URL + 双端改造，按产品决定暂缓） |
| M10 | 已修复 | `limit=-1/abc` 等不再 500；ops 非法 `user`/`ids` 被忽略 |
| M11 | 已修复 | `swipe` 先查双向拉黑，命中返回 404，不产生 Match/灰条 |
| M12 | 已修复 | `session_version` 改 `F()` 自增；举报 `dedupe_key` 唯一约束 + 处理后清空 |
| L1 | 已修复 | `/health`、`/readyz` 加 IP 限流（1200/h） |
| L2 | 已修复 | `X-Request-Id` 只接受 `[A-Za-z0-9._-]{1,64}` |
| L3 | 部分 | `ALLOWED_HOSTS` 无 `*`；部署时按域名收紧 |
| L4 | 已修复 | CORS localhost 仅 `DEBUG` 生效 |
| L5 | 已修复 | 只接受 jpg/png/webp，统一重编码 |
| L6 | 已修复 | `chatapp/requirements.lock` 精确锁定依赖闭包（含 gunicorn），README 改为装 lock；`DependencyLockTests` 守卫漂移 |
| L7 | 已修复 | 生产 443 vhost 已带 HSTS/CSP/XFO/Referrer；后续接第三方 CDN 时需同步改 CSP |
| L8 | 已修复 | App 令牌改存 `flutter_secure_storage`（Android Keystore / iOS Keychain），老用户首启一次性迁移并删除 SharedPreferences 旧键；`AndroidManifest` 关闭 `allowBackup`/`fullBackupContent`；安全存储不可用时降级读写，不会把人锁在登录页 |
| L9 | 部分 | `known_` 已有上限；Origin/端口绑定/探针未全改 |
| L10 | 部分 | JWT `exp <= now` 已改；ops 参数已校验；短信重放窗口保留 |

**复核命令**（与计划文档一致）：

```bash
cd chatapp && python manage.py test
docker compose -f imserver/docker-compose.test.yml run --rm test bash /src/scripts/test_http.sh
docker compose -f imserver/docker-compose.test.yml run --rm test bash /src/scripts/test_integration.sh
```

---

**报告结束**
