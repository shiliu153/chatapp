# 第二轮安全整改计划（2026-10-28）

> 依据：[docs/security/2026-10-28-api-security-audit-round2.md](../../security/2026-10-28-api-security-audit-round2.md)
> 范围：本轮审计的 3 高危 + 8 中危（M-4/M-5 记录不改）+ 6 低危。
> 执行方式：`executing-plans` 内联逐批完成，不派子 agent。
> 每批完成即跑对应测试并勾选，未全绿不进入下一批。

## 0. 验收基线

- 后端：`cd chatapp && python manage.py test`（需 Redis；本机 `TEST_REDIS_PORT=16379`）。
- imserver：`docker compose -f imserver/docker-compose.test.yml run --rm test bash /src/scripts/test_http.sh`。
- Web：`cd web && npm run type-check && npm run lint && npm run test:run`。
- App：`cd app && ../flutter/bin/flutter.bat analyze`。
- 接口文档：任何 `/api/v1` 行为变化同步 `docs/api/`，否则 `ApiDocsCoverageTests` 红。
- 注释规范：新增/修改 `.py` 同步 docstring，否则 `CommentCoverageTests` 红。

## 1. 批次总览

| 批次 | 内容 | 项 | 状态 |
|---|---|---|---|
| A | 会话吊销 / 密钥断言 / 验证码 | H-1、H-2、H-3 | [x] |
| B | 配额顺序 / IM HTTP 限流 / 可信代理 / OTP / 解析 | M-1、M-2、M-3、M-6、M-7、M-8 | [x] |
| C | 并发与边角 | L-1、L-2、L-4、L-5、L-6、L-7 | [x] |
| D | 回归、文档与核对单 | 全部 | [x] |

---

## A. 会话吊销 / 密钥断言 / 验证码

### A.1 H-1 IM HTTP 校验会话版本

- [x] `HttpApi::authenticate`：`claims.sv != 0` 时与 `im_user.session_version` 比对，不一致返回空（401）。
- [x] 复用 WS 的 `sv` 语义：`sv=0` 的旧 token 过渡期放行。
- [x] 测试：旧 `sv` token 请求 `/im/api/messages` → 401；新 token → 200。

### A.2 H-2 SECRET_KEY 生产断言

- [x] `config/settings.py`：`not DEBUG` 且 `SECRET_KEY` 仍是默认常量 → `ImproperlyConfigured`。
- [x] 测试：`override_settings` 无法覆盖模块级断言，改为直接调用校验函数/子进程检查。

### A.3 H-3 验证码日志与 CSPRNG

- [x] `accounts/services.issue_code`：验证码改用 `secrets.randbelow`；日志只在 `SMS_DEV_MODE` 下打，且脱敏手机号。
- [x] `notifications/backends.ConsoleSmsBackend`：`SMS_DEV_MODE=0` 时不打码，改记 error「短信商未接入」。
- [x] 测试：`SMS_DEV_MODE=0` 时 `assertLogs` 中不出现 6 位码；生成码为 6 位数字。

---

## B. 配额 / 限流 / 可信代理 / OTP / 解析

### B.1 M-1 配额先于落盘

- [x] `im/views.upload_image`：先算原图 + 缩略图字节并 `ensure_quota`，再 `file.save` / `thumb.save`。
- [x] 失败路径不留文件（测试断言存储目录无新增）。

### B.2 M-2 IM HTTP 限流

- [x] `HttpApi`：把 `allow_search` 泛化为按账号的 API 令牌桶（默认 120/min、burst 40），
      `conversations` / `messages` / `search` 共用；search 保留更严的独立桶（60/min、burst 20）。
- [x] 超限返回 429 + `42901`。
- [x] 测试：同一 uid 连续请求触发 429。

### B.3 M-3 client_ip 只信可信代理

- [x] 新增 `settings.TRUSTED_PROXY_IPS`（默认 `127.0.0.1,::1`，支持 CIDR）。
- [x] `config/net.client_ip`：仅当 `REMOTE_ADDR` 命中可信代理时才采信 `X-Real-IP` / XFF 末段。
- [x] `docs/ops/nginx-security.conf`：`/ops/`、`/admin/` 显式覆盖 `X-Real-IP` / `X-Forwarded-For`。
- [x] 测试：非回环 `REMOTE_ADDR` + 伪造头 → 返回真实地址。

### B.4 M-6 OTP 有效期

- [x] `otp_verified_at` 时间戳替代布尔；中间件按 `OPS_OTP_TTL`（默认 12h）判定。
- [x] 测试：超时后重定向到 OTP 页。

### B.5 M-7 ops id 解析

- [x] `ops.photo_review`：`try: int(value)`，非法值丢弃；上限 500 个。
- [x] 测试：`ids=²` 返回 200。

### B.6 M-8 WS uid 严格解析

- [x] `ws_server.cpp`：`parse_uid` 要求整串数字；`handle_send` 复用它。
- [x] 测试：`u12abc` → 42201。

---

## C. 并发与边角

- [x] L-1 `sms_verify`：`get_or_create` 捕获 `IntegrityError` 后回查。
- [x] L-2 `PostReport`：`dedupe_key` 字段 + 唯一约束 + 迁移，创建走 `get_or_create`，处理时清空。
- [x] L-4 刷新/注销端点：`Origin` 存在时校验同源，不同源 403。
- [x] L-5 `logout`：加 IP 限流（scope `logout`，60/hour）。
- [x] L-6 `_safe_redirect`：`ALLOWED_HOSTS` 为空时只允许站内相对路径。
- [x] L-7 imserver：`IM_MEDIA_SIGN_SECRET` 为空时启动告警（不 fatal，避免打断本地/测试）。

---

## D. 回归与文档

- [x] 后端全量绿；imserver unit + db + 集成绿；Web type-check/lint/test 绿；App analyze 零告警。
- [x] 更新审计报告 §3/§5 状态列与证据。
- [x] 更新 `docs/pitfalls/backend.md` / `docs/pitfalls/im.md` 新增的坑。
- [x] 更新 `docs/api/`（如 `logout` 限流、举报去重行为有变化）。

## E. 上线动作（2026-10-29 已执行）

- [x] 后端：`python manage.py migrate`（新增 `feed.0004_postreport_dedupe_key`，会给存量待处理举报回填去重键）。
- [x] 后端 `.env`：确认 `SECRET_KEY` 不是开发默认值（否则 `DEBUG=0` 下进程起不来）；确认 `TRUSTED_PROXY_IPS` 保持默认回环，不要写公网网段。
- [x] nginx：线上 vhost 的 `location ~ ^/(api|admin|ops)` 已显式 `proxy_set_header X-Real-IP $remote_addr` / `X-Forwarded-For $remote_addr`，无需改动。
- [x] imserver：重建镜像并替换（`http_api` / `token` / `ratelimit` / `ws_server` 均有改动）；启动日志确认没有 `media_sign_disabled`。
- [x] 回归：旧设备（被顶下线）调 `/im/api/conversations` 应 401/40101；正常设备 200。
- [ ] 运营：升级后第一次进 `/ops/` 会被要求重新输一次 TOTP（`otp_verified_at` 时间戳替代旧布尔标记），属预期（待运营下次登录时自然触发）。

## F. 执行记录（2026-10-29 17:37–17:55，生产）

> 说明：服务器原 HEAD 为 `7930bf2`（10-28 的 bundle 线），本次 `git reset --hard origin/master` 一并带上了 M7（存储配额/候选池）与 L9（imserver 入口防护），因此额外执行了 M7 的迁移、回填与计划任务。

| 时间 | 动作 | 结果 |
|---|---|---|
| 17:37 | 备份：分支 `backup/pre-round2-20261029-1737`、`chatapp/.env`、`imserver/.env`、`/root/chatapp_backup_20261029-1737.sql`（164K） | 完成 |
| 17:39 | `git reset --hard origin/master` → `80340e7` | 完成 |
| 17:40 | `pip install -r requirements.lock`（首次落 lock） | 完成 |
| 17:40 | `migrate`：`feed.0003`、`feed.0004`、`ops.0001`、`users.0005` | 4 个迁移 OK |
| 17:40 | `media_bytes_backfill`：资料图 46 行、动态图 21 行 | 完成 |
| 17:41 | `collectstatic`（127 文件）+ `check --deploy`（仅 W021） | 完成 |
| 17:41 | 重启 `chatapp-web:*` / `chatapp-celery:*` | RUNNING |
| 17:42 | 补 3 条 cron：03:40 `refresh_shuffle_keys`、04:10 `media_cleanup --apply`、04:20 `media_disk_report --fail-over` | 已写入 root crontab |
| 17:43 | 本地构建并上传 `imserver:80340e7`（81MB gz）→ `docker load` → `--migrate`（v1–v4 全 skip）→ `up -d` | 容器已换新镜像 |
| 17:42 | Web `npm run build` 后覆盖 `dist`（index 由 `BZl6fh0W` → `B6fZxN7L`） | 完成 |
| 17:50 | 验收：`/api/v1/health` 200、`readyz` 200、`/app/config` 1.0.1；WS `auth_ok`、错误 `sv` → `40101`；HTTP 旧 token 200、错误 `sv` → `401 40101`；媒体无签名 403 / 签名 200；45 次读请求后 429；默认 `SECRET_KEY` 启动抛 `ImproperlyConfigured` | 全过 |

回退：`git reset --hard backup/pre-round2-20261029-1737` + 恢复 `.env` 备份 + `IMSERVER_IMAGE` 改回 `imserver:7930bf2` + `docker compose up -d` + 重启 web/celery（迁移不回滚，代码向前兼容）。
