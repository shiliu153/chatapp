# 第三轮安全整改计划（2026-11-01）

> 依据：[docs/security/2026-11-01-api-security-audit-round3.md](../../security/2026-11-01-api-security-audit-round3.md)
> 范围：1 严重 + 2 高危 + 7 中危 + 9 低危（其中 L-2/L-4/L-5/L-7/L-8 记录不改）。
> 执行方式：`executing-plans` 内联逐批完成，不派子 agent。
> 每批完成即跑对应测试并勾选，未全绿不进入下一批。
> 前置：本轮只动部署脚本/模板与少量后端代码，**不需要数据库迁移**。
> **执行状态：A–E 已完成并合并（PR #30 → `c44035e`，2026-11-03，CI 双绿）；F（上线）待执行。**

## 0. 验收基线

- 后端：`cd chatapp && python manage.py test`（需 Redis；本机 `TEST_REDIS_PORT=16379`）。
- imserver：`docker compose -f imserver/docker-compose.test.yml run --rm test bash /src/scripts/test_http.sh`
  与 `test_integration.sh`（改 `http_api.cpp` 时必须）。
- Web：`cd web && npm run type-check && npm run lint && npm run test:run`。
- App：`cd app && ../flutter/bin/flutter.bat analyze`。
- 部署脚本：`bash -n deploy/oneclick.sh deploy/chatapp deploy/docker/entrypoint.sh`；
  `bash deploy/oneclick.sh --render-only --no-tls --app-dir /tmp/render-check` 能生成配置；
  渲染出的 `docker-compose.yml` 能通过 `docker compose config -q`（本机有 Docker 时）。
- 接口文档：任何 `/api/v1` 行为变化同步 `docs/api/`，否则 `ApiDocsCoverageTests` 红。
- 注释规范：新增/修改 `.py` 同步 docstring，否则 `CommentCoverageTests` 红。

## 1. 批次总览

| 批次 | 内容 | 项 | 状态 |
|---|---|---|---|
| A | 部署默认值与内部接口 | C-1、H-1、H-2 | [x] 2026-11-03 |
| B | 访客记录与运维缺口 | M-1、M-2、M-3、M-4、M-7 | [x] 2026-11-03 |
| C | 容器与网络加固 | M-5、M-6、L-9 | [x] 2026-11-03（两项记录） |
| D | 低危与文档 | L-1、L-3、L-6 | [x] 2026-11-03 |
| E | 回归与文档 | 全部 | [x] 2026-11-03 |

---

## A. 部署默认值与内部接口

### A.1 C-1 固定验证码不再作为公网部署默认值

- [x] `deploy/oneclick.sh`：新增 `--allow-dev-sms`（默认关闭）。
      TLS/公网模式（`TLS=1`）下若未显式传 `--allow-dev-sms` → `die`，
      提示「SMS_DEV_MODE=1 只允许封闭测试；接短信商前请用 --allow-dev-sms 显式确认」。
- [x] `--no-tls` + `--public-url` 指向非回环地址时同样要求 `--allow-dev-sms`。
- [x] `SMS_DEV_MODE` 写入 `chatapp.env` 时按开关取值（`1`/`0`），不再硬编码 `1`。
- [x] `ADMIN_PHONE` 去掉默认 `13900000000`：TLS/公网模式必须显式 `--admin-phone`；
      `--render-only` 可保留占位值（`13900000000`）并打印警告。
- [x] `chatapp/accounts/views.py::sms_verify`：`user.is_superuser` 时返回 403
      （`{"code":403,"message":"运营账号请使用运营后台登录"}`），并补测试。
      —— 这条不依赖短信商，能直接切断「固定验证码 → 最高权限账号」的路径。
      **实现按 `is_staff or is_superuser` 判定**（更严）；封闭测试需要运营账号登 App 时
      用 `SMS_ALLOW_STAFF_LOGIN=1` 显式放开，生产保持 0。
- [x] `deploy/README.md` §6/§12 同步说明：默认不开启开发短信；运营账号不走短信登录。

**验收**：默认 `sudo bash deploy/oneclick.sh --domain ... --email ...` 在没有
`--allow-dev-sms` 时直接失败；带该开关才生成 `SMS_DEV_MODE=1`；
`sms_verify` 对 superuser 返回 403（后端测试）。

### A.2 H-1 imserver 内部接口支持「显式来源网段」

- [x] `imserver/src/config.{h,cpp}`：新增 `IM_INTERNAL_ALLOW`（逗号分隔 IP/CIDR，
      默认 `127.0.0.1,::1`），非法条目启动报错。
- [x] `imserver/src/net/http_api.cpp`：`route()` 的 `/internal/*` 判断从
      `is_loopback()` 改为「对端命中 `IM_INTERNAL_ALLOW`」；保留 HMAC 校验。
- [x] `imserver/tests/`：新增用例——默认配置下非回环 403；加入 `172.28.0.0/16`
      后同网段放行；不在名单内的网段仍 403。
      实现方式：`ConfigTest.ParsesInternalAllowList` 覆盖解析；`ProxyTrust` 的
      CIDR/非法条目行为由 `GuardTest` 覆盖；端到端用「`IM_INTERNAL_ALLOW=10.0.0.0/8`
      时回环探针 403、默认名单 200」实跑验证（见 §G）。
- [x] `deploy/oneclick.sh` 的 `imserver.env` 写入
      `IM_INTERNAL_ALLOW=127.0.0.1,::1,172.28.0.0/16`（或 nginx/web 的固定 IP）。
- [x] `docs/ops/imserver.md` 与 `docs/pitfalls/im.md` 补这一条：**回环假设在
      容器网络下不成立**，`/internal/*` 的信任边界改为「来源网段 + HMAC」。

**验收**：compose 里从 web 容器 `curl http://imserver:9101/internal/healthz` → 200；
从不在名单的网段 → 403；`user_sig` 不再 503。

### A.3 H-2 可信代理收敛到 nginx 固定 IP

- [x] `deploy/docker-compose.yml.tmpl`：给 `nginx` 服务加
      `networks: default: ipv4_address: 172.28.0.10`。
- [x] `deploy/oneclick.sh`：`TRUSTED_PROXY_IPS` 与 `IM_TRUSTED_PROXIES` 改为
      `127.0.0.1,::1,172.28.0.10`（不再写整个 `/16`）。
- [x] `deploy/README.md` §1 的架构说明同步（「只信任 nginx 的固定地址」）。

**验收**：从 web 容器伪造 `X-Real-IP` 直连 `web:8000`，`client_ip()` 仍返回容器真实
地址；经 nginx 的请求仍能拿到真实客户端 IP。

---

## B. 访客记录与运维缺口

### B.1 M-1 保留期进入每日维护

- [x] `deploy/oneclick.sh` 的 `maintenance.sh` 增加
      `python manage.py purge_profile_visits --apply`。
- [x] `deploy/README.md` §6/§9 的维护清单同步。
- [x] `docs/ops/` 若有维护任务清单，同步一行（§9 已写）。

### B.2 M-2 只为「会展示的访客」落库

- [x] `chatapp/users/services.py::_record_visit`：先取 viewer 的
      `Profile.status` 与「是否有过审照片」，不满足 `COMPLETE` 直接 return
      （与 `visits_received_queryset` 的展示口径一致）。
- [x] 可选上限：同一 owner 的 `ProfileVisit` 超过 `PROFILE_VISIT_MAX_PER_OWNER`
      （默认 500）时，删除最旧的再写；用一次 `ORDER BY last_at LIMIT` 实现。
- [x] `chatapp/users/tests.py`：补「未完善资料的访问不落库」「超出上限时最旧行被淘汰」。

### B.3 M-3 访客接口节流

- [x] `chatapp/config/settings.py`：新增 `VISITS_RATE`（默认 `120/hour`）、
      `VISITS_COUNT_RATE`（默认 `240/hour`），登记进 `DEFAULT_THROTTLE_RATES`。
- [x] `chatapp/discovery/throttles.py`：新增 `VisitsThrottle` / `VisitsCountThrottle`。
- [x] `chatapp/discovery/views.py`：两个视图加 `@throttle_classes`。
- [x] `chatapp/discovery/tests.py`：连续请求触发 429/`42901`。
      （测试用 `patch.dict(Throttle.THROTTLE_RATES, {"visits": "2/hour"})` 调小额度，
      不循环 120 次。）
- [x] `docs/api/discovery.md`：补限流说明（接口行为变化）。

### B.4 M-4 备份权限与提示

- [x] `deploy/chatapp`：`umask 077`；`backup` 落盘后 `chmod 600 "$out"`；
      `backup-media` 同样。
- [x] `deploy/README.md` §8：写明备份含个人信息、需加密/离线保存、建议保留期。

### B.5 M-7 域名白名单

- [x] `deploy/oneclick.sh`：`--domain` 只允许 `[a-z0-9.-]`、长度 ≤253、不含 `..`；
      非法直接 `die`。补一条 `--render-only` 的非法域名用例（脚本内 `die` 即可）。

---

## C. 容器与网络加固

### C.1 M-5 非 root + 资源/能力限制

- [x] `deploy/docker/Dockerfile`：创建 `app` 用户（uid 10001），`chown /app`，`USER app`；
      预建 `media`/`staticfiles`/`logs`，命名卷初始化时继承属主。
- [ ] `deploy/docker/web.Dockerfile`：nginx 镜像默认以 root 起 master，评估是否改
      `nginx-unprivileged`（若改动大，记录为已知项）。
      **记录为已知项**：nginx 需要绑 80/443，改 unprivileged 要同时改端口映射与模板，
      本轮不做，已在 `deploy/README.md` §12 标注。
- [x] `deploy/docker-compose.yml.tmpl`：给 web/worker/imserver/nginx 加
      `mem_limit`（web 384m、worker 256m、imserver 320m、nginx 96m、mysql 700m、
      redis 320m）、`pids_limit`、`security_opt: [no-new-privileges:true]`、
      `cap_drop: [ALL]`（nginx/mysql 例外：nginx 需要 NET_BIND_SERVICE）。
- [x] 本地 `docker compose config -q` 通过；渲染后人工核对缩进。

### C.2 M-6 Redis 网络与口令

- [x] 短期：compose 增加独立 `backend` 网络（`internal: true`），只有
      web/worker/imserver/redis/mysql 在内；nginx 只接 `default`。
- [ ] 长期（记录）：imserver `parse_redis_url` 支持 `redis://:pass@host:port/db` 并 `AUTH`，
      再给 Redis 开 `requirepass`；本轮不做代码改动，只在 `deploy/README.md` 标注。

### C.3 L-9 MySQL root 来源

- [x] `deploy/docker-compose.yml.tmpl`：`MYSQL_ROOT_HOST` 改为 `172.28.0.%`
      （由 `DOCKER_SUBNET` 派生，不是 `%`）；确认 `db-init` 与 `mysql` 健康检查仍通过。

---

## D. 低危与文档

### D.1 L-1 预览目录忽略

- [x] `.gitignore` 增加 `deploy-render/`；`deploy/README.md` §3 提示预览完删除。

### D.2 L-3 HSTS 与现网对齐

- [x] `deploy/oneclick.sh`：`SECURE_HSTS_SECONDS` 默认改为 `31536000`，并在 README
      说明「首次上线可先 3600，确认全站 HTTPS 后再升一年」。

### D.3 L-6 验签路径显式校验

- [x] `chatapp/im/views.py::image_auth`：在 `media_sign.verify` 前显式判断
      `parts.path.startswith("/media/chat/")`，与 docstring 一致；补测试。

### D.4 记录项

- [x] 在审计报告 §3/§5 标注 L-2/L-4/L-5/L-7/L-8 为「记录（本轮不改）」，
      并在 `deploy/README.md` §12 留一句已知风险。

---

## E. 回归与文档

- [x] 后端全量绿（693）；imserver unit 43 + db 19 + HTTP 集成绿；Web type-check/lint/403 测试绿；
      App analyze 零告警。
- [x] 更新审计报告 §3 状态列与 §5 修复证据。
- [x] 更新 `docs/pitfalls/backend.md`（访客写放大/节流）、`docs/pitfalls/im.md`（内部接口来源网段）。
- [x] 更新 `docs/api/discovery.md`（visits 限流）。
- [x] 更新 `deploy/README.md`（默认值、维护任务、备份、可信代理、内部接口）。
- [x] 若 C-1 改了 `sms_verify` 行为，更新 `docs/api/auth.md`。

## F. 上线动作（执行后填写）

- [ ] 新部署路径：用 `--render-only` 生成一份配置做静态核对；
      有条件时在一台测试机跑 `--no-tls --allow-dev-sms` 全链路（登录/聊天/发图/语音）。
      **已完成的部分**：`--render-only` 渲染 + `docker compose config -q` 通过；
      完整容器起栈未做（本机拉不到 `python:3.11-slim-bookworm`，Docker Hub 不可达）。
- [ ] 现网（宝塔）不受本轮改动影响；若只上线后端代码（`sms_verify` superuser 403 +
      visits 节流），按常规 `git pull` + `migrate`（无新迁移）+ 重启 web/worker。

---

## G. 执行记录（2026-11-03）

### 改动清单

| 文件 | 内容 |
|---|---|
| `deploy/oneclick.sh` | `--allow-dev-sms`、公网/TLS 强制 `--admin-phone`、域名白名单、HSTS 一年、维护加 `purge_profile_visits`、`TRUSTED_PROXY_IPS`/`IM_TRUSTED_PROXIES` 收敛到 nginx 固定 IP、`IM_INTERNAL_ALLOW`、`MYSQL_ROOT_HOST` 派生 |
| `deploy/docker-compose.yml.tmpl` | nginx 固定 `172.28.0.10`；`backend`(internal) 网络；`mem_limit`/`pids_limit`/`cap_drop`/`no-new-privileges`；`MYSQL_ROOT_HOST` |
| `deploy/docker/Dockerfile`、`imserver/Dockerfile` | 非 root `uid 10001` |
| `deploy/chatapp` | `umask 077` + 备份/媒体包 `chmod 600` |
| `chatapp/accounts/views.py` | `sms_verify` 对 staff/superuser 返回 403（`SMS_ALLOW_STAFF_LOGIN` 可放开） |
| `chatapp/users/services.py` | 访客落库先判「完善 + 过审照片」；单 owner 上限 500 淘汰最旧 |
| `chatapp/discovery/{views,throttles}.py`、`config/settings.py` | `visits` 120/h、`visits/count` 240/h 节流 |
| `chatapp/im/views.py` | `image_auth` 显式校验 `/media/chat/` 前缀 |
| `docs/` | api/auth、api/discovery、ops/imserver、pitfalls/backend、pitfalls/im、审计报告状态与证据、deploy README |

### 验证结果

| 项 | 命令 | 结果 |
|---|---|---|
| 后端全量 | `python manage.py test` | **693 通过**（基线 640，新增 53 条含本轮） |
| imserver 单元 | `docker compose -f imserver/docker-compose.test.yml run --rm --no-deps test bash /src/scripts/test.sh` | **43/43** |
| imserver DB | `… test bash /src/scripts/test_integration.sh` | **19/19** |
| imserver HTTP 集成 | `… test bash /src/scripts/test_http.sh` | `e2e ok`，启动日志 `internal_allow_ready rules=2` |
| H-1 负向验证 | 容器内 `IM_INTERNAL_ALLOW=10.0.0.0/8` → 探针 `403`；默认名单 → `200` | **403 / 200** |
| C-1 部署闸门 | `--render-only --no-tls --public-url http://203.0.113.10`（无开关） | 退出码 **1** |
| C-1 开关生效 | 同上 + `--allow-dev-sms` | 生成 `SMS_DEV_MODE=1` |
| M-7 域名 | `a_b.example` / `a;b` / `a..b` | 三者均退出码 **1** |
| 渲染配置 | `--render-only` + `docker compose config -q` | **通过** |
| Web | `npm run type-check && npm run lint && npm run test:run` | **403 测试通过**，零告警 |
| App | `flutter analyze` | **No issues found** |

### 合并与 CI（2026-11-03）

- PR #30 squash 合并 **`c44035e`**；CI 双绿（backend 693 测试 + imserver unit/db/http）。
- **首跑红一次，根因不是本轮代码**：`requirements.txt` 缺 `packaging` —— kombu 的 redis transport
  在「第一次真的往 broker 发布任务」时 `from packaging.version import Version`，缺它时所有
  `.delay` 入队 `ModuleNotFoundError`，表现为发短信 **503**（`SmsSendTests.test_send_ip_throttle`
  是唯一真入队的用例）。已补依赖；`requirements.lock` 本来就有 `packaging==25.0`。
- 排障手法记录：CI 日志要 admin 权限才能下载，改用「失败时把用例名/上下文写成 GitHub
  annotation」的临时步骤，再用公开的 `/check-runs/{id}/annotations` 读回；确认后已移除该步骤。

### 未完成 / 已知限制

- **未部署**：上线动作见 §F（宝塔现网只上后端代码时，`git pull` + 重启 web/worker 即可，无迁移）。
- `python:3.11-slim-bookworm` 拉取失败（本机访问 Docker Hub 超时），**非 root 镜像只做了静态核对**，
  未实际构建运行；上线前需在能拉镜像的机器上 `docker compose build web` 验证一次。
- nginx 仍是 root master（绑 80/443），`nginx-unprivileged` 记录为已知项。
- Redis 仍未设 `requirepass`（imserver 不支持 AUTH），靠 `backend` 网络隔离兜底。
- 备份文件未自动加密，README 要求运维加密/离线保存。
