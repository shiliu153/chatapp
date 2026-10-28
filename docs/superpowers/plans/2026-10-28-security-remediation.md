# 安全审计整改计划（2026-10-28）

> 依据：[docs/security/2026-10-27-api-security-audit.md](../../security/2026-10-27-api-security-audit.md)
> 范围：P0 + P1 全部（含 imserver H3/H4）。
> **明确排除**：S1、H2、M8 的短信部分 —— 产品决定暂不接短信服务商、保留固定验证码 `123456`。
> 该决定意味着「知道手机号即可登录」的风险仍然存在，属于**已接受风险**，不在本计划内关闭。
> 执行方式：`executing-plans` 内联逐批完成，不派子 agent。
> 每批完成即跑对应测试并勾选，未全绿不进入下一批。

## 0. 验收基线

- 后端：`cd chatapp && python manage.py test`（需 Redis；本机 `TEST_REDIS_PORT=16379`）。
- imserver：`docker compose -f imserver/docker-compose.test.yml run --rm test bash /src/scripts/test_http.sh`。
- App：`cd app && ../flutter/bin/flutter.bat analyze`。
- Web：`cd web && npm run type-check && npm run lint && npm run test:run`。
- 接口文档：任何 `/api/v1` 行为变化同步 `docs/api/`，否则 `ApiDocsCoverageTests` 红。
- 注释规范：新增/修改 `.py` 同步 docstring，否则 `CommentCoverageTests` 红。

## 1. 批次总览

| 批次 | 内容 | 审计项 | 状态 |
|---|---|---|---|
| B1 | 代理/限流/参数校验/日志头 | M1、M10、L2、L3、L4 | [x] |
| B2 | 图片与媒体签名 | M3、M4、M6、L5 | [x] |
| B3 | 业务接口加固 | M11、M12、M2、M7、L1 | [x] |
| B4 | IM token 绑定会话版本 | H3 | [x] |
| B5 | IM 发送校验配对/目标存在/配额 | H4 | [x] |
| B6 | 后台登录限流 + 2FA + IP 白名单 | H6 | [x] |
| B7 | 内容审核开关与队列 | H5 | [x]（机器审核仍未接） |
| B8 | HTTPS/安全头（代码侧，待域名） | H1、L7 | [x]（代码/模板就绪，证书待办） |
| B9 | 全量回归、文档、核对单 | 全部 | [x] |

---

## B1. 代理 / 限流 / 参数校验 / 日志头

### B1.1 M1 伪造 XFF 绕过 IP 限流

- [ ] `settings.REST_FRAMEWORK["NUM_PROXIES"] = int(os.getenv("NUM_PROXIES", "1"))`。
- [ ] nginx 部署文档改为 `proxy_set_header X-Forwarded-For $remote_addr;`（覆盖客户端传入值）。
- [ ] 测试：伪造 `X-Forwarded-For` 不改变限流 key（DRF `get_ident` 单测或视图级测试）。

### B1.2 M10 非法参数 500

- [ ] 抽 `config/params.py`：`int_param(request, name, default, minimum, maximum)`，非法值抛 `ValidationError`（400 统一信封）。
- [ ] `discovery.candidates` 的 `limit` 用该函数（`limit=-1/abc/0/999` 均不 500）。
- [ ] `ops` 的 `user`、`ids`、`date`、`limit` 参数统一校验。
- [ ] 测试：参数化边界用例。

### B1.3 L2 X-Request-Id 客户端可控

- [ ] 中间件只接受 `[A-Za-z0-9._-]{8,64}`，否则重新生成 UUID；响应头回显清洗后的值。
- [ ] 测试：超长/换行/控制字符被替换。

### B1.4 L3/L4 Host 与 CORS

- [ ] `CORS_ALLOWED_ORIGIN_REGEXES` 仅在 `DEBUG` 下包含 localhost；生产不放开。
- [ ] `ALLOWED_HOSTS` 不含 `*`（已有则移除）；部署文档强调。
- [ ] 测试：`DEBUG=0` 时 localhost 不在 CORS 白名单。

---

## B2. 图片与媒体签名

### B2.1 M3 像素上限 / 解压炸弹

- [ ] 新增 `chatapp/config/images.py`（或 `users/images.py`）：
  - `MAX_IMAGE_PIXELS = 20_000_000`；`Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS`。
  - `open_checked(file)`：先 `Image.open` 读 `size`，`width*height > MAX` 抛 `ImageTooLarge`；
    捕获 `Image.DecompressionBombError/Warning`。
- [ ] 三个入口统一：聊天图（`im/views.upload_image`）、资料图（`users`）、广场图（`feed`）。
- [ ] 测试：12000×12000 纯色 PNG 返回 400；正常 5MB 图仍可上传。

### B2.2 M4/L5 EXIF/GPS 剥离 + 统一重编码

- [ ] 新增 `normalize_image(image)`：`ImageOps.exif_transpose` → `convert("RGB")` → 重编码 JPEG（quality 85），
  不带 EXIF；超过最大边先缩到 4096。
- [ ] 聊天图：无论 orientation 是否为 1 都重编码，不再直接存原始字节。
- [ ] 资料图、广场图：保存前重编码；只允许 jpg/png/webp（校验 content_type + PIL 实际格式）。
- [ ] 测试：带 GPS EXIF 的 JPEG 上传后读回无 EXIF；方向正确。

### B2.3 M6 媒体签名 fail-closed + TTL

- [ ] `media_sign.verify()`：未配置密钥时在 `DEBUG=0` 返回 `False`（fail-closed），`DEBUG=1` 保持放行。
- [ ] 启动断言：`not DEBUG and not IM_MEDIA_SIGN_SECRET` → `ImproperlyConfigured`。
- [ ] `IM_MEDIA_SIGN_TTL` 默认 3600；`.env.example` 与部署核对单同步。
- [ ] 测试：空密钥 + `DEBUG=0` 时验签拒绝；过期/篡改 403。

---

## B3. 业务接口加固

### B3.1 M11 swipe 校验拉黑

- [ ] `swipe` 在创建 `Swipe` 前检查双向 `Block`，有拉黑关系返回 404。
- [ ] 配对通知前再校验一次；已解除配对不复活（已有）。
- [ ] 测试：A 拉黑 B 后 B 对 A 滑卡 404，不产生 Match/灰条。

### B3.2 M12 会话版本竞态 + 举报去重

- [ ] `accounts/views.py` 登录：`User.objects.filter(pk=...).update(session_version=F("session_version")+1)`，
      `refresh_from_db` 后再签发 JWT。
- [ ] `Report` 增加可空 `dedupe_key` + 唯一约束；创建时 `get_or_create(dedupe_key=...)`，
      处理时置 `NULL`；捕获 `IntegrityError` 回查。
- [ ] 迁移 + 测试：并发登录只有一个 token 有效（尽力而为）；并发举报只一条 pending。

### B3.3 M2/M7 限流与高开销接口

- [ ] 新增 throttle：`public_profile` 120/h、`candidates` 60/h、`presence` 120/h、`user_sig` 30/h、
      `post_like` 120/h、`blocks` 60/h、`upload_photo` 20/h。
- [ ] 测试：超限 429。

### B3.4 L1 探针

- [ ] `/health`、`/readyz` 返回最小信息；加 IP 限流（或仅内网，部署文档）。
- [ ] 测试：连续请求触发 429 或保持 200 但有限流配置。

---

## B4. H3 IM token 绑定会话版本

### B4.1 Django 侧

- [ ] `im/token.py::mint_im_token(user_id, ttl, session_version)` 增加 `sv` claim。
- [ ] `im/views.user_sig`：自建分支先同步会话版本到 imserver（`POST /internal/session_version`），
      失败返回 503（fail-closed），成功再签发 token。
- [ ] `im/self_client.py::set_session_version(uid, version)`。
- [ ] 测试：token 含 `sv`；同步失败不签发。

### B4.2 imserver 侧

- [ ] 迁移 `003_session_version.sql`：`im_user.session_version BIGINT NOT NULL DEFAULT 0`。
- [ ] `TokenClaims` 增加 `sv`（缺省 0）；`verify_token` 解析。
- [ ] `UserRepo::session_version(uid)` + `set_session_version`。
- [ ] `handle_auth`：`claims.sv != 0 && claims.sv != stored` → `40101`，关闭 4002。
- [ ] 内部 API `POST /internal/session_version`。
- [ ] 测试：旧 sv 重连被拒；新 sv 通过；内部 API 更新后旧 token 失效。

### B4.3 兼容与回滚

- [ ] 无 `sv` 的旧 token 在过渡期内放行（最多 24h），文档注明；
- [ ] 回滚：镜像回退 + `IM_REQUIRE_SESSION_VERSION=0`（可选开关）。

---

## B5. H4 IM 发送校验配对

### B5.1 数据与同步

- [ ] 迁移 `004_pair.sql`：`im_pair(user_a,user_b,created_at)`，主键 `(user_a,user_b)`，`user_a<user_b`。
- [ ] imserver 内部 API `POST /internal/pair`（`add`/`remove`）。
- [ ] Django：配对创建后 `add`；解除配对/拉黑后 `remove`（事务提交后，Celery 任务，失败重试）。
- [ ] 管理命令 `im_sync_pairs`：按现有 `Match` 全量回填（幂等）。

### B5.2 发送校验

- [ ] `MessageService::send`：`from != 0` 时校验 `pair_exists(from,to)`，否则 `40302`。
- [ ] 目标必须存在：`users_.get(lease, to)` 为空 → `42201`，不再 `ensure` 建行。
- [ ] `known_` 加上限（默认 100000，超限清空并记日志）。
- [ ] 发送配额：Redis `im:sendq:{uid}:{minute}`，默认 120 条/分钟（`IM_SEND_PER_MINUTE`）。
- [ ] 测试：未配对 40302；配对后成功；随机 uid 不建行；系统通知（from=0）放行。

---

## B6. H6 后台登录加固

- [ ] 登录失败计数（账号 + IP，5 次锁 15 分钟），`/admin/` 与 `/ops/login/` 共用。
- [ ] TOTP 2FA（`pyotp`）：`User.totp_secret` 字段 + 迁移；staff 登录后强制验证；
      未绑定则进入绑定页（显示 secret/otpauth URI）；恢复码可选。
- [ ] `OPS_ALLOWED_IPS` 中间件：`/admin/`、`/ops/` 仅白名单 IP；未配置时记录 warning（不阻断）。
- [ ] 测试：5 次失败锁定；无 2FA 不能进 ops；白名单外 403。

---

## B7. H5 内容审核开关

- [ ] 生产默认 `AUTO_APPROVE=0`（`DEBUG=0` 时默认 0；`DEBUG=1` 保持 1）。
- [ ] 新照片 `pending` 进入 ops 审核队列（确认队列已存在且可用）。
- [ ] 聊天图片/语音：保留人工抽审；在 ops 增加「待抽审」筛选（如已有则只补文档）。
- [ ] 机器审核（云内容安全）仍为**未关闭项**，在报告与上线核对单中标注。

---

## B8. H1/L7 HTTPS 与安全头（代码侧）

- [ ] `HTTPS_ENABLED=1` 时启用：`SECURE_PROXY_SSL_HEADER`、`SECURE_SSL_REDIRECT`、
      `SESSION_COOKIE_SECURE`、`CSRF_COOKIE_SECURE`、`SECURE_HSTS_SECONDS`（默认 3600）、
      `SECURE_HSTS_INCLUDE_SUBDOMAINS`、`CSRF_TRUSTED_ORIGINS`。
- [ ] nginx 模板：80→443、HSTS、CSP、X-Frame-Options、X-Content-Type-Options、Referrer-Policy。
- [ ] `manage.py check --deploy` 在 `HTTPS_ENABLED=1` 下无 W004/W008/W012/W016。
- [ ] 域名/证书到位后才能验收，代码与文档先行。

---

## B9. 回归与文档

- [ ] 后端全量测试绿；App analyze 零告警；Web type-check/lint/test 绿。
- [ ] imserver unit + db 测试绿。
- [ ] `docs/api/` 同步（如有接口行为变化）。
- [ ] 更新 `docs/pitfalls/backend.md` / `im.md`（新增的坑与约定）。
- [ ] 更新审计报告每项「状态」列：已修复/部分修复/未关闭（附证据）。
- [ ] 更新上线核对单（HTTPS、2FA、媒体密钥、配对校验）。

---

## 3. 执行记录（2026-10-28）

- 分支：`fix/security-remediation`。
- 后端全量：`python manage.py test` → **545 项通过**（Redis 测试端口 16379）。
- imserver：unit **22 项**、db **18 项**、集成脚本（history/internal/image/search/send/e2e）全过。
- `python manage.py check --deploy`（`DEBUG=0` + `HTTPS_ENABLED=1` + 已配媒体密钥）：
  仅剩 `security.W021`（HSTS preload，故意不默认开）。
- 新增迁移：
  - Django `moderation.0002_report_dedupe_key`、`accounts.0003_user_totp_secret`；
  - imserver `003_session_version.sql`、`004_pair.sql`。
- 新增命令：`python manage.py im_sync_pairs [--dry-run]`（上线 H4 前必须跑一次回填）。

### 3.1 各批落地位置

| 批次 | 主要文件 |
|---|---|
| B1 | `config/params.py`、`config/middleware.py`、`config/settings.py`、`discovery/views.py`、`ops/views.py` |
| B2 | `config/images.py`、`im/views.py`、`im/media_sign.py`、`users/views.py`、`feed/views.py` |
| B3 | `discovery/views.py`、`accounts/views.py`、`moderation/models.py`、`config/throttling.py`、各 `throttles.py` |
| B4 | `im/token.py`、`im/views.py`、`im/client.py`、`im/self_client.py`、`im/tasks.py`、`imserver/src/{auth,store,net}` |
| B5 | `imserver/src/service/message_service.cpp`、`imserver/src/net/http_api.cpp`、`im/tasks.py`、`im_sync_pairs` |
| B6 | `accounts/backends.py`、`accounts/totp.py`、`ops/middleware.py`、`ops/otp.py`、`ops/templates/ops/otp.html` |
| B7 | `config/settings.py`（`AUTO_APPROVE` 生产默认 0） |
| B8 | `config/settings.py`（`HTTPS_ENABLED`）、`docs/ops/nginx-security.conf` |

### 3.2 上线顺序（重要）

1. 先部署 Django 与 imserver 新版本;**imserver 的迁移是显式步骤**(entrypoint 不自动跑):
   `docker compose run --rm imserver --migrate` 再 `docker compose up -d`。
2. 立刻跑 `python manage.py im_sync_pairs` 回填现有配对(并补齐缺失的 `im_user` 行),否则老用户会发不出消息。
3. 观察 IM 发送 40302 日志；确认没有正常配对用户被误拒。
4. 配置 `OPS_OTP_REQUIRED=1` 后，**第一个登录后台的运营账号会被要求绑定 TOTP**；
   绑定前请先安装验证器 App（Google Authenticator / 微软 Authenticator 均可）。
5. 域名/证书到位后再打开 `HTTPS_ENABLED=1`，并按 `docs/ops/nginx-security.conf` 替换 nginx。

### 3.3 仍需外部条件/后续立项

- S1/H2/M8：用户明确决定暂不接短信商、保留固定验证码；**这是仍未关闭的严重风险**。
- H1：`shiliu153.cn` 已备案且证书可用，但 443 当前指向简历站；交友 App 的 `https://chat.shiliu153.cn` 切换任务见 [2026-10-28-chat-shiliu153-cn-https.md](2026-10-28-chat-shiliu153-cn-https.md)。Web token 仍在 `localStorage`（需 BFF + HttpOnly Cookie）；App 未做证书绑定。
- H5：无内容安全服务商，图片/语音只有人工抽审；`AUTO_APPROVE=0` 已让新资料图进审核队列。
- M2：非配对用户仍能看到完整公开资料（只加了限流，未裁剪字段）。
- M5：ffmpeg 未加协议白名单/容器隔离。
- M7：磁盘配额、候选池缓存未做。
- M9：ops 仍可浏览全量私聊媒体；资料图/广场图仍公开直出。
- L6：依赖仍未锁定版本。

---

## 2. 明确不做的项（已接受风险）

| 项 | 原因 | 备注 |
|---|---|---|
| S1 固定验证码 | 产品决定不接短信商 | 知道手机号即可登录；仅限封闭测试 |
| H2 验证码日志 | 同上（固定码本身公开） | 接入短信商时必须一并修 |
| M8 CSPRNG/锁定策略 | 同上 | 固定码场景无意义 |
| H5 机器审核 | 无内容安全服务商 | 仅做默认 pending + 人工队列 |
| H1 证书/域名 | 域名未备案 | 代码与 nginx 模板先行 |
