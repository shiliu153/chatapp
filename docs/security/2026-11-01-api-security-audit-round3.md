# chat_app 第三轮安全审计（2026-11-01）

> 审计日期：2026-11-01（第三轮）
> 报告版本：v1.0
> 审计对象：
> 1. 第二轮整改（`80340e7`，2026-10-29）之后新增/变更的代码：**「谁看过我」访客记录**、
>    语音录制交互重构、Web 访客页/Toast、**全新的一键 Docker Compose 部署路径**；
> 2. 第二轮标注「记录 / 未关闭」的遗留项（M-4、M-5、L-3、L-8、L-9、S1/H2）；
> 3. 第一、二轮没有覆盖到的模块做抽样复核（feed / moderation / ops / imserver 内部 API）。
> 审计方式：只读静态代码审查（Django / imserver C++ / Web / App / deploy 脚本与模板）+ 与第一、二轮逐项对账。
> 审计执行：AI 辅助静态审查；复核：待项目负责人。
> 结论：**本轮主要风险不在业务代码，而在新加入的部署路径**。新增的
> `deploy/oneclick.sh` + Compose 模板把「固定验证码 + 固定管理员手机号」带进了
> 公网部署默认值（C-1），并且与 imserver「内部 API 只允许回环」的既有约束冲突（H-1）。
> 业务侧新增的「谁看过我」存在写放大与保留期运维缺口（M-1/M-2/M-3），未发现新的
> 未授权接管或越权读取入口。

---

## 1. 执行摘要

### 1.1 风险统计

| 等级 | 数量 | 说明 |
|---|---:|---|
| 严重 | 1 | 一键部署默认值导致任意账号（含运营账号）可被固定验证码登录 |
| 高危 | 2 | Compose 下自建 IM 内部 API 不可用；可信代理范围过宽可伪造 `X-Real-IP` |
| 中危 | 7 | 访客记录保留期/写放大/限流、备份明文、容器 root 与资源限制、Redis 无口令、域名注入 |
| 低危 | 9 | 密钥目录未忽略、镜像供应链、HSTS、口令输出、HMAC 重放、文档与实现不一致等 |
| **合计** | **19** | |

### 1.2 与第二轮的关系

| 第二轮项 | 第二轮结论 | 本轮复核 |
|---|---|---|
| H-1/H-2/H-3 | 已修复 | **成立**（`sv` 双入口校验、`SECRET_KEY` 断言、验证码 CSPRNG 均有效） |
| M-1/M-2/M-3/M-6/M-7/M-8 | 已修复 | **成立**（配额前移、HTTP 限流、可信代理、OTP TTL、id 解析、WS uid 解析） |
| M-4 语音同步 ffmpeg | 记录 | **不变**：仍是请求线程内同步转码（本机 60 次/小时/账号） |
| M-5 `user_sig` 同步调腾讯 | 记录 | **不变**：自建分支是 localhost/内网，风险小；腾讯分支仍违反响应路径纪律 |
| L-3 探测面 | 记录 | **不变**（产品取舍） |
| L-8 配对列表内存分页 | 记录 | **不变**（数据量小） |
| L-9 默认值偏开发 | 记录 | **被新部署路径放大**：`SMS_DEV_MODE=1` 被写进一键部署的生成配置（C-1） |
| S1/H2 固定验证码 | 未关闭（已接受） | **根因不变**；本轮新增的是「默认值 + 固定管理员手机号」的组合风险（C-1） |

---

## 2. 审计范围与方法

### 2.1 范围内

- **部署路径（本轮重点，此前从未评审）**：`deploy/oneclick.sh`、`deploy/docker-compose.yml.tmpl`、
  `deploy/docker/*`、`deploy/nginx/*.tmpl`、`deploy/chatapp`、`deploy/README.md`、`.dockerignore`。
- **「谁看过我」**：`users.ProfileVisit` 模型/迁移、`users.services.record_profile_view/_record_visit`、
  `discovery.views.visits/visits_count`、`discovery.services.visits_received_queryset`、
  `purge_profile_visits` 命令、App/Web 访客页与设置开关。
- **语音交互重构**：App `voice_record_controller.dart`、Web `useVoiceRecorder.ts` / `VoiceRecordBar.vue`、
  `chat.ts` 图片重试改动。
- **抽样复核**：`accounts`（短信/刷新/注销）、`feed`（动态/评论/举报）、`moderation`（举报/拉黑）、
  `ops`（审核台与 OTP）、`im`（签名/配额/验签）、imserver（WS 发送、内部 HMAC、媒体签名）。

### 2.2 范围外

- 云控制台、安全组、操作系统、Docker 守护进程配置。
- 依赖 CVE 库比对、短信商/腾讯云/内容安全的内部实现。
- 对生产环境的主动扫描与利用；Compose 部署未在真实服务器上执行（H-1 为代码推断，附一条复现命令）。

### 2.3 方法

- 逐接口核对鉴权、对象归属、入参校验、限流、错误处理与「响应路径无外部调用」纪律。
- 对新增部署脚本逐段核对：密钥生成/落盘权限、默认值、端口发布、反代头、容器权限、定时任务、备份。
- 对「谁看过我」做读写路径与隐私口径核对（谁能看、看什么、保留多久、写放大）。
- 所有结论给出文件与行号；依赖部署配置的结论标注「条件风险」。

---

## 3. 风险总表

| ID | 等级 | 标题 | 主要影响 | 状态 |
|---|---|---|---|---|
| C-1 | 严重 | 一键部署默认 `SMS_DEV_MODE=1` + 固定管理员手机号 | 新部署到公网即可用 `123456` 登录任意手机号，包括运营管理员账号 | 待修 |
| H-1 | 高危 | Compose 下 imserver `/internal/*` 仅允许回环 | 自建 IM 全链路 403（`user_sig` 503、配对/封禁/删号失效），并诱导运维放开内部接口 | 待修 |
| H-2 | 高危 | `TRUSTED_PROXY_IPS` / `IM_TRUSTED_PROXIES` = 整个 Docker 子网 | 任一容器（含被攻陷的 imserver）可伪造 `X-Real-IP`，绕过后台 IP 白名单、登录锁定与按 IP 限流 | 待修 |
| M-1 | 中危 | 每日维护漏掉 `purge_profile_visits` | 90 天保留期永不执行，违反隐私政策承诺 | 待修 |
| M-2 | 中危 | 访客记录写放大（GET 落库 + 未完善资料也写） | 批量造号可放大 `ProfileVisit` 表与写压力 | 待修 |
| M-3 | 中危 | `visits` / `visits/count` 无按用户节流 | 单账号可高频打带多子查询的计数接口 | 待修 |
| M-4 | 中危 | 备份明文落盘、目录权限随 umask、无保留策略 | 数据库转储（手机号/聊天内容/密码哈希）在宿主机可读 | 待修 |
| M-5 | 中危 | 容器全部 root、无资源/能力限制 | 任一容器 RCE 影响面放大；2C2G 上 OOM 会波及宿主（压测已见 MySQL 被 OOM） | 待修 |
| M-6 | 中危 | Redis 无口令且与业务容器同网 | 验证码摘要、JWT 黑名单、限流计数、在线状态可被同网容器读取/篡改 | 待修 |
| M-7 | 中危 | `--domain` 未做字符白名单 | 域名值原样渲染进 nginx `server_name`，可注入配置（托管/自动化场景） | 待修 |
| L-1 | 低危 | `--render-only` 渲染目录未加入 `.gitignore` | 预览生成的 `secrets/values.env` 可能被 `git add -A` 提交 | 待修 |
| L-2 | 低危 | 镜像可变 tag + `curl get.docker.com \| sh` | 构建不可复现，供应链漂移 | 记录 |
| L-3 | 低危 | 部署模板 HSTS 仅 3600 秒 | 与现网「HSTS 一年」基线不一致 | 待修 |
| L-4 | 低危 | 管理员口令打印到 stdout 并明文存 `admin.txt` | 部署日志/终端录屏可能泄露运营口令 | 记录 |
| L-5 | 低危 | 内部 HMAC 无重放缓存（60 秒窗口） | 同网抓包可在窗口内重放内部调用 | 记录 |
| L-6 | 低危 | `image_auth` 文档称校验路径前缀，实现未显式校验 | 现状靠签名覆盖路径兜底，后续改动易踩 | 待修 |
| L-7 | 低危 | 刷新/注销无节流；`logout` 可拉黑任意有效 refresh | 随机 token 可打黑名单查询；单 token 可被 DoS | 记录 |
| L-8 | 低危 | 开启「隐身浏览」不清理历史访客记录 | 与用户直觉不符（设计已记录，需文案说明） | 记录 |
| L-9 | 低危 | `MYSQL_ROOT_HOST=%` | 容器网络内任意主机可尝试 root 登录 | 待修 |

---

## 4. 详细发现

### 4.1 严重

#### C-1 一键部署默认 `SMS_DEV_MODE=1` + 固定管理员手机号

**位置**：
[deploy/oneclick.sh:415](../../deploy/oneclick.sh)（`SMS_DEV_MODE=1`）、
[deploy/oneclick.sh:335](../../deploy/oneclick.sh)（`ADMIN_PHONE` 默认 `13900000000`）、
[chatapp/config/settings.py:313-314](../../chatapp/config/settings.py)（`SMS_DEV_MODE` 默认 1、`SMS_DEV_CODE=123456`）、
[chatapp/accounts/views.py:160-204](../../chatapp/accounts/views.py)（`sms_verify` 不区分账号类型）。

**问题**：一键部署生成的 `chatapp.env` 明确写入 `SMS_DEV_MODE=1`，而 `sms_verify`
对**任何**手机号都接受固定验证码 `123456`，且不区分 `is_staff` / `is_superuser`。
脚本同时用固定手机号 `13900000000` 创建运营管理员（首次部署时 `is_staff=True`、
`is_superuser=True`）。因此只要按默认值把站点部署到公网：

```bash
curl -s -X POST https://<站点>/api/v1/auth/sms/verify \
  -H 'Content-Type: application/json' \
  -d '{"phone":"13900000000","code":"123456"}'
# → 200，返回该运营账号的 access/refresh
```

攻击者不需要口令、不需要 TOTP，就能拿到运营账号的 API 身份：可读该账号的会话/聊天
（`POST /im/user_sig`）、改资料、发起举报/拉黑、甚至 `DELETE /users/me` 注销该账号。
`/ops/` 控制台本身仍受「密码 + TOTP」保护，但运营账号被接管后，其个人聊天与身份
已经泄露，且这是可预期的、面向公网的默认值。

> 说明：固定验证码本身是第二轮已接受的 S1/H2（产品决定暂不接短信商）。本轮新增的
> 问题是**部署脚本把它作为「生产/灾备一键部署」的默认值**，并配了一个公开可猜的
> 管理员手机号，使「已接受的风险」从封闭测试扩大到了任何一次新部署。

**影响**：新部署的任意账号可被接管；运营账号（最高权限的 API 身份）可被定向接管。

**验收**：
1. 默认部署（不带额外参数）不再生成 `SMS_DEV_MODE=1` 的公网配置，或在 TLS/公网模式下
   直接拒绝启动并提示 `--allow-dev-sms`；
2. `sms_verify` 对 `is_superuser` 账号返回 403（运营账号只走 `/ops/` 的密码 + TOTP）；
3. `--admin-phone` 必须显式提供，不再有默认值。

### 4.2 高危

#### H-1 Compose 部署下 imserver `/internal/*` 仅允许回环

**位置**：
[imserver/src/net/http_api.cpp:437-448](../../imserver/src/net/http_api.cpp)（`/internal/*` 非回环直接 403）、
[deploy/docker-compose.yml.tmpl:134-158](../../deploy/docker-compose.yml.tmpl)（imserver 走默认 bridge 网络，无 `network_mode: host`）、
[deploy/oneclick.sh:392](../../deploy/oneclick.sh)（`IM_SELF_URL=http://imserver:9101`）。

**问题**：imserver 的内部管理接口从设计起就只允许**回环对端**（`is_loopback()`），
现网靠 `network_mode: host` + `127.0.0.1:9101` 满足。新的一键部署把 imserver 放进
Compose 默认 bridge 网络，Django 通过服务名 `imserver:9101` 访问，源地址是 web 容器的
`172.28.0.x`，**不是回环** → 所有 `/internal/*` 返回 403。

连带后果：
- `POST /im/user_sig` 先同步会话版本，失败即 **503** → 客户端拿不到 IM token；
- 配对 `pair_add`、封禁踢人、拉黑、注销删号、系统通知全部静默失败（`_post` 只记日志）；
- 发消息因 `im_pair` 不存在返回 **40302**，聊天不可用。

运维遇到「聊天全挂」时，最可能的修法是把回环判断去掉或把 9101 发布到宿主机 ——
这正是 imserver 安全设计要防的事（内部接口只有 HMAC + 回环两层）。

**影响**：新部署路径下自建 IM 不可用（部署即坏）；错误修法会把内部管理接口暴露到
容器网络甚至公网。

**验收**：
1. 在 compose 里从 web 容器执行
   `curl -s -o /dev/null -w '%{http_code}' http://imserver:9101/internal/healthz`
   当前应为 403，修复后应为 200；
2. `user_sig` 不再 503，配对/拉黑/踢人日志无 403；
3. 内部接口仍只允许「显式配置的来源网段 + HMAC」，不是无条件放开。

#### H-2 `TRUSTED_PROXY_IPS` / `IM_TRUSTED_PROXIES` = 整个 Docker 子网

**位置**：
[deploy/oneclick.sh:410](../../deploy/oneclick.sh)、
[deploy/oneclick.sh:441](../../deploy/oneclick.sh)（均写成 `$DOCKER_SUBNET`，默认 `172.28.0.0/16`）、
[chatapp/config/net.py:59-83](../../chatapp/config/net.py)（命中可信名单即采信 `X-Real-IP`）。

**问题**：把整个 `/16` 当作可信代理，意味着**同一网络里的任何容器**（web、worker、
imserver、db-init、以及未来新增的服务）都能直连 `web:8000` 并伪造 `X-Real-IP`。
一旦 imserver（对公网开放 WS）或某个依赖被攻陷，攻击者即可：
- 绕过后台 `OPS_ALLOWED_IPS` 白名单（若运维配置了）；
- 让登录失败锁定、短信/滑卡等按 IP 的限流全部失效（每次换一个伪造 IP）；
- 在日志/审计里伪造来源。

现网用 `TRUSTED_PROXY_IPS=127.0.0.1,::1`（只有本机 nginx），新部署把信任面从
「一个进程」放大到「一个 /16」。

**影响**：条件风险（需要容器内 foothold），但会直接击穿后台 IP 白名单与限流。

**验收**：compose 给 nginx 固定 IP（如 `172.28.0.10`），两个变量都只写这个地址；
从 web 容器伪造 `X-Real-IP` 不再改变 `client_ip()` 的结果。

### 4.3 中危

#### M-1 每日维护漏掉 `purge_profile_visits`

**位置**：[deploy/oneclick.sh:533-545](../../deploy/oneclick.sh)（maintenance.sh 只跑
`refresh_shuffle_keys` / `im_media_cleanup` / `media_cleanup` / `media_disk_report`）、
[chatapp/users/management/commands/purge_profile_visits.py](../../chatapp/users/management/commands/purge_profile_visits.py)。

**问题**：访客记录承诺保留 90 天（隐私政策与设计文档都写了），现网靠手工加的
03:50 crontab 执行；新的一键部署的每日维护脚本**没有**这条命令。用新路径部署的实例，
`ProfileVisit` 会无限增长，隐私政策里的保留期承诺不成立。

**影响**：合规风险（超出声明的保留期）+ 表持续膨胀。

**验收**：`deploy/oneclick.sh` 生成的 `maintenance.sh` 含
`python manage.py purge_profile_visits --apply`，README 的维护清单同步。

#### M-2 访客记录写放大

**位置**：[chatapp/users/services.py:75-105](../../chatapp/users/services.py)（`_record_visit`）、
[chatapp/users/views.py:114](../../chatapp/users/views.py)（每次 `GET /users/{id}` 都调用）。

**问题**：
1. `_record_visit` 对**任何**登录用户都写行，但访客列表只展示
   `ProfileStatus.COMPLETE` 且有过审照片的人 —— 资料未完善的访问者产生的行在完善前
   不会展示（除非之后完善资料），属于低价值写入；
2. 结合 C-1 的固定验证码，可以低成本批量造号，每个号每小时可浏览 120 个不同目标
   （`PUBLIC_PROFILE_RATE`，默认 `120/hour`），每次浏览落一行（同一对 30 分钟内去重）。
   1 万个号 × 每小时 120 次 ≈ 120 万行/小时的上限，90 天保留期意味着表可以被打到
   千万级，且每次都是 `update_or_create` 写库。

**影响**：认证用户即可制造的写放大/表膨胀；与 C-1 组合时成本更低。

**验收**：只为「资料完善且有过审照片」的访问者落库（与展示口径一致）；
可选的第二道闸：每个 owner 只保留最近 N 条（N=500）或对单账号每日新增行数设上限。

#### M-3 `visits` / `visits/count` 无按用户节流

**位置**：[chatapp/discovery/views.py:279-306](../../chatapp/discovery/views.py)。

**问题**：`visits` 与 `visits/count` 没有 `@throttle_classes`，也没有在
`REST_FRAMEWORK.DEFAULT_THROTTLE_RATES` 里登记。`visits_received_queryset` 每次都要跑
`Swipe`/`Photo`/`Block` 三个子查询 + `COUNT`，单账号可高频调用打库；`count` 尤其便宜
（一个请求 → 多次聚合）。

**影响**：单账号 DoS 面；与 M-2 的写放大叠加时更明显。

**验收**：两个接口加按用户节流（建议 `visits` 120/hour、`visits/count` 240/hour），
超限 429/`42901`。

#### M-4 备份明文落盘、权限随 umask、无保留策略

**位置**：[deploy/chatapp:53-62](../../deploy/chatapp)（`backup` 直接 `gzip > "$out"`）。

**问题**：`backups/` 目录用默认 umask 创建，转储文件通常 644；内容包含手机号、密码哈希、
聊天记录与图片元数据。没有加密、没有保留期、没有异地副本说明。任何能读该目录的
本机用户/备份采集进程都能拿到全量数据。

**影响**：数据泄露面扩大（宿主机侧）。

**验收**：`umask 077` + 落盘后 `chmod 600`；README 增加「备份需加密/离线保存」；
可选 `--encrypt`（gpg/age）。

#### M-5 容器全部 root、无资源/能力限制

**位置**：[deploy/docker/Dockerfile:6-39](../../deploy/docker/Dockerfile)（无 `USER`）、
[deploy/docker/web.Dockerfile:17-20](../../deploy/docker/web.Dockerfile)、
[deploy/docker-compose.yml.tmpl](../../deploy/docker-compose.yml.tmpl)（无 `mem_limit` /
`pids_limit` / `cap_drop` / `no-new-privileges`）。

**问题**：Django/gunicorn、celery、imserver 均以 root 运行；所有服务没有内存上限。
2026-11-01 压测已经实测 2C2G 上 MySQL 会被 OOM 杀掉（`docs/ops/stress-test-2026-11-01.md`），
Compose 路径没有任何 `mem_limit` 来隔离「一个服务吃满内存拖垮整机」。

**影响**：容器 RCE 后的影响面放大（可写挂载卷、可读环境变量）；OOM 时故障扩散。

**验收**：应用镜像加非 root `USER`；compose 给各服务加 `mem_limit`/`pids_limit`，
`security_opt: [no-new-privileges:true]`，按需 `cap_drop: [ALL]`。

#### M-6 Redis 无口令且与业务容器同网

**位置**：[deploy/docker-compose.yml.tmpl:54-69](../../deploy/docker-compose.yml.tmpl)（`redis-server` 无 `requirepass`）、
[deploy/oneclick.sh:388-389](../../deploy/oneclick.sh)（`redis://redis:6379/0`）。

**问题**：Redis 里同时有：短信验证码的 HMAC 摘要与失败计数、JWT 黑名单、DRF 限流计数、
在线状态、IM 的封禁键与发送配额。任何能连到 `redis:6379` 的容器（或未来新增的服务）
都能读写这些键：清空限流、伪造在线状态、删封禁键、枚举/重放黑名单。

**影响**：条件风险（需要容器内 foothold），但一旦成立，多个安全控制同时失效。

**验收**：短期把 Redis 放到只有 web/worker/imserver 的独立网络；长期给 Redis 加
`requirepass`（imserver 的 `parse_redis_url` 目前不支持 AUTH，需要同步扩展）。

#### M-7 `--domain` 未做字符白名单

**位置**：[deploy/oneclick.sh:145-150](../../deploy/oneclick.sh)（只拒绝 `://` 与 `/`）、
[deploy/oneclick.sh:487-493](../../deploy/oneclick.sh)（`sed` 渲染进 nginx 模板）。

**问题**：`DOMAIN` 原样进入 `server_name __SERVER_NAME__;`。形如
`--domain 'a.example; include /etc/passwd;'` 的值会注入 nginx 配置指令。
当前脚本由 root 手动执行、域名来自运维自己，属于「自伤型」；但脚本被托管面板/
自动化平台调用时，域名可能来自外部输入。

**影响**：条件风险（nginx 配置注入 → 任意文件读取/反代）。

**验收**：域名只允许 `[a-z0-9.-]`，长度 ≤253，且不含 `..`；非法直接 `die`。

### 4.4 低危

| ID | 位置 | 问题 | 处理 |
|---|---|---|---|
| L-1 | [deploy/oneclick.sh:157-160](../../deploy/oneclick.sh) | `--render-only` 默认写 `$PWD/deploy-render`，含 `secrets/values.env`（真实密钥），但 `.gitignore` 没有该目录 | 加入 `.gitignore`，README 提示预览目录也要删 |
| L-2 | [deploy/docker-compose.yml.tmpl:26/55/197](../../deploy/docker-compose.yml.tmpl)、[deploy/oneclick.sh:578](../../deploy/oneclick.sh) | `mysql:8.0`、`redis:7-alpine`、`certbot:latest`、`alpine` 均为可变 tag；Docker 安装走 `curl \| sh` | 固定小版本/摘要；文档标注可复现构建 |
| L-3 | [deploy/oneclick.sh:407](../../deploy/oneclick.sh) | 部署模板 `SECURE_HSTS_SECONDS=3600`，现网已是 31536000 | 统一为一年（首次上线可先短，稳定后升） |
| L-4 | [deploy/oneclick.sh:866-878](../../deploy/oneclick.sh) | 部署结束把管理员口令打印到 stdout；`admin.txt` 明文 | 只提示「见 secrets/admin.txt」；首次登录强制改密 |
| L-5 | [imserver/src/net/http_api.cpp:292-315](../../imserver/src/net/http_api.cpp) | HMAC 只校验 ±60 秒时间窗，无 nonce 缓存 | 记录；需要时加 `(timestamp, signature)` 短 TTL 去重 |
| L-6 | [chatapp/im/views.py:218-238](../../chatapp/im/views.py)、[chatapp/im/media_sign.py:130-153](../../chatapp/im/media_sign.py) | docstring 称「路径不在 `/media/chat/` 下返回 403」，实际 `image_auth` 未显式判断，靠 `media_sign.verify` 内部前缀检查兜底 | 在 `image_auth` 显式校验前缀，或修正文档 |
| L-7 | [chatapp/accounts/views.py:266-331/334-363](../../chatapp/accounts/views.py) | 刷新/注销端点无节流；`logout` 对请求体里任意有效 refresh 直接拉黑 | 记录；注销加按 IP 更严额度即可（已有 60/hour） |
| L-8 | [chatapp/users/services.py:75-105](../../chatapp/users/services.py) | 开启隐身只影响后续访问，历史行仍展示 | 设计已记录；设置页文案写明「不影响已产生的记录」 |
| L-9 | [deploy/docker-compose.yml.tmpl:34](../../deploy/docker-compose.yml.tmpl) | `MYSQL_ROOT_HOST: "%"`，容器网络内任意主机可尝试 root 登录 | 改为具体服务名或固定 IP |

---

## 5. 修复批次

| 批次 | 内容 | 项 |
|---|---|---|
| A | 部署默认值与内部接口 | C-1、H-1、H-2 |
| B | 访客记录与运维缺口 | M-1、M-2、M-3、M-4、M-7 |
| C | 容器与网络加固 | M-5、M-6、L-9 |
| D | 低危与文档 | L-1、L-3、L-6、其余记录项 |
| E | 回归与文档 | 后端全量、imserver 集成、Web/App 检查、docs/api、pitfalls、部署 README |

**本轮建议不做**（记录为已知风险）：M-4/M-5（第二轮遗留的语音异步化、腾讯调用移出
响应路径）、L-2（镜像供应链，需 CI 支持）、L-5（HMAC 重放缓存）、L-7/L-8（产品取舍）。

---

## 6. 关键复现命令

```bash
# C-1：默认部署后，用固定验证码登录管理员手机号（在站点可达的机器上）
curl -s -X POST https://<站点>/api/v1/auth/sms/verify \
  -H 'Content-Type: application/json' \
  -d '{"phone":"13900000000","code":"123456"}' | head -c 300

# H-1：compose 部署后，从 web 容器访问 imserver 内部探针
docker compose -f /opt/chatapp/docker-compose.yml exec web \
  sh -c "curl -s -o /dev/null -w '%{http_code}\n' http://imserver:9101/internal/healthz"
# 预期（修复前）：403；修复后：200

# H-2：从 web 容器伪造 X-Real-IP 直连 Django
docker compose -f /opt/chatapp/docker-compose.yml exec web \
  sh -c "curl -s -H 'X-Real-IP: 203.0.113.9' http://web:8000/api/v1/health"

# M-1：确认维护脚本是否包含访客清理
grep -n purge_profile_visits /opt/chatapp/bin/maintenance.sh

# M-3：visits/count 无节流（连续请求不应出现 429）
for i in $(seq 1 50); do curl -s -o /dev/null -w '%{http_code} ' \
  -H "Authorization: Bearer $TOKEN" https://<站点>/api/v1/discovery/visits/count; done; echo
```

---

## 7. 回归命令

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

## 8. 结论

- 业务代码的安全基线（鉴权、对象归属、封禁可见性、媒体签名、配额、限流）在第三轮抽样中
  未发现新的越权/接管入口；第一、二轮的修复仍然有效。
- 本轮的风险集中在**新部署路径**：默认值（C-1）、网络与回环假设（H-1）、可信代理范围（H-2）
  都属于「部署即生效」的问题，建议在把 Compose 路径用于任何公网实例之前先关闭。
- 「谁看过我」本身口径正确，但保留期（M-1）、写放大（M-2）与节流（M-3）需要在
  上线前补齐，否则会同时带来隐私合规与容量问题。

**报告结束（修复进展见 §5 勾选与 `docs/superpowers/plans/2026-11-01-security-round3.md`）**
