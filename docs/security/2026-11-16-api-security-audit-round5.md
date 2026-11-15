---
状态: 一次性
复核: 无(一次性)
---

# chat_app 第五轮安全审计（2026-11-16）

> 审计日期：2026-11-16（第五轮）
> 报告版本：v1.0
> 基线：第四轮整改收尾 `dfa641d`（PR #146，2026-11-08 之后的状态回填）→ 审计时 `main` `de76120`，
> 区间 **160 个提交 / 688 个文件 / +82910 −5201 行**。
> 审计对象：
> 1. 第四轮之后新增/变更的代码：功能批 **M–Q**（登录设备与单端下线 / 会话菜单 / 撤销滑卡与
>    每日额度 / 个人使用报告 / 敏感词拦截）、**R–W**（资料语音自我介绍 / 发现页筛选与今日精选 /
>    广场点赞列表与收藏 / 运营看板与每日指标快照 / 聊天多选删除与草稿）、
>    **CI 流程治理 6 节**（门禁注册表 / 文档索引 / 数字机械化 / C++ 注释门禁）、
>    **worker 工程链路**（L4 需求自动入队 / 出网探针 / 代理 / 健康巡检）；
> 2. 第四轮标注「记录 / 未关闭」的遗留项（Redis `requirepass`、HMAC 重放、游标签名、
>    镜像与 Actions 供应链、设备易主、语音同步转码、管理员口令打印）；
> 3. 第四轮**未覆盖**但属于同一风险面的两处：`GET /im/api/search`（2026-10-27 交付，
>    从未进过任何一轮报告）、`deploy/**` 与 `.github/**` 的本轮增量。
> 审计方式：只读静态代码审查（Django / imserver C++ / Web / App / deploy 脚本 / CI / 仓库脚本）
> + 与第一~四轮逐项对账。**未对生产做任何扫描或利用**。
> 审计执行：AI 辅助静态审查；复核：待项目负责人。
>
> **结论**：业务接口的鉴权 / 对象归属 / 可见性基线**仍然成立**，本轮新增的 HTTP 入口与
> IM 帧逐项核对后没有发现新的未授权接管入口；两处做得比上一轮更细（IM 多选删除的
> 「别人的 id 静默忽略」与搜索的 `LIKE` 转义 + 常量时间比较、设备下线「打标记不删行」）。
> 本轮风险集中在三处：
> ① **新接口没有跟上第四轮定下的限流口径**——`GET /stats/me`、两个登录设备接口、
> `GET /discovery/quota` 都没有按用户额度（M-1），其中 `DELETE /devices/{端}` 每次还会
> 入队一个 Celery 任务；
> ② **语音转码仍在请求路径上，且本轮多了一个入口**（资料语音自我介绍），2C2G 上两个
> gunicorn worker 被两路转码占满即全站排队（M-3，承接并升档）；
> ③ **Redis 依然是信任锚**（H-1 承接）：口令仍未开，而本轮又往 Redis 里放了三类敏感物料
> ——轮换后的 refresh 令牌（宽限窗口内）、日活集合里的用户 id、滑卡额度计数。

---

## 1. 执行摘要

### 1.1 风险统计

| 等级 | 数量 | 说明 |
|---|---:|---|
| 严重 | 0 | — |
| 高危 | 1 | Redis 无口令 + 本轮新增三类敏感物料（承接第四轮 H-1，未恶化到代码执行但面更宽） |
| 中危 | 3 | 四个新接口缺按用户限流、聊天搜索前导通配全表扫、语音转码在请求路径且新增第二入口 |
| 低危 | 8 | HMAC 无 nonce、游标不签名、镜像可变 tag、口令打印、设备易主、refresh 宽限复用、资料语音公开直出、L4 把外部数据写进 worker 指令面 |
| **合计** | **12** | |

### 1.2 与第四轮的关系

| 第四轮项 | 第四轮结论 | 本轮复核 |
|---|---|---|
| H-1 Redis 无口令 + pickle | RCE 面已关闭（JSON 序列化），`requirepass` 待开 | **承接且面更宽**：口令仍未开（`deploy/oneclick.sh:481` 仍是 `redis://redis:6379/2`），而 Redis 里新增了 refresh 令牌、DAU 用户 id 集合、滑卡额度计数 → 仍列高危 §4.1 |
| M-1 准入名单 fail-open | 已修（`SMS_ALLOWLIST_STRICT` 生产严格 + `accounts.E001`） | **成立**：生产 `.env` 不写该键即严格（`docs/ops/runbook.md:357`），`accounts.E001` 已有反向门禁 `backend-e001-gate` 每次 CI 执行 |
| M-2 名单启停无审计 | 已修（`PhoneAllowlistEvent`） | **成立**：`/ops/allowlist/` 的加号 / 启停 / 种子导入各留一条流水 |
| M-3 三个新列表接口无限流 | 已修（四个读接口补按用户限流） | **部分退步**：本轮新接口又出现同类缺口 —— `stats/me`、`devices`、`devices/{端}`、`discovery/quota` 均无额度（M-1） |
| M-4 自动合并白名单只有 `docs/` | 已修（收窄 + 黑名单） | **加强**：白名单只剩 `docs/api/` 与 `docs/milestones.md`，`docs/security/`、`docs/reviews/` 也在 2026-11-12 移入黑名单（`.github/workflows/auto-merge.yml:56-66`） |
| M-5 `POST /push/devices` 不校验归属 | 已修（留痕 + 通知原账号，取 §4.2 第二个选项） | **不变**：仍允许易主，`registration_id` 归属校验未加（L-5） |
| L-1 内部 HMAC 无 nonce | 记录 | **不变**：`notifications/internal.py:87-118` 仍只校验 ±300 秒时间戳 |
| L-2 匿名 `/client-errors` 写 error 日志 | 已修 | **成立**（日志降级 + 采样） |
| L-3 分页游标不签名 | 记录 | **不变**，且本轮新增两个游标接口（点赞列表 / 我的收藏）沿用同一实现 |
| L-4 Actions 与镜像可变 tag | 记录 | **一半改善**：Actions 全部 pin 到提交 SHA；**镜像仍是裸 tag**，其中 `certbot/certbot:latest` 是彻底可变的（L-3） |
| L-5 关注接口存在「账号是否存在」口径 | 记录 | **不变**（与 `GET /users/{id}` 同口径） |
| L-6 语音同步转码 | 记录 | **恶化**：资料语音自我介绍把同一条同步转码路径复制到了第二个入口，且一次上传 3 个子进程（M-3） |
| L-7 管理员口令打印到 stdout | 记录 | **不变**：`deploy/oneclick.sh:926` 仍打印 `$ADMIN_PASSWORD`（L-4） |
| L-8 `pull-backup-pi.sh` 远端注入 | 已修 | **成立**（改 `printf '%s\0'` + `tar --null -T -`） |
| L-9 客户端错误上报带 query | 已修 | **成立**（只留 `pathname`） |

---

## 2. 审计范围与方法

### 2.1 范围内（本轮重点以★标注）

- ★**多端在线与登录设备（批次 M）**：`accounts/device_session.py`（新模块）、
  `accounts/views.py::devices` / `device_logout` / `logout_all`、
  `accounts/urls.py`、`accounts/models.DeviceSession`、
  `accounts/migrations/0006~0008`、`imserver/src/store/user_repo.*` 的
  `session_version(uid, ct)`、`imserver/src/net/ws_server.cpp::handle_auth`、
  `imserver/src/net/http_api.cpp::authenticate`。
- ★**撤销滑卡与每日额度（批次 O）**：`discovery/quota.py`（新模块）、
  `discovery/views.py::swipe` / `swipe_undo` / `quota_view`、`discovery/serializers`、
  `settings.SWIPE_DAILY_LIKE_LIMIT`（默认 0 = 关闭）。
- ★**个人使用报告（批次 P）**：`stats/*`（新 app：`views` / `services` / `metrics` /
  `im_source` / `management/commands/metrics_daily` / `models.DailyMetric`）。
- ★**敏感词拦截（批次 Q）**：`imserver/src/util/sensitive.*`、
  `ws_server.cpp::handle_send`、`IM_SENSITIVE_WORDS_FILE`。
- ★**资料语音自我介绍（批次 R）**：`users/views.py::my_voice`、
  `users.views.normalize_profile_voice`、`users/models.ProfileVoice`、
  `users/serializers.ProfileVoiceSerializer` / `PublicProfileSerializer.get_voice`、
  `users/throttles.ProfileVoiceThrottle`、`im/voice.py`（复用）。
- ★**广场点赞列表与收藏（批次 U）**、**发现页筛选与今日精选（批次 S）**、
  **运营看板与每日指标快照（批次 V）**、**聊天多选删除与置顶免打扰（批次 N/T）**：
  `feed/views.py::post_likes` / `post_favorite` / `favorite_posts`、
  `discovery/views.py::daily`、`ops/views.py::metrics`、
  `imserver/src/net/http_api.cpp` 的 `/im/api/search` / `/conversations/flags` /
  `/messages/delete`、`imserver/src/store/message_repo.cpp`、
  `imserver/migrations/007~008`。
- ★**部署与工程链路**：`deploy/oneclick.sh`、`deploy/docker-compose.yml.tmpl`、
  `deploy/nginx/{http,https}.conf.tmpl`、`deploy/ops/mysql-drill-e5.sh`、
  `.github/workflows/*`（含新的 `l4-intake.yml` / `main-health.yml`）、
  `scripts/{gates.toml,run_gates.py,verify.sh,ci-scope.sh,l4_intake.py,apply_ruleset.py,
  set_automerge_token.py,facts.py,docs_index.py,docs_lint.py,check_cpp_comments.py}`。
- **Web/App 增量**：`web/src/{api,stores,features}`、`app/lib/{core,features}` 的
  新页面与调用点（只查 XSS / 令牌存储 / 越权调用形态，不审视觉）。

### 2.2 范围外

- 云控制台、安全组、操作系统、Docker 守护进程、宝塔面板自身配置。
- 依赖 CVE 库比对、模型网关内部实现、`npm audit` 公告库本身。
- 生产环境主动扫描与利用；compose 与观测栈**未在真实服务器上执行**，
  涉及部署配置的结论标注「条件风险」。
- Flutter SDK（`flutter/`）与第三方依赖源码；App 的 golden 截图链路（非安全面）。

### 2.3 方法

- 逐接口核对：鉴权类、对象归属、入参校验与长度上限、限流、错误契约、
  响应路径是否有外部调用、是否引入新的信任锚（Redis / 缓存 / 文件）。
- 逐新模块核对：数据模型约束（唯一键 / 级联 / 保留期）、跨系统副作用是否走 Celery、
  幂等与去重的**键是否含接收者**、失败时 fail-open 还是 fail-closed。
- IM 面：WS 上行帧白名单、`/im/api/*` 的路径白名单与鉴权、SQL 拼接是否全部经过
  `escape()` / `uint64` 解析、限流桶是否按账号。
- 工程链路：workflow 触发方式（`pull_request` vs `pull_request_target`）、token 权限、
  自动开单 / 自动合并的**输入是否受信**、脚本里的变量是否经过 shell。
- 所有结论给出文件与行号；条件风险注明触发前提与验收口径。

---

## 3. 风险总表

| ID | 等级 | 标题 | 主要影响 | 状态 |
|---|---|---|---|---|
| H-1 | 高危 | Redis 仍无口令，且本轮新增三类敏感物料 | 同网容器被拿下后：① 读走轮换后的 refresh 令牌（30 天）；② 拿 DAU 名单（用户 id 集合）；③ 改准入快照 / 额度计数 | **承接（未修）**：`requirepass` 仍未开（§4.1） |
| M-1 | 中危 | 四个新接口没有按用户限流 | 单账号可高频打聚合 / 写库 + 入队的接口；`DELETE /devices/{端}` 每次入队一个 Celery 任务 | 新增 |
| M-2 | 中危 | 聊天搜索是前导通配 `LIKE '%kw%'`，`im_message` 正文无索引 | 单账号 60 次/分钟即可让 2C2G 的 MySQL 持续全扫自己全部消息 | 新增（首次审查） |
| M-3 | 中危 | 语音转码仍在请求路径，且本轮多了一个入口 | 一次上传 3 个子进程（各 15 秒上限）；两路并发即占满两个 worker | 承接 + 升档 |
| L-1 | 低危 | 内部 HMAC 无 nonce | 同网可在 300 秒窗口内重放；被 `msg_id` 幂等压到「重复入队」 | 承接 |
| L-2 | 低危 | 分页游标不签名 | 客户端可伪造 `(时间, 主键)`，只影响自己可见的分页位置 | 承接 |
| L-3 | 低危 | 镜像仍是可变 tag（`certbot/certbot:latest` 最糟） | 供应链漂移；Actions 已 pin 到 SHA，镜像没跟上 | 半承接 |
| L-4 | 低危 | 管理员口令打印到 stdout + `admin.txt` 明文 | 部署日志 / 录屏泄露运营口令 | 承接 |
| L-5 | 低危 | `POST /push/devices` 不校验 `registration_id` 归属 | 知道别人设备 id 即可抢归属（推送 `off` 时影响有限） | 承接（已留痕 + 通知） |
| L-6 | 低危 | refresh 宽限复用把轮换后的令牌明文放进 Redis | 旧 refresh 在 60 秒内仍可换出新令牌；Redis 可读即拿到新令牌 | 新增 |
| L-7 | 低危 | 资料语音与照片同口径公开直出（不签名、不过期） | 语音是身份特征；URL 一旦泄露（截图 / 日志 / 转发）即长期可下载 | 新增（设计如此，建议改） |
| L-8 | 低危 | L4 自动开单把**外部数据**写进 issue 正文，而 issue 正文是 worker 的指令面 | 只做 `@` 剔除，其余原样；恶意公告文本可成为后续 worker 的「任务描述」 | 新增 |

---

## 4. 详细发现

### 4.1 高危

#### H-1 Redis 仍是信任锚：口令未开，且本轮新增三类敏感物料

**位置**：
[deploy/docker-compose.yml.tmpl:66-72](../../deploy/docker-compose.yml.tmpl)（`redis:7-alpine`，
`command` 里没有 `--requirepass`）、
[deploy/oneclick.sh:481](../../deploy/oneclick.sh)（`IM_REDIS_URL=redis://redis:6379/2`，
无口令）、
[chatapp/config/settings.py:198](../../chatapp/config/settings.py)（`REDIS_URL` 缺省无口令）、
[deploy/README.md](../../deploy/README.md)「已知风险」（自述「Redis 仍未设 `requirepass`」）。

**问题**：第四轮把「Redis 无口令」判为高危（H-1），并关掉了最严重的那一半 ——
`CACHES` 已换 JSON 序列化器 + `VERSION=2`（`chatapp/config/settings.py:211-226`），
`pickle` 反序列化 → RCE 的面确实没了。**但口令那一半没做**（第四轮验收 A2），
而本轮又往同一个 Redis 里放进了三类新的敏感物料：

1. **轮换后的 refresh 令牌明文**：`accounts/views.py:486-487` 把新 refresh 原样
   `cache.set` 进 `auth:refresh_grace:{jti}`（`settings.REFRESH_REUSE_GRACE` 默认 60 秒）。
   能读 Redis 的人在这 60 秒内拿到的是**一枚可用的、30 天有效**的长期凭证，
   直接换 access 即可接管账号 —— 这是本项目第一次把「长期凭证」放进 Redis。
2. **日活集合里的用户 id**：`users/activity.py:108-138` 用 `SADD activity:dau:{YYYYMMDD}`
   写明文账号 id（45 天 TTL）。读到即拿到「谁在哪天用过」的完整名单。
3. **安全边界的派生量**：准入名单快照（已 HMAC 自证，改不了，但可 `DEL` 造成回填抖动）、
   滑卡额度计数（`swipe_like:{uid}:{date}`，可读写 → 绕过每日喜欢额度）、
   限流计数（可 `DEL` → 绕过所有按用户 / 按 IP 限流）。

**影响**：条件风险（需要「同网某个容器被攻陷」或「Redis 端口被暴露」）。一旦成立，
从第四轮的「准入绕过 + 代码执行」变成「**账号接管 + 限流失效 + 行为名单泄露**」。
imserver / worker / 未来新增容器都在同一个 Redis 上，攻击面并没有缩小。

**验收**（第四轮 A2 的同一件事，建议本轮闭环）：
1. Redis 开 `requirepass`：`deploy/docker-compose.yml.tmpl` 的 `command` 加
   `--requirepass $REDIS_PASSWORD`；`chatapp.env` 的 `REDIS_URL` / `BROKER_URL` 与
   `imserver.env` 的 `IM_REDIS_URL` 同改（imserver 的 `parse_redis_url` 已支持
   `redis://user:pass@host/db` 并 `AUTH`）；`deploy/oneclick.sh` 生成口令并写进
   `secrets/values.env`；
2. 顺手把敏感物料从缓存搬走或缩短：`auth:refresh_grace` 的 TTL 已是 60 秒（可接受），
   但 DAU 集合建议只存 `hash(user_id)`（名单用途够了，反查不需要）；
3. 部署核对单加一条「`redis-cli -a` 能连、不带口令连不上」的手测项。

---

### 4.2 中危

#### M-1 四个新接口没有按用户限流（第四轮 M-3 的同类回归）

**位置**：
[chatapp/stats/views.py:32-33](../../chatapp/stats/views.py)（`my_stats`，无 `throttle_classes`）、
[chatapp/stats/services.py:191-194](../../chatapp/stats/services.py)（七个 `COUNT(*)`
压进同一条 SQL 的标量子查询）、
[chatapp/accounts/views.py:608-610](../../chatapp/accounts/views.py)（`devices`）、
[chatapp/accounts/views.py:650-684](../../chatapp/accounts/views.py)
（`device_logout`：写库 + `im_tasks.kick_device.delay`）、
[chatapp/discovery/views.py:432-450](../../chatapp/discovery/views.py)（`quota_view`）。

**问题**：第四轮 M-3 的教训是「新增的读接口必须与既有接口同档限流」，
当时给通知列表 / 未读数 / 关注流 / 回复列表都补了按用户额度。本轮四个新接口没有跟上：

- `GET /api/v1/stats/me`：`period=year` 时七个标量子查询各自扫一整年
  （`Match` / `Swipe`×2 / `ProfileVisit` / `Post` / `PostLike` / `Follow`），
  单请求查询预算 8 条（`stats/services.py` 的设计说明），但**没有额度**；
- `GET /api/v1/devices`：每条一次库查询，无额度；
- `DELETE /api/v1/devices/{client_type}`：**每次写库两处**（`version` 自增 + `logged_out_at`）
  **并 `delay()` 一个 Celery 任务**（`kick_device`），无额度 —— 一个账号即可把
  `default` 队列灌满，`critical` / `notify` 之外的 worker 被占住就影响所有人；
- `GET /api/v1/discovery/quota`：只读一次 Redis，风险最小，但同属「无额度」这一类。

**影响**：单账号可持续放大「聚合查询 + 写库 + 入队」的接口。2C2G / 两 worker 的部署形态下，
这类接口是最容易被一个脚本打满的一档；队列灌满还会牵连与攻击者无关的业务任务。

**验收**：给四个接口补按用户额度（建议与既有各档对齐：`stats` 240/hour、
`devices_read` 480/hour、`devices_write` 30/hour、`quota` 480/hour），超限 429 / `42901`；
在 `docs/api/stats.md` / `docs/api/auth.md` / `docs/api/discovery.md` 写明额度；
`chatapp/config/settings.py` 的 `DEFAULT_THROTTLE_RATES` 增加对应 scope。

#### M-2 聊天搜索是前导通配 `LIKE '%关键词%'`，正文列没有索引

**位置**：
[imserver/src/net/http_api.cpp:915-950](../../imserver/src/net/http_api.cpp)（`/im/api/search`）、
[imserver/src/store/message_repo.cpp:502-537](../../imserver/src/store/message_repo.cpp)（SQL）、
[imserver/src/util/like.h](../../imserver/src/util/like.h)（`%`/`_`/`!` 转义）、
[imserver/migrations/002_search_index.sql](../../imserver/migrations/002_search_index.sql)
（只给 `im_conversation.user_b` 补了索引，`im_message.body` 无 FULLTEXT / 前缀索引）。

**问题**：这条接口 2026-10-27 就交付了，但**前四轮报告都没有覆盖它**（第四轮的范围列了
新增入口，搜索不在其中）。本轮首次审查，注入面是干净的 —— 关键词先 `like_pattern()`
转义 `!`/`%`/`_`，再由 `lease.escape()` 处理引号，SQL 里显式 `ESCAPE '!'`；
`from` 过滤 `(c.user_a=<我> OR c.user_b=<我>)` 保证只搜自己参与的会话，
已撤回 / 我已隐藏 / 我拉黑的对端 / 系统灰条（`user_b=0`）全部排除。**问题在成本**：

- `m.body LIKE '%kw%'` 是**前导通配**，`im_message` 上只有 `(conv_id, seq)` 与主键，
  这个条件无法走索引 → 每次搜索要把「我参与的全部会话的全部文本消息」扫一遍；
- 上限时长消息 150 字节、每页 50 条，但扫描量与**历史总消息数**成正比，与关键词无关；
- 限流是每账号 60 次/分钟、burst 20（`http_api.cpp` 的 `search_table_`），
  也就是说单账号可以持续制造每分钟 60 次全扫。

**影响**：2C2G 上「一个人搜自己的老聊天记录」就能把 MySQL 打到 100%，
与 Redis 无关、与是否登录别人的账号无关 —— 属于**自助式 DoS / 资源耗尽**，
而不是越权。当前账号量很小，实际风险有限；一旦某个人的会话量上去（本项目 IM 不做消息
归档清理），成本会随数据量线性上升。

**验收**（三选一，按成本排序）：
1. 给 `im_message.body` 建 `FULLTEXT` 索引（MySQL 8 + `ngram` 分词器，中文可用），
   搜索改 `MATCH ... AGAINST`；
2. 或者加一条**服务端时间窗**：只搜最近 N 天（例如 90 天）并写进 `docs/ops/imserver.md` §16.4，
   把扫描量钉成常数；
3. 或者把限流压到每账号 10 次/分钟（现在是 60），并把「搜索结果页大小」上限从 50 降到 20 ——
   最省事，但只降低频率不降低单次成本。

#### M-3 语音转码仍在请求路径，且本轮多了一个入口（承接第四轮 L-6，升档）

**位置**：
[chatapp/im/voice.py:95-119](../../chatapp/im/voice.py)（`_run`：`subprocess.run`，
15 秒超时 + `RLIMIT_CPU`/`RLIMIT_AS`/`RLIMIT_FSIZE`）、
[chatapp/im/voice.py:164-221](../../chatapp/im/voice.py)（`_probe_ms` 一次 `ffprobe`、
`_transcode` 一次 `ffmpeg`）、
[chatapp/users/views.py:236-269](../../chatapp/users/views.py)
（**新增**：`normalize_profile_voice` 先写临时文件 + `_probe_ms`，再调 `voice.normalize`
→ 一次上传共 **3 个子进程**）、
[chatapp/users/views.py:297-330](../../chatapp/users/views.py)（`my_voice`，同步路径）、
[chatapp/im/views.py:231-248](../../chatapp/im/views.py)（聊天语音，2 个子进程）。

**问题**：第四轮把「语音同步转码」记为低危（L-6），前提是「只有聊天语音这一个入口，
60 次/小时/账号」。本轮资料语音自我介绍（批次 R）**把同一条路径复制到了第二个入口**，
而且为了「不信任客户端声明的时长」多跑了一次 `ffprobe`：

- 聊天语音：`ffprobe` + `ffmpeg`，最长 60 秒音频；
- 资料语音：`ffprobe` + `ffprobe` + `ffmpeg`，最长 30 秒音频（5MB 上限，10 次/小时/账号）。

子进程有 15 秒超时与 rlimit 兜底（这点做得好，不是无界资源），但**仍在 gunicorn 的
请求线程里同步跑**。生产是 2 个 worker：两路并发转码就占满全部处理能力，
期间所有接口（含登录、健康检查）排队 —— 这是「可用性」问题而不是越权问题，
但它的触发门槛只有一个已认证账号，且成本与音频时长无关（15 秒超时的上限是固定的）。

**影响**：单账号（或两台设备）即可让整站卡住十几秒；资料语音让入口数翻倍、
单次子进程数从 2 升到 3。

**验收**：把转码挪进 Celery（`bulk` 队列），接口只做「接收 + 落临时文件 + 入队」，
前端轮询结果；或至少给这条路径加一个**全局并发闸**（Redis 信号量，例如同时只允许 1 路
转码，其余快速 503）。任一方案都要在 `docs/pitfalls/backend.md` 把口径改掉。

---

### 4.3 低危

| ID | 位置 | 问题 | 处理 |
|---|---|---|---|
| L-1 | [chatapp/notifications/internal.py:87-118](../../chatapp/notifications/internal.py)、[imserver/src/service/push_notifier.cpp](../../imserver/src/service/push_notifier.cpp) | 内部 HMAC 只校验 ±300 秒时间戳，无 `(timestamp, signature)` 去重缓存 | 记录（承接）；影响被 `msg_id` 幂等压到「重复入队」 |
| L-2 | [chatapp/config/cursor.py](../../chatapp/config/cursor.py) | 游标是 base64 明文 `(时间, 主键)`，无签名；本轮新增的点赞列表 / 我的收藏 / 关注流沿用 | 记录（承接）：泄露的只是「某条记录的时间与主键」，查询始终带可见性过滤 |
| L-3 | [deploy/docker-compose.yml.tmpl:34](../../deploy/docker-compose.yml.tmpl)、[:68](../../deploy/docker-compose.yml.tmpl)、[:92](../../deploy/docker-compose.yml.tmpl)、[:247](../../deploy/docker-compose.yml.tmpl) | 镜像仍是 `mysql:8.0` / `redis:7-alpine` / **`certbot/certbot:latest`**；Actions 已在本轮全部 pin 到提交 SHA（改善） | 记录；建议把三个镜像钉到 digest，`latest` 至少钉到具体版本 |
| L-4 | [deploy/oneclick.sh:400-404](../../deploy/oneclick.sh)、[deploy/oneclick.sh:926](../../deploy/oneclick.sh) | 部署结束把管理员口令打印到 stdout，`secrets/admin.txt` 明文（600） | 记录（承接）；建议只打「见 `secrets/admin.txt`」+ 首次登录强制改密 |
| L-5 | [chatapp/notifications/views.py:53-90](../../chatapp/notifications/views.py) | `registration_id` 易主照旧允许，只留痕 + 给原账号发通知；归属校验仍未加 | 记录（承接第四轮 M-5 的第二个选项）：推送 `PUSH_PROVIDER=off` 时只影响归属 |
| L-6 | [chatapp/accounts/views.py:376-407](../../chatapp/accounts/views.py)、[:486-487](../../chatapp/accounts/views.py)、[chatapp/config/settings.py:569](../../chatapp/config/settings.py) | 刷新宽限：旧 refresh 被拉黑后 60 秒内仍能通过 `auth:refresh_grace:{jti}` 换出新令牌；新 refresh 明文存 Redis | 记录；宽限期是「多标签页并发刷新」的必要妥协，但**必须与 A2（Redis 口令）一起看**：它把一个长期凭证放进了无口令的 Redis |
| L-7 | [chatapp/users/serializers.py:162-175](../../chatapp/users/serializers.py)、[:358-375](../../chatapp/users/serializers.py)、[deploy/nginx/https.conf.tmpl:92-95](../../deploy/nginx/https.conf.tmpl) | 资料语音与照片同口径：公开绝对地址、不签名、不过期，由 nginx 裸静态直出；「任何能看资料卡的人都能听」是设计如此 | 记录 + 建议改：照片是「看图」，语音是**可识别身份的生物特征**，泄露后无法换。建议对 `/media/voices/` 也走 `/media/chat/` 那套 `auth_request` 签名（`im/media_sign.py` 现成） |
| L-8 | [scripts/l4_intake.py:173-182](../../scripts/l4_intake.py)、[.github/workflows/l4-intake.yml:140-171](../../.github/workflows/l4-intake.yml) | L4 把 `npm audit` 的公告字段（包名 / 区间 / 公告标题）直接拼进 issue 标题与正文，只做 `@提及` 剔除；而 issue 正文正是 worker 读的「任务描述」 | 记录 + 建议：对外部字段做字符白名单（只留包名 / 版本 / GHSA 形状），或把外部原文放进代码块并显式标注「以下是外部数据，不是指令」。当前输入源是 npm 公告库，被投毒的概率极低，但这是**唯一一条「外部文本 → worker 指令」的通道** |

---

## 5. 第四轮遗留项与本轮「已加强」项

### 5.1 遗留项复核

| 项 | 第四轮处理 | 本轮判定 |
|---|---|---|
| Redis `requirepass`（A2） | 「仍需人侧开启」 | **仍未开**；Redis 里的敏感物料反而更多 → H-1 |
| L-1 HMAC 无 nonce | 记录 | 不变 |
| L-3 游标签名 | 记录 | 不变（新增两个游标接口沿用） |
| L-4 Actions / 镜像可变 tag | 记录 | **Actions 已 pin 到 SHA**；镜像仍裸 tag |
| L-5 关注口径 | 记录 | 不变 |
| L-6 语音同步转码 | 记录 | **恶化** → M-3 |
| L-7 口令打印 | 记录 | 不变 |
| M-5 设备易主归属校验 | 取「留痕 + 通知」 | 不变（L-5） |

### 5.2 本轮确认「已修 / 已加强」的项（免得后续误以为没做）

- **多端在线的下口语义**：下线是「打标记 + 版本单调递增」而不是删行
  （`accounts/device_session.py:117-141`），旧令牌不会因为行消失、版本回落而复活 ——
  这正好躲掉了「删行导致旧令牌重新有效」这个经典错误。
- **按端校验**：JWT 与 IM token 都带 `ct`，WS 握手与 `/im/api/*` **同一份判定**
  （`ws_server.cpp::handle_auth` 与 `http_api.cpp::authenticate` 都是
  `sv != 0 → session_version(uid, ct)` 比对，且都先查 `im:block:{uid}`）；
  判端只在签发时看 `X-Client`，鉴权一律看令牌。
- **IM 多选删除**：`find_mine` 的 SQL 限定 `(from_id=我 OR to_id=我)`，别人的 id
  **静默忽略**（不报 403/404，避免变成「探测别人消息是否存在」的信道），
  `INSERT IGNORE` 靠 `(user_id,msg_id)` 主键幂等，未读只按「本次新隐藏」减。
- **IM 搜索**：`LIKE` 三层转义 + `ESCAPE '!'` + 只搜自己参与的会话 + 排除
  撤回 / 隐藏 / 拉黑 / 系统灰条；这是本轮判「注入面干净」的依据（问题只在成本，见 M-2）。
- **贴纸上行**仍只放行 `type=sticker` + `sticker_NN` 形状；敏感词**只拦上行文本**
  （`ws_server.cpp:643-658`），日志只记「谁发给谁、多少字节」，不抄违规原文。
- **聊天媒体签名**：`im/media_sign.py` 用 `hmac.compare_digest` 常量时间比较、
  只签 `/media/chat/`、缺密钥时**生产 fail-closed**（`DEBUG` 才放行），
  且 nginx 侧用 `auth_request` + `internal` 子请求（公网无法直连验签口）。
- **准入名单**：`ensure_phone_allowed` 的判定顺序把「库内停用」放在最前
  （停用优先于 `.env` 种子，否则老号永远停不掉），生产空名单 fail-closed，
  `accounts.E001` 还有一条 CI 反向门禁用 `DEBUG=0` 实际验证它会响
  （`scripts/gates.toml` 的 `backend-e001-gate`）。
- **自动合并**：白名单只剩 `docs/api/` 与 `docs/milestones.md`，`docs/security/`、
  `docs/reviews/`、`docs/pitfalls/`、`docs/ops/`、`docs/superpowers/` 进黑名单；
  草稿 / 跨仓库 / 作者 / 否决标签 / checks 全绿 / 文件数 / 每日上限全部判定。
- **L4 自动入队**：`permissions` 只给 `contents: read` + `issues: write` + `actions: read`；
  **绝不 @ 任何人**（派单仍由人评论触发）；反编译 / 依赖双保险等判据 fail-closed；
  去重靠 `<!-- l4-fingerprint -->`。
- **工程脚本**：`scripts/l4_intake.py` 调 `gh` 一律用 `subprocess.run([...])` 列表形式
  （无 `shell=True`）；仓库脚本里没有 `ssh`/`scp`/`rsync`；`deploy/ops/mysql-drill-e5.sh`
  用 `MYSQL_PWD` 传口令、`--defaults-extra-file` 读配置，不把口令放命令行参数。
- **Web/App**：全仓没有 `v-html` / `innerHTML` / `eval(` / `document.write`，App 没有 WebView。

---

## 6. 建议修复批次

| 批次 | 内容 | 项 | 规模 |
|---|---|---|---|
| A | Redis 硬化（`requirepass` 落地，三处配置同改） | H-1 | 部署脚本 + backend + imserver 配置，**一条栈做不完 → 拆两个工单**（`deploy+backend`、`imserver`） |
| B | 四个新接口补按用户限流 | M-1 | 后端（`settings` + 四个视图 + 三份文档） |
| C | 聊天搜索降成本（FULLTEXT 或时间窗或压额度） | M-2 | imserver + `docs/ops` |
| D | 语音转码挪出请求路径（Celery 或全局并发闸） | M-3 | 后端 + `docs/pitfalls` |
| E | 小修 | L-3、L-7、L-8 | 部署（镜像 digest）/ 后端+nginx（语音签名）/ CI（外部数据白名单），分别开单 |
| F | 记录项 | L-1、L-2、L-4、L-5、L-6 | 文档（`docs/pitfalls` / `docs/ops`）记录为已知风险，不排期 |

**建议顺序**：A → B → D → C。A 未闭环前，任何「新部署到公网」都不要做；
B/D 都是「一个已认证账号即可触发」的那一档，优先于 C（C 需要历史数据量才有量级）。

---

## 7. 关键复现命令

```bash
# H-1：Redis 是否仍无口令（从任意同网容器）
docker compose -f /opt/chatapp/docker-compose.yml exec web \
  sh -c 'python -c "import os,redis;print(redis.Redis.from_url(\"redis://redis:6379/0\").ping())"'
# 返回 True、且 compose 的 redis command 里没有 --requirepass ⇒ 命中

# H-1 ③：本轮新增的敏感物料就在同一个 Redis 里
docker compose -f /opt/chatapp/docker-compose.yml exec redis redis-cli -n 0 keys 'auth:refresh_grace:*'
docker compose -f /opt/chatapp/docker-compose.yml exec redis redis-cli -n 0 smembers "activity:dau:$(date +%Y%m%d)"
docker compose -f /opt/chatapp/docker-compose.yml exec redis redis-cli -n 0 keys 'swipe_like:*'

# M-1：四个新接口应当出现 429（当前都没有额度）
for i in $(seq 1 60); do curl -s -o /dev/null -w '%{http_code} ' \
  -H "Authorization: Bearer $TOKEN" "https://<站点>/api/v1/stats/me?period=year"; done; echo
for i in $(seq 1 60); do curl -s -o /dev/null -w '%{http_code} ' \
  -X DELETE -H "Authorization: Bearer $TOKEN" "https://<站点>/api/v1/devices/app"; done; echo

# M-2：搜索的单次成本（看 rows_examined 是否随历史消息数增长）
curl -sG 'https://<站点>/im/api/search' --data-urlencode 'q=火锅' --data 'limit=20' \
  -H "Authorization: Bearer $IM_TOKEN" >/dev/null
mysql -e "SELECT * FROM performance_schema.events_statements_history_long
          WHERE SQL_TEXT LIKE '%im_message%LIKE%' ORDER BY TIMER_START DESC LIMIT 5\G"

# M-3：两路并发上传资料语音（观察 /api/v1/health 的延迟）
curl -s -o /dev/null -w '%{http_code}\n' -X POST https://<站点>/api/v1/users/me/voice \
  -F 'file=@30s.m4a;type=audio/mp4' -H "Authorization: Bearer $TOKEN_A" &
curl -s -o /dev/null -w '%{http_code}\n' -X POST https://<站点>/api/v1/users/me/voice \
  -F 'file=@30s.m4a;type=audio/mp4' -H "Authorization: Bearer $TOKEN_B" &
time curl -s -o /dev/null https://<站点>/api/v1/health

# L-3：镜像仍是可变 tag
grep -n 'image:' /opt/chatapp/docker-compose.yml

# L-7：资料语音的 URL 是公开、不签名、不过期的
curl -s -H "Authorization: Bearer $TOKEN" "https://<站点>/api/v1/users/<他人 id>" \
  | python -c 'import json,sys;print(json.load(sys.stdin)["voice"])'
curl -sI "$(上一步的 url)" | head -3   # 不带令牌也应 200
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

# 只改文档（本报告即此类）
scripts/verify.sh contract
```

> 本报告只新增 `docs/security/` 下的一篇文档并更新本目录索引，
> 未改任何代码；`scripts/verify.sh contract` 需在 Linux 侧跑（本机 Windows 侧只做了只读审查）。

---

## 9. 结论

- **业务接口的鉴权基线仍然成立**：本轮新增的 HTTP 入口（登录设备 2、退出所有设备 1、
  滑卡撤销 1、额度查询 1、今日精选 1、个人报告 1、点赞列表 1、收藏 2、资料语音 1、
  会话 flags 1、多选删除 1）与 IM 上行帧（`typing` / 贴纸 / `self_read`）逐项核对过
  鉴权类、对象归属、幂等键、长度上限与限流，**没有发现新的越权读取或接管入口**。
- **三处做得比上一轮更细**：多端下线的「打标记不删行」、IM 多选删除的「别人的 id 静默忽略」、
  搜索的「三层 LIKE 转义 + 只搜自己的会话」。这三处都是同类项目里最容易写错的地方。
- **本轮真正的风险是「新代码没跟上旧口径」而不是新漏洞**：限流口径（M-1）、
  请求路径纪律（M-3）都是第四轮已经立过的规矩，新增入口没有再走一遍；
  这是「纪律没有机械化」的典型形态 —— 与 `accounts.E001` 被做成门禁是同一个解法的两端。
- **Redis 仍是唯一的高危项，且它每一轮都在变重**（本轮又多了长期凭证与行为名单）。
  A2（开 `requirepass`）不需要任何代码改动，只是三处配置 + 一次重启 ——
  建议在本轮内闭环，不要再顺延。
- **建议**：A（Redis 口令）与 B（限流）本轮闭环；D（语音异步化）开单排期；
  C（搜索成本）在消息量上来之前做完即可；E 顺路做；F 只补文档口径。

**报告结束。**（修复进展后续在本文 §3 的「状态」列与 `docs/superpowers/plans/` 下的整改计划里勾选）
