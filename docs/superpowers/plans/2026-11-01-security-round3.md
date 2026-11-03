# 第三轮安全整改计划（2026-11-01）

> 依据：[docs/security/2026-11-01-api-security-audit-round3.md](../../security/2026-11-01-api-security-audit-round3.md)
> 范围：1 严重 + 2 高危 + 7 中危 + 9 低危（其中 L-2/L-4/L-5/L-7/L-8 记录不改）。
> 执行方式：`executing-plans` 内联逐批完成，不派子 agent。
> 每批完成即跑对应测试并勾选，未全绿不进入下一批。
> 前置：本轮只动部署脚本/模板与少量后端代码，**不需要数据库迁移**。

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
| A | 部署默认值与内部接口 | C-1、H-1、H-2 | [ ] |
| B | 访客记录与运维缺口 | M-1、M-2、M-3、M-4、M-7 | [ ] |
| C | 容器与网络加固 | M-5、M-6、L-9 | [ ] |
| D | 低危与文档 | L-1、L-3、L-6 | [ ] |
| E | 回归与文档 | 全部 | [ ] |

---

## A. 部署默认值与内部接口

### A.1 C-1 固定验证码不再作为公网部署默认值

- [ ] `deploy/oneclick.sh`：新增 `--allow-dev-sms`（默认关闭）。
      TLS/公网模式（`TLS=1`）下若未显式传 `--allow-dev-sms` → `die`，
      提示「SMS_DEV_MODE=1 只允许封闭测试；接短信商前请用 --allow-dev-sms 显式确认」。
- [ ] `--no-tls` + `--public-url` 指向非回环地址时同样要求 `--allow-dev-sms`。
- [ ] `SMS_DEV_MODE` 写入 `chatapp.env` 时按开关取值（`1`/`0`），不再硬编码 `1`。
- [ ] `ADMIN_PHONE` 去掉默认 `13900000000`：TLS/公网模式必须显式 `--admin-phone`；
      `--render-only` 可保留占位值（`13900000000`）并打印警告。
- [ ] `chatapp/accounts/views.py::sms_verify`：`user.is_superuser` 时返回 403
      （`{"code":403,"message":"运营账号请使用运营后台登录"}`），并补测试。
      —— 这条不依赖短信商，能直接切断「固定验证码 → 最高权限账号」的路径。
- [ ] `deploy/README.md` §6/§12 同步说明：默认不开启开发短信；运营账号不走短信登录。

**验收**：默认 `sudo bash deploy/oneclick.sh --domain ... --email ...` 在没有
`--allow-dev-sms` 时直接失败；带该开关才生成 `SMS_DEV_MODE=1`；
`sms_verify` 对 superuser 返回 403（后端测试）。

### A.2 H-1 imserver 内部接口支持「显式来源网段」

- [ ] `imserver/src/config.{h,cpp}`：新增 `IM_INTERNAL_ALLOW`（逗号分隔 IP/CIDR，
      默认 `127.0.0.1,::1`），非法条目启动报错。
- [ ] `imserver/src/net/http_api.cpp`：`route()` 的 `/internal/*` 判断从
      `is_loopback()` 改为「对端命中 `IM_INTERNAL_ALLOW`」；保留 HMAC 校验。
- [ ] `imserver/tests/`：新增用例——默认配置下非回环 403；加入 `172.28.0.0/16`
      后同网段放行；不在名单内的网段仍 403。
- [ ] `deploy/oneclick.sh` 的 `imserver.env` 写入
      `IM_INTERNAL_ALLOW=127.0.0.1,::1,172.28.0.0/16`（或 nginx/web 的固定 IP）。
- [ ] `docs/ops/imserver.md` 与 `docs/pitfalls/im.md` 补这一条：**回环假设在
      容器网络下不成立**，`/internal/*` 的信任边界改为「来源网段 + HMAC」。

**验收**：compose 里从 web 容器 `curl http://imserver:9101/internal/healthz` → 200；
从不在名单的网段 → 403；`user_sig` 不再 503。

### A.3 H-2 可信代理收敛到 nginx 固定 IP

- [ ] `deploy/docker-compose.yml.tmpl`：给 `nginx` 服务加
      `networks: default: ipv4_address: 172.28.0.10`。
- [ ] `deploy/oneclick.sh`：`TRUSTED_PROXY_IPS` 与 `IM_TRUSTED_PROXIES` 改为
      `127.0.0.1,::1,172.28.0.10`（不再写整个 `/16`）。
- [ ] `deploy/README.md` §1 的架构说明同步（「只信任 nginx 的固定地址」）。

**验收**：从 web 容器伪造 `X-Real-IP` 直连 `web:8000`，`client_ip()` 仍返回容器真实
地址；经 nginx 的请求仍能拿到真实客户端 IP。

---

## B. 访客记录与运维缺口

### B.1 M-1 保留期进入每日维护

- [ ] `deploy/oneclick.sh` 的 `maintenance.sh` 增加
      `python manage.py purge_profile_visits --apply`。
- [ ] `deploy/README.md` §6/§9 的维护清单同步。
- [ ] `docs/ops/` 若有维护任务清单，同步一行。

### B.2 M-2 只为「会展示的访客」落库

- [ ] `chatapp/users/services.py::_record_visit`：先取 viewer 的
      `Profile.status` 与「是否有过审照片」，不满足 `COMPLETE` 直接 return
      （与 `visits_received_queryset` 的展示口径一致）。
- [ ] 可选上限：同一 owner 的 `ProfileVisit` 超过 `PROFILE_VISIT_MAX_PER_OWNER`
      （默认 500）时，删除最旧的再写；用一次 `ORDER BY last_at LIMIT` 实现。
- [ ] `chatapp/users/tests.py`：补「未完善资料的访问不落库」「超出上限时最旧行被淘汰」。

### B.3 M-3 访客接口节流

- [ ] `chatapp/config/settings.py`：新增 `VISITS_RATE`（默认 `120/hour`）、
      `VISITS_COUNT_RATE`（默认 `240/hour`），登记进 `DEFAULT_THROTTLE_RATES`。
- [ ] `chatapp/discovery/throttles.py`：新增 `VisitsThrottle` / `VisitsCountThrottle`。
- [ ] `chatapp/discovery/views.py`：两个视图加 `@throttle_classes`。
- [ ] `chatapp/discovery/tests.py`：连续请求触发 429/`42901`。
- [ ] `docs/api/discovery.md`：补限流说明（接口行为变化）。

### B.4 M-4 备份权限与提示

- [ ] `deploy/chatapp`：`umask 077`；`backup` 落盘后 `chmod 600 "$out"`；
      `backup-media` 同样。
- [ ] `deploy/README.md` §8：写明备份含个人信息、需加密/离线保存、建议保留期。

### B.5 M-7 域名白名单

- [ ] `deploy/oneclick.sh`：`--domain` 只允许 `[a-z0-9.-]`、长度 ≤253、不含 `..`；
      非法直接 `die`。补一条 `--render-only` 的非法域名用例（脚本内 `die` 即可）。

---

## C. 容器与网络加固

### C.1 M-5 非 root + 资源/能力限制

- [ ] `deploy/docker/Dockerfile`：创建 `app` 用户，`chown /app`，`USER app`；
      确认 `collectstatic`、`media` 卷写权限仍正常。
- [ ] `deploy/docker/web.Dockerfile`：nginx 镜像默认以 root 起 master，评估是否改
      `nginx-unprivileged`（若改动大，记录为已知项）。
- [ ] `deploy/docker-compose.yml.tmpl`：给 web/worker/imserver/nginx 加
      `mem_limit`（如 web 768m、worker 512m、imserver 512m、nginx 128m）、
      `pids_limit`、`security_opt: [no-new-privileges:true]`、`cap_drop: [ALL]`（按需回加）。
- [ ] 本地 `docker compose config -q` 通过；渲染后人工核对缩进。

### C.2 M-6 Redis 网络与口令

- [ ] 短期：compose 增加独立 `backend` 网络，只有 web/worker/imserver/redis 在内；
      nginx 只接 `frontend`（或保持默认网络但把 redis 放独立网络）。
- [ ] 长期（记录）：imserver `parse_redis_url` 支持 `redis://:pass@host:port/db` 并 `AUTH`，
      再给 Redis 开 `requirepass`；本轮不做代码改动，只在 `deploy/README.md` 标注。

### C.3 L-9 MySQL root 来源

- [ ] `deploy/docker-compose.yml.tmpl`：`MYSQL_ROOT_HOST` 改为 `172.28.0.%` 或具体
      `db-init` 服务地址；确认 `db-init` 与 `mysql` 健康检查仍通过。

---

## D. 低危与文档

### D.1 L-1 预览目录忽略

- [ ] `.gitignore` 增加 `deploy-render/`；`deploy/README.md` §3 提示预览完删除。

### D.2 L-3 HSTS 与现网对齐

- [ ] `deploy/oneclick.sh`：`SECURE_HSTS_SECONDS` 默认改为 `31536000`，并在 README
      说明「首次上线可先 3600，确认全站 HTTPS 后再升一年」。

### D.3 L-6 验签路径显式校验

- [ ] `chatapp/im/views.py::image_auth`：在 `media_sign.verify` 前显式判断
      `parts.path.startswith("/media/chat/")`，与 docstring 一致；补测试。

### D.4 记录项

- [ ] 在审计报告 §4.4 标注 L-2/L-4/L-5/L-7/L-8 为「记录（本轮不改）」，
      并在 `docs/pitfalls/` 或部署 README 留一句已知风险。

---

## E. 回归与文档

- [ ] 后端全量绿；imserver unit + db + 集成绿；Web type-check/lint/test 绿；App analyze 零告警。
- [ ] 更新审计报告 §3 状态列与 §5 修复证据。
- [ ] 更新 `docs/pitfalls/backend.md`（访客写放大/节流）、`docs/pitfalls/im.md`（内部接口来源网段）。
- [ ] 更新 `docs/api/discovery.md`（visits 限流）。
- [ ] 更新 `deploy/README.md`（默认值、维护任务、备份、可信代理、内部接口）。
- [ ] 若 C-1 改了 `sms_verify` 行为，更新 `docs/api/auth.md`。

## F. 上线动作（执行后填写）

- [ ] 新部署路径：用 `--render-only` 生成一份配置做静态核对；
      有条件时在一台测试机跑 `--no-tls --allow-dev-sms` 全链路（登录/聊天/发图/语音）。
- [ ] 现网（宝塔）不受本轮改动影响；若只上线后端代码（`sms_verify` superuser 403 +
      visits 节流），按常规 `git pull` + `migrate`（无新迁移）+ 重启 web/worker。
