# chat_app 第四轮安全审计（2026-11-08）

> 审计日期：2026-11-08（第四轮）
> 报告版本：v1.0
> 基线：第三轮整改合并 `c44035e`（PR #30，2026-11-03）→ 审计时 master `611c44b`，
> 区间 **101 个提交 / 378 个文件 / +30498 −3384 行**。
> 审计对象：
> 1. 第三轮之后新增/变更的代码：功能批 **F–J**（暗黑模式 / 共同点破冰 / 站内通知中心 /
>    广场关注 + 关注流 / 聊天贴纸）、**已读回执**、**离线推送（C-1）**、**客户端错误上报**、
>    **封闭测试准入名单（B-1/B-1c）**、**契约体系（D-5）**、**观测与容量（E-3/E-4/E-6/E-7）**、
>    **superagent 工程链路**（工单流程 / gh-guard / 自动合并 / 模型兜底代理）；
> 2. 第三轮标注「记录 / 未关闭」的遗留项（L-2、L-4、L-5、L-7、L-8、Redis 口令、语音同步转码）；
> 3. 第三轮未覆盖的部署与运维面抽样复核（`deploy/observability/*`、`deploy/ops/*`、CI 工作流）。
> 审计方式：只读静态代码审查（Django / imserver C++ / Web / App / deploy 脚本 / CI / 仓库脚本）
> + 与第一~三轮逐项对账。**未对生产做任何扫描或利用**。
> 审计执行：AI 辅助静态审查；复核：待项目负责人。
>
> **结论**：业务接口的鉴权/对象归属/可见性基线**仍然成立**，没有发现新的未授权接管入口；
> 本轮风险集中在三处：
> ① **Redis 重新成为信任锚**——它无口令、和业务容器同网，而 Django 缓存走 pickle，
> 且「准入名单」这一安全边界现在也存在 Redis 里（H-1）；
> ② **两个 fail-open 默认值叠加**——`SMS_DEV_MODE` 默认 1 + 名单「库与种子都空即放行」，
> 一键部署路径又不落名单（M-1）；
> ③ **agent 工程链路的写权限面**——自动合并只按 `docs/` 前缀放行，而 `docs/` 正是
> 下一次 agent 的指令面（M-4）。

---

## 1. 执行摘要

### 1.1 风险统计

| 等级 | 数量 | 说明 |
|---|---:|---|
| 严重 | 0 | — |
| 高危 | 1 | Redis 无口令 + pickle 反序列化 + 准入名单快照入库（条件风险，需容器内 foothold） |
| 中危 | 5 | 准入名单 fail-open 与部署路径缺位、名单启停无审计、新列表接口无限流、推送设备可被接管、自动合并白名单覆盖 agent 指令面 |
| 低危 | 8 | HMAC 无 nonce、匿名错误上报污染日志、游标未签名、CI/镜像可变 tag、语音同步转码、口令打印、备份脚本远端注入、上报路由带 query |
| **合计** | **14** | |

### 1.2 与第三轮的关系

| 第三轮项 | 第三轮结论 | 本轮复核 |
|---|---|---|
| C-1 部署默认 | 已修复 | **成立**：`oneclick.sh` 公网/TLS 必须 `--allow-dev-sms` 且必须显式 `--admin-phone`；运营账号走短信登录仍 403 |
| H-1 内部接口回环 | 已修复 | **成立**：`IM_INTERNAL_ALLOW` 按 CIDR 判定，compose 写子网；`/internal/*` 不在 nginx 反代路径上 |
| H-2 可信代理范围 | 已修复 | **成立**：只信任 nginx 固定地址 `172.28.0.10` |
| M-1~M-3 访客记录 | 已修复 | **成立**：`purge_profile_visits` 进维护脚本、写侧先判「完善+过审照片」、两接口有限流 |
| M-5 容器非 root | 已修复 | **加强**：nginx 也改用 `nginx-unprivileged`（E-6①），`cap_drop: ALL` |
| M-6 Redis 无口令 | 已修复（网络隔离）/ `requirepass` 待办 | **未变，且影响面变大**：Redis 里的安全敏感键更多（推送幂等、封禁、限流、**准入名单快照**），pickle 反序列化使其从「控制面失效」升级为「代码执行」→ H-1 |
| L-2 镜像可变 tag | 记录 | **不变**（GitHub Actions 也仍是 `@v4/@v5/@v2` 大版本引用） |
| L-4 管理员口令打印 | 记录 | **不变**（`oneclick.sh:926`） |
| L-5 HMAC 无 nonce | 记录 | **不变**，且新增的 `/internal/push/new-message` 同样无 nonce（靠 `msg_id` 幂等兜底） |
| L-7 刷新/注销节流 | 记录 | **不变** |
| L-8 隐身不清理历史访客 | 记录 | **不变** |
| 第二轮 M-4 语音同步转码 | 记录 | **不变**（`im/voice.py` 仍在请求路径里起 2 次子进程） |

---

## 2. 审计范围与方法

### 2.1 范围内（本轮重点以★标注）

- ★**准入名单**：`accounts/allowlist.py`、`accounts/services.ensure_phone_allowed`、
  `accounts/models.PhoneAllowlist`、`accounts/validators.py`、`ops/views.py::allowlist_*`、
  `accounts/management/commands/allowlist_seed_import.py`、`settings.SMS_PHONE_WHITELIST`。
- ★**站内通知与推送**：`notifications/*`（`models` / `views` / `services` / `internal` /
  `push` / `tasks`）、`config/urls.py` 的 `/internal/`、imserver `push_notifier.cpp`、
  `docs/ops/push.md`。
- ★**新列表与分页**：`feed/views.py::following_posts`、`notifications/views.py`、
  `config/cursor.py`、`config/params.py`。
- ★**客户端错误上报**：`telemetry/*`、`config/logging.py`、Web `api/clientErrors.ts`。
- ★**部署与工程链路**：`deploy/observability/*`（prometheus/alertmanager/grafana/exporter/
  alert-relay）、`deploy/ops/chatapp-backup.sh`、`deploy/ops/pull-backup-pi.sh`、
  `.github/workflows/*`（含新的 `auto-merge.yml`、`app-ui.yml`）、`scripts/gh-guard/*`、
  `scripts/superagent-*`、`scripts/superagent-failover/*`、`scripts/create_release.py`。
- **IM 面变更**：imserver `ws_server.cpp`（贴纸上行白名单、`read` 限流、已读回执广播）、
  `redis_client.cpp`（AUTH 支持）、`http_api.cpp`（离线推送触发）、`im/self_client.py`、
  `im/views.py`、`im/voice.py`。
- **App/Web**：`app/lib/core/token_storage.dart`、`app/lib/im/self_im_client.dart`、
  `app/lib/im/self_transport.dart`、`web/src/api/{http,token-store,clientErrors}.ts`、
  `web/src/im/self/*`、`web/src/stores/{theme,notifications}.ts`。

### 2.2 范围外

- 云控制台、安全组、操作系统、Docker 守护进程、宝塔面板自身配置。
- 依赖 CVE 库比对、极光/阿里云邮件推送/模型网关的内部实现。
- 生产环境主动扫描与利用；Compose 与观测栈**未在真实服务器上执行**，
  涉及部署配置的结论标注「条件风险」。
- Flutter SDK（`flutter/`）与第三方依赖源码。

### 2.3 方法

- 逐接口核对：鉴权类、对象归属、入参校验与长度上限、限流、错误契约、响应路径是否有外部调用。
- 逐新模块核对：数据模型约束（唯一键/级联/保留期）、跨系统副作用是否走 Celery、
  幂等与去重的**键是否含接收者**。
- 部署链路：默认值、端口发布、网络分段、容器权限、密钥落盘权限、定时任务、备份与加密。
- CI 与仓库脚本：触发方式（`pull_request` vs `pull_request_target`）、token 权限、
  白名单与否决标签、脚本里的变量拼接是否经过 shell。
- 所有结论给出文件与行号；条件风险注明触发前提与验收口径。

---

## 3. 风险总表

| ID | 等级 | 标题 | 主要影响 | 状态 |
|---|---|---|---|---|
| H-1 | 高危 | Redis 无口令 + Django 缓存 pickle + 准入名单快照入库 | 同网容器被拿下后：① 可绕过准入名单（往快照里塞号码）；② 通过 `pickle` 反序列化在 web/worker 执行代码 | **已修（RCE 面已关闭，口令未开）**：序列化器换 JSON + `CACHES.VERSION=2`、名单快照改 HMAC 自证（#125 → #138 → `57e17e2`）；**Redis `requirepass`（A2）仍需人侧开启**（§4.1） |
| M-1 | 中危 | 准入名单 fail-open：`SMS_DEV_MODE` 默认 1、名单「库+种子都空即放行」、部署路径不落名单 | 一次「按默认值部署」= 任意手机号可用 `123456` 登录 | **已修**：名单为空按 `SMS_ALLOWLIST_STRICT` fail-closed（生产即严格）+ `accounts.E001` 部署检查（#128 → #141 → `9127e82`） |
| M-2 | 中危 | 准入名单启停无操作人审计 | 安全边界的「谁放进来 / 谁拿掉」查不到 | **已修**：新增 append-only `PhoneAllowlistEvent` 流水，`/ops/allowlist/` 的加号/启停/种子导入各留一条（#130 → #144 → `6093b0d`） |
| M-3 | 中危 | 三个新列表接口无读限流且每页 `COUNT(*)` | 单账号可高频打多子查询/聚合接口 | **已修**：四个读接口补按用户限流 —— 通知列表 240/h、未读数 480/h、关注流 240/h、回复列表 360/h（#129 → #142 → `8ed6209`） |
| M-4 | 中危 | 自动合并白名单只有 `docs/`，而 `docs/` 是 agent 指令面 | worker 账号被拿下即可**无人工审查**向 master 写入后续 agent 会执行的指令 | **已修**：白名单收窄到无指令语义的 docs 子集 + 显式黑名单（人侧 PR #134 → `2011b24`） |
| M-5 | 中危 | `POST /push/devices` 不校验 `registration_id` 归属 | 知道设备 id 即可把别人的设备抢到自己名下（推送当前 off，影响有限） | **已修（取 §4.2 验收的第二个选项）**：易主时写 `push_device_transfer` 日志 + 给原账号发站内通知（#131 → #145 → `7f1909b`）；`registration_id` 归属**校验**仍未加，知道别人的 rid 照样能抢（推送 `off` 时只影响归属，见 §4.2） |
| L-1 | 低危 | 内部 HMAC 无 nonce，`/internal/push/new-message` 窗口 300 秒 | 同网可在窗口内重放；靠 `msg_id` 幂等把影响降到「重复入队」 | 记录 |
| L-2 | 低危 | 匿名 `/client-errors` 直接写 `error` 级日志 | 可污染日志/告警；每 IP 120/h、字段上限已设 | **已修**：日志降为 `warning` 且不参与告警，同一 `platform+message` 60 秒采样（#126 → #136 → `748ef7b`） |
| L-3 | 低危 | 分页游标不签名 | 客户端可伪造任意 `(created_at, pk)`，仅影响自己可见的分页位置，不构成越权 | 记录 |
| L-4 | 低危 | Actions 与镜像仍是可变大版本 tag；`auto-merge` 用带写权限 PAT | 供应链漂移；PAT 泄露即写仓库 | 记录 |
| L-5 | 低危 | 关注接口存在「账号是否存在」口径（204/404） | 与 `GET /users/{id}` 同口径，无新增暴露；关注不发通知需在文档写明 | 记录 |
| L-6 | 低危 | 语音仍在请求路径同步转码（第二轮 M-4 遗留） | 单次上传 2 个子进程 + 15 秒 CPU 上限，60/h/账号，2C2G 上并发可打满 | 记录 |
| L-7 | 低危 | 管理员口令打印到 stdout + `admin.txt` 明文（第三轮 L-4 遗留） | 部署日志/录屏泄露运营口令 | 记录 |
| L-8 | 低危 | `pull-backup-pi.sh` 把远端文件名未加引号拼进远端 shell | 远端文件名含空格/分号时可注入命令（需先有服务器写权限） | **已修**：文件名改为 `printf '%s\0'` + 远端 `tar --null -T -`（人侧 PR #135 → `6964c1e`） |
| L-9 | 低危 | 客户端错误上报的 `route` 带 query string | 分享码等参数可能被写进日志 | **已修**：上报只保留 `pathname`（#127 → #139 → `23dce11`） |

---

## 4. 详细发现

### 4.1 高危

#### H-1 Redis 仍是信任锚：无口令 + pickle 反序列化 + 准入名单快照入库

**位置**：
[chatapp/config/settings.py:195-202](../../chatapp/config/settings.py)（`CACHES` 用
`django_redis.cache.RedisCache`，**默认 pickle 序列化器**）、
[chatapp/accounts/allowlist.py:43-76](../../chatapp/accounts/allowlist.py)（名单快照
`cache.get/cache.set`）、
[chatapp/accounts/services.py:40-75](../../chatapp/accounts/services.py)（准入判定唯一入口）、
[deploy/README.md](../../deploy/README.md)「已知风险」（`Redis 仍未设 requirepass`）、
[deploy/docker-compose.yml.tmpl](../../deploy/docker-compose.yml.tmpl)（`backend` internal
网络里的 `redis`，无 `requirepass`）。

**问题**：第三轮把「Redis 无口令」记为 M-6，判定为「网络隔离兜底，一旦同网容器被拿下则多个
安全控制同时失效」。本轮该结论不变，但**后果升级了两级**：

1. **安全边界本身进了 Redis**：准入门名单为了「零查询」，把整张表读成
   `(active, disabled)` 两个 frozenset 缓存在 `sms:allowlist:snapshot`。任何能写 Redis 的
   容器（含被攻陷的 imserver / worker / 未来新增服务）执行
   `SET sms:allowlist:snapshot <自己的值>`（或 `DEL` 后等 TTL 回填）就能让任意号码通过
   `ensure_phone_allowed`。固定验证码 + 名单是**长期准入机制**（2026-11-03 决定），
   所以这等于「容器 foothold → 任意账号可被注册/登录」。
2. **pickle 反序列化把控制面失效升级为代码执行**：`django_redis` 默认
   `django_redis.serializers.pickle.PickleSerializer`。攻击者能写 Redis，就能写一个 pickle
   载荷到**任何**缓存键（限流计数、候选池、推送幂等键……），等 web/worker 下一次
   `cache.get` 时在 Django 进程里反序列化 → 直接 RCE。这类路径每请求都在跑
   （限流计数、白名单快照、候选池缓存），不需要受害者点击任何东西。

**影响**：条件风险（需要「同网某个容器被攻陷」或「Redis 端口被暴露」）。一旦成立，
既是**准入绕过**（业务边界失效），又是**远程代码执行**（web 进程持有 `.env`：
`SECRET_KEY`、DB 口令、`IM_SELF_INTERNAL_SECRET`、`IM_MEDIA_SIGN_SECRET`）。

**验收**（任选其一，建议全做）：
1. Redis 开启 `requirepass`：Django `REDIS_URL=redis://:pass@redis:6379/0`、
   imserver `IM_REDIS_URL`（已支持 `AUTH`，`redis_client.cpp` 的
   `parse_redis_url` 支持 `redis://user:pass@host/db`），`.env` 与 compose 同改；
   **注意**：`CELERY_BROKER_URL` 也在同一个 Redis 上，必须一起改。
2. 缓存序列化改 JSON：`CACHES["default"]["OPTIONS"]["SERIALIZER"] =
   "django_redis.serializers.json.JSONSerializer"`（顺便关掉整类 pickle 反序列化面）。
3. 准入名单快照不再落 Redis 信任链：改成「进程内短 TTL 快照 + 写路径失效」
   （多进程最多各自滞后 TTL），或加一个不可伪造的 HMAC 包裹（`cache` 值比 HMAC 不匹配即视为未命中）。

---

### 4.2 中危

#### M-1 准入名单 fail-open：`SMS_DEV_MODE` 默认 1、名单空即放行、部署路径不落名单

**位置**：
[chatapp/config/settings.py:417](../../chatapp/config/settings.py)（`SMS_DEV_MODE` 缺省 `1`）、
[chatapp/config/settings.py:432-433](../../chatapp/config/settings.py)（种子缺省为空集）、
[chatapp/accounts/services.py:40-75](../../chatapp/accounts/services.py)
（第 5 条规则：库与种子都空 = 不限制）、
[deploy/oneclick.sh:280-304](../../deploy/oneclick.sh)（`--allow-dev-sms` 的判定）、
[deploy/oneclick.sh:435-470](../../deploy/oneclick.sh)（生成的 `chatapp.env` **没有**
`SMS_PHONE_WHITELIST`）。

**问题**：三个「放行」默认值叠在一起：

1. `SMS_DEV_MODE` 在**代码里**默认 `1`（固定码 `123456`），只有 `.env` 显式写 `0` 才关；
2. `ensure_phone_allowed` 在「库与种子都空」时**放行**（开发/测试友好，但对生产是 fail-open）；
3. 一键部署生成的配置**不写** `SMS_PHONE_WHITELIST`，也不会去导库里的名单
   （`allowlist_seed_import` 要人工跑）。

因此「按默认值部署一台公网实例」的路径是：`.env` 里 `SMS_PHONE_WHITELIST` 缺失 +
`accounts.PhoneAllowlist` 空 → 判定走到第 5 条 → **任何手机号都能用 `123456` 登录**，
只要部署者加了 `--allow-dev-sms`（第三轮 C-1 的修复把「加开关」变成了显式动作，
但没有把「名单必须有内容」一起要求）。这属于「已接受风险（固定码）」在新机制下
**没有被新机制覆盖到**的缺口，而不是新漏洞。

**影响**：一次「按默认值 + 一个确认开关」的部署 = 全号码可登录；名单机制（长期准入）
实际未生效，而文档已宣称它是安全边界。

**验收**：
1. `--allow-dev-sms` 之外再加一条硬约束：`SMS_DEV_MODE=1` **且**（库内启用名单为空 **且**
   `SMS_PHONE_WHITELIST` 为空）时，非 `DEBUG` 环境**拒绝启动/拒绝部署**（或
   `manage.py check --deploy` 里加一条 Error 级检查），把「fail-open」变成「fail-closed」；
2. `oneclick.sh` 支持 `--allowlist-phone`（可多次）并把结果写进 `SMS_PHONE_WHITELIST`，
   同时打印「名单内号码即可登录本实例」；
3. `docs/ops/runbook.md` 的「准入名单日常运维」加一条首次部署必跑
   `allowlist_seed_import`。

#### M-2 准入名单启停无操作人审计

**位置**：[chatapp/ops/views.py:828-885](../../chatapp/ops/views.py)（`allowlist_add` /
`allowlist_toggle` 只写 `is_active` / `note`）、
[chatapp/accounts/models.py:132-146](../../chatapp/accounts/models.py)（只有 `created_by`）。

**问题**：名单是安全边界，但「谁在什么时候停用了谁」「谁把这个号重新启用」在库里查不到——
`created_by` 只记创建人，`updated_at` 只记时间不记操作人。`/ops/` 的其它写操作
（封禁、审核、举报处理）都走 `moderation.services.log_ban_change` 之类的审计，
唯独准入名单没有。运营账号多人共用时（当前是单人项目，但 `/ops/` 有多个 staff 入口），
出问题无法追溯。

**影响**：安全边界可变但不可审计；一个被拿下的运营账号可以静默加号/停用，
事后只剩 `updated_at` 一个时间戳。

**验收**：新增 `PhoneAllowlistEvent`（或复用 `ops` 的审计表）记录
`(phone 摘要, action=add/enable/disable, operator_id, at, note)`，
`allowlist_add` / `allowlist_toggle` 各写一条；列表页展示最近 N 条。

#### M-3 三个新列表接口无读限流且每页 `COUNT(*)`

**位置**：
[chatapp/notifications/views.py:132-166](../../chatapp/notifications/views.py)
（`notification_list` / `notification_unread_count`，无 `@throttle_classes`）、
[chatapp/feed/views.py:401-421](../../chatapp/feed/views.py)（`following_posts`）、
[chatapp/config/cursor.py:233](../../chatapp/config/cursor.py)
（`paginated_response` 每次请求都跑 `queryset.count()`）。

**问题**：第三轮 M-3 给 `visits` / `visits/count` 补了按用户节流，理由是「列表要跑多个子查询、
计数接口单请求多次聚合」。本轮新增的列表**重复了同样的形态且没有节流**：

- `GET /notifications` 每页一次 `COUNT(*)`（90 天窗口，索引 `user, -created_at`）+ 预取
  `actor__profile` 与 `actor__photos`；
- `GET /notifications/unread_count` 单请求一次聚合 + 一次 `COUNT`；
- `GET /feed/following` 走 `page_visible_posts`，`total = base.count()`（含 `NOT EXISTS`
  子查询）+ 当页 id + 当页聚合三段 SQL；
- `GET /posts/{id}/comments/{cid}/replies` 同样无节流。

`DEFAULT_THROTTLE_RATES` 里也没有对应 scope（只有 `client_error` 是新增的）。

**影响**：单账号即可高频打「聚合 + 计数」接口；2C2G 上 `COUNT` 与三段查询叠加时最容易被放大。

**验收**：给三个读接口加按用户节流（建议 `notifications` 240/hour、
`notifications_unread` 480/hour、`following` 240/hour，与 `visits` 同档），超限 429/`42901`；
并在 `docs/api/notifications.md` / `docs/api/feed.md` 注明额度。

#### M-4 自动合并白名单只有 `docs/`，而 `docs/` 是 agent 的指令面

**位置**：[.github/workflows/auto-merge.yml:47-58](../../.github/workflows/auto-merge.yml)
（`WHITELIST_PREFIXES=("docs/")`）、
[.github/workflows/auto-merge.yml:99-124](../../.github/workflows/auto-merge.yml)
（只按 `files[].path` 前缀放行 + 作者/标签/checks 判定）。

**问题**：L2 自动合并的合理化前提是「`docs/` 改动不可执行」。但在本仓库里，`docs/` 是
**下一次 agent 的行为输入**：`docs/superpowers/specs/*`、`docs/pitfalls/*.md`、
`docs/ops/superagent.md`、`docs/superpowers/plans/*` 都会被 worker 与主 agent 当作指令读。
一个被拿下的 worker 账号（它有 `docs/` 的推送权）可以提一个「纯文档」PR，往
`docs/pitfalls/backend.md` 里写一段「遇到 X 时请执行 Y」，六轨全绿后由 auto-merge
**无人工审查**合进 master，之后每个读到它的 agent 都会照做。这不是理论风险：本仓库
已经把「读 pitfalls → 按它改代码」写成了流程。

**影响**：一处「文档级」写入可以变成后续 agent 会话的指令注入；绕过人工 PR 审查。

**验收**（建议同时做）：
1. 白名单缩到「无指令语义」的目录：`docs/api/`、`docs/security/`、`docs/reviews/`、
   `docs/milestones.md`，把 `docs/superpowers/`、`docs/pitfalls/`、`docs/ops/` 排除；
2. 或对上述目录保留自动合并，但要求在 PR 正文里附「本改动不含指令性内容」并由
   人打 `auto-ok` 标签（现有 `VETO_LABELS` 反向用法）；
3. worker 的 `docs/` 写权限与「读文档的 agent」不是同一信任级这一点，写进
   `docs/superpowers/specs/2026-11-08-superagent-automation-ladder-design.md` §4。

#### M-5 `POST /push/devices` 不校验 `registration_id` 归属

**位置**：[chatapp/notifications/views.py:38-67](../../chatapp/notifications/views.py)
（`update_or_create(registration_id=..., defaults={"user": me, ...})`）、
[chatapp/notifications/models.py:24-46](../../chatapp/notifications/models.py)
（`registration_id` 全局唯一）。

**问题**：设计意图是「同一台设备换账号登录时设备易主」。但它没有校验「这个
`registration_id` 现在属于谁」，也没有「必须与登录设备一致」的绑定（App 里
`registration_id` 是客户端自己上报的字符串）。因此：

- 拿到别人的 `registration_id`（例如从崩溃日志、客服截图、或自己曾用过的旧设备记录里
  拼出来）就能把该设备记录**改挂到自己账号下** → 原账号失去推送，且该设备以后收到的是
  攻击者的通知（内容泄露给设备持有人说）。
- 反向：攻击者可以把自己的设备 id 反复卖给不同账号，制造「推送到别人手机上」。

**影响**：条件风险（需要知道对方 `registration_id`，且当前 `PUSH_PROVIDER=off`
使实际后果仅限记录归属）；一旦哪天打开推送就会变成真实的信息泄露面。

**验收**：`register_device` 加上「同一 `registration_id` 归属变化需在同一会话内先解绑，
或写入 `PushDeviceHistory` 并在归属变化时给原账号写一条站内通知」；`docs/api/push.md`
写明「设备易主」的语义与前提。

---

### 4.3 低危

| ID | 位置 | 问题 | 处理 |
|---|---|---|---|
| L-1 | [chatapp/notifications/internal.py:73-99](../../chatapp/notifications/internal.py)、[imserver/src/service/push_notifier.cpp:202-216](../../imserver/src/service/push_notifier.cpp) | 内部 HMAC 只校验 ±300 秒时间戳，无 `(timestamp, signature)` 去重缓存 | 记录；影响被 `msg_id` 幂等（`PUSH_DEDUP_TTL=3600`）压到「重复入队」，需要时再加 nonce 缓存 |
| L-2 | [chatapp/telemetry/views.py:42-55](../../chatapp/telemetry/views.py) | 匿名接口直接写 `error` 级日志（`chatapp.client_error`），可被用来灌日志/触发日志类告警 | 改成独立 logger + 采样（如同一 message+route 每小时 1 条）或降到 `warning`；`docs/ops/observability.md` 注明该 logger 不参与告警 |
| L-3 | [chatapp/config/cursor.py:63-86](../../chatapp/config/cursor.py) | `before` 游标是 base64 的明文 `(iso时间, pk)`，无签名/无校验边界 | 记录：泄露的信息只是「某条记录的时间与主键」，查询始终带 `user/可见性` 过滤，不构成越权；如需抗篡改可加 HMAC |
| L-4 | [.github/workflows/*.yml](../../.github/workflows)、[deploy/docker-compose.yml.tmpl](../../deploy/docker-compose.yml.tmpl) | Actions 仍是 `actions/checkout@v4` / `subosito/flutter-action@v2` 大版本引用；镜像仍是 `mysql:8.0` 之类的可变 tag（第三轮 L-2 未变）；`auto-merge.yml` 用带 `repo` 权限的 `AUTOMERGE_TOKEN` | 记录；后续可固定到 SHA/摘要，并给 PAT 收窄到 `contents:write` + `pull_requests:write`（fine-grained） |
| L-5 | [chatapp/feed/views.py:428-459](../../chatapp/feed/views.py) | `POST/DELETE /users/{id}/follow` 用 204/404 区分「存在/不存在」，与 `GET /users/{id}` 同口径；「关注不发通知」意味着被关注者看不到谁关注了自己（`follower_count` 却公开） | 记录；在 `docs/api/feed.md` 把这三条口径写清楚（不暴露粉丝身份、只暴露数量） |
| L-6 | [chatapp/im/voice.py:86-107](../../chatapp/im/voice.py)、[chatapp/im/views.py:176-226](../../chatapp/im/views.py) | 语音仍在**请求路径**里同步跑 `ffprobe` + `ffmpeg`（各 15 秒上限，`RLIMIT_AS=512MB`），`CHAT_VOICE_RATE=60/hour` | 记录（第二轮 M-4 遗留）；2C2G 上 2 个 gunicorn worker 被两路转码占满即全站排队，需要时改 Celery + 预签名上传 |
| L-7 | [deploy/oneclick.sh:919-941](../../deploy/oneclick.sh) | 部署结束把管理员口令打印到 stdout，`secrets/admin.txt` 明文（第三轮 L-4 未变） | 记录；改成「见 `secrets/admin.txt`」+ 首次登录强制改密 |
| L-8 | [deploy/ops/pull-backup-pi.sh:72](../../deploy/ops/pull-backup-pi.sh) | `$SSH "$TARGET" "cd $REMOTE_DIR && tar -cf - -- ${missing[*]}"` 把远端 `find` 结果未加引号拼进**远端 shell**：备份目录里出现 `a; rm -rf x` 之类文件名即注入（在树莓派上以 `backup` 身份执行） | 改成 `printf '%q'` 转义或 `--files-from` 走 stdin |
| L-9 | [web/src/api/clientErrors.ts:82-86](../../web/src/api/clientErrors.ts) | 上报的 `route` = `pathname + search`，query 里的分享码/邀请参数会被写进服务端日志 | 只保留 `pathname`（或对 `search` 做键名白名单） |

---

## 5. 第三轮遗留项复核

| 项 | 第三轮处理 | 本轮判定 |
|---|---|---|
| Redis `requirepass` | 「待 imserver 支持 AUTH」 | **已具备条件**：`imserver/src/store/redis_client.cpp` 已支持 `redis://user:pass@host/db` + `AUTH`。**建议本轮就打开**（H-1 的验收 1） |
| L-2 镜像/供应链 | 记录 | 不变（新增 Actions 大版本引用） |
| L-4 口令打印 | 记录 | 不变 |
| L-5 HMAC 重放 | 记录 | 不变，新增 `/internal/push/new-message` 同样无 nonce |
| L-7 刷新/注销节流 | 记录 | 不变 |
| L-8 隐身不清理历史访客 | 记录 | 不变（文案已说明） |
| 第二轮 M-4 语音异步化 | 记录 | 不变（L-6） |
| 第二轮 M-5 腾讯调用移出响应路径 | 记录 | **已消失**：腾讯分支随 D-4 删除，`im/signature.py`、`im/backend.py`、`tencent_im_client.dart`、`routing_im_client.dart` 全部删除 |

**本轮新增的「已修复/已加强」项**（免得后续误以为没做）：
- nginx 非 root（E-6①）+ 全容器 `cap_drop: ALL`；
- Redis AUTH 能力（E-6②）；
- 客户端错误上报的字段长度上限与 IP 限流；
- 站内通知的 dedupe 键**全部含接收者**（`match:{match_pk}:{receiver_id}`、
  `like:{post}:{actor}`、`report:{report_pk}`），没有出现「两个接收者共用一个键导致
  第二个人收不到通知」的经典 bug；
- 贴纸上行只放行 `type=sticker` + `sticker_NN` 白名单形状，
  `match_notice` / `ban_notice` 等系统灰条仍只能由 `/internal/send` 发
  （`imserver/src/net/ws_server.cpp:412-476`）——这一条做得很干净；
- `read` 帧 2/s 限流 + 服务端回读实库再广播（`GREATEST` 语义）；
- Web 把 refresh 放 HttpOnly Cookie（`token-store.ts` 只留 `userId`），App 走
  Keystore/Keychain（`token_storage.dart`）；IM token 走 `auth` 帧而**不在** WS URL 里。

---

## 6. 建议修复批次

| 批次 | 内容 | 项 | 规模 |
|---|---|---|---|
| A | Redis 硬化（口令 + JSON 序列化 + 名单快照不入信任链） | H-1 | 后端 + imserver + 部署，一条栈做不完 → **拆两个工单**：`backend+deploy`（口令/序列化）、`imserver`（`IM_REDIS_URL` 同步） |
| B | 准入名单 fail-closed + 审计 | M-1、M-2 | 后端 + 部署（`settings` / `services` / `ops` / `oneclick.sh`） |
| C | 读接口限流 | M-3 | 后端 |
| D | 自动合并白名单收窄 | M-4 | CI（`.github/workflows/auto-merge.yml` + spec 文档） |
| E | 小修 | M-5、L-2、L-8、L-9 | 后端 / 部署脚本 / Web 三处，分别开单 |
| F | 记录项 | L-1、L-3、L-4、L-5、L-6、L-7 | 文档（`docs/pitfalls` / `docs/ops`）记录为已知风险，不排期 |

**建议顺序**：A → B → C → D，其余按需。A 与 B 未闭环前，任何「新部署到公网」都不要做。

---

## 7. 关键复现命令

```bash
# H-1 ①：Redis 是否仍无口令（从 web 容器，或任何同网容器）
docker compose -f /opt/chatapp/docker-compose.yml exec web \
  sh -c 'python -c "import os,redis;print(redis.Redis.from_url(\"redis://redis:6379/0\").ping())"'
# 返回 True、且 compose 里没有 requirepass ⇒ 命中

# H-1 ②：缓存值是 pickle（本地起 Redis 后）
cd chatapp && python - <<'PY'
import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings"); django.setup()
from django.core.cache import cache
from django_redis import get_redis_connection
cache.set("probe:pickle", {"a": 1}, 60)
print(get_redis_connection("default").get("chatapp:1:probe:pickle")[:2])  # b'\x80\x04' = pickle
PY

# H-1 ③：准入名单快照就在 Redis 里（能改就能绕过）
docker compose exec web python manage.py shell -c \
  "from accounts import allowlist; allowlist.snapshot()"
docker compose -f /opt/chatapp/docker-compose.yml exec redis \
  redis-cli -n 0 keys 'chatapp:*allowlist*'

# M-1：默认部署后名单与种子是否都为空（= 任何号码可用 123456）
grep -n 'SMS_PHONE_WHITELIST\|SMS_DEV_MODE' /opt/chatapp/secrets/chatapp.env
docker compose exec web python manage.py shell -c \
  "from accounts.models import PhoneAllowlist as P; print(P.objects.filter(is_active=True).count())"

# M-3：三个新读接口不应出现 429（当前无限流）
for i in $(seq 1 60); do curl -s -o /dev/null -w '%{http_code} ' \
  -H "Authorization: Bearer $TOKEN" https://<站点>/api/v1/notifications/unread_count; done; echo

# M-5：把同一 registration_id 报给两个账号（应被拒/需先解绑）
curl -s -X POST https://<站点>/api/v1/push/devices \
  -H "Authorization: Bearer $TOKEN_B" -H 'Content-Type: application/json' \
  -d '{"registration_id":"<A 设备的 id>","platform":"android"}'
```

---

## 8. 回归命令

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

> 本报告只新增 `docs/security/` 下的一篇文档，未改任何代码；`scripts/verify.sh contract`
> 需在 WSL/Linux 侧对合并后的分支跑（本机 Windows 侧只做了只读审查）。

---

## 9. 结论

- **业务接口的鉴权基线仍然成立**：本轮新增的 10 个 HTTP 入口（站内通知 3、推送设备/偏好 3、
  关注 1、关注流 1、客户端错误 1、内部推送回调 1）与 1 条新的上行帧（贴纸）逐项核对过
  鉴权类、对象归属、幂等键接收者、长度上限与限流，没有发现新的越权读取或接管入口；
  站内通知的「别人的 id 静默过滤 + 一律 204」、贴纸上行的白名单形状、`read` 帧限流
  这三处做得比同规模项目更细。
- **本轮真正的风险在「信任锚」与「工程链路」两层**：
  Redis 既无口令又承载安全边界，Django 缓存又是 pickle（H-1）；
  准入名单是新的长期安全边界，但它的默认值是 fail-open，部署路径也没把它带上（M-1、M-2）；
  自动合并把「worker 可写」与「agent 会读」两个面缝在 `docs/` 上（M-4）。
- **建议**：A（Redis 硬化）与 B（名单 fail-closed + 审计）在本轮内闭环；
  C/D 各开一个工单；E 顺路做；F 只补文档口径。

**报告结束。**（修复进展后续在本文 §3 的「状态」列与
`docs/superpowers/plans/` 下的整改计划里勾选）
