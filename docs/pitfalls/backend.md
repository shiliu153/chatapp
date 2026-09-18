# 踩坑手册 · 后端(Django / 接口 / 数据)

> 索引见 [README.md](README.md)。铁律级契约见 `CLAUDE.md`「核心契约与纪律」;部署运维见 [`../deploy-runbook.md`](../deploy-runbook.md)。

## 环境与本地开发

- MySQL 本机 8.0,库 `chatapp_dev`,用户 `chatapp`(口令在 `.env`);建库/授权脚本 `chatapp/db_setup.sql`(可重复执行)。Python 用 anaconda 环境 `Django`(3.10)。
- ⚠️ **DB 每请求新建连接 + 本机 MySQL TLS 握手 ~250ms → 所有接口 ~280ms**。已默认 `DB_SSL_DISABLED=1`(settings 按 env 注入 `ssl_disabled=True`),接口降到 ~30ms。远程库/生产置 0 或改连接池;**接口变慢先量「建连 vs 查询」**,别猜。
- ⚠️ **Docker Hub 国内不可达**:拉 redis 要先从镜像源拉再打标签——
  `docker pull docker.m.daocloud.io/library/redis:7-alpine && docker tag docker.m.daocloud.io/library/redis:7-alpine redis:7-alpine`。
- ⚠️ **Celery worker 不 autoreload**:改 `im/tasks.py` 等任务代码后必须**手动重启 worker**,否则跑旧代码、新任务报 unregistered task(踩过:runserver 自动重载了,worker 还是几小时前的旧进程)。

## 接口与契约(细节)

- ⚠️ **`GET /users/me` 响应里 `id` 是 profile 表主键,账号 ID 看 `user_id`**(与公开资料卡同源;我的页 ID 行显示 `u{user_id}`——取错会差一位,u7 显示成 u6,2026-09-12 修)。
- ⚠️ JWT 的 `user_id` claim 是**字符串**(SimpleJWT 行为),前端与自家 id 比对时转 int。
- ⚠️ **Git Bash 里 curl 发中文会 400**:`curl -d '{"昵称":...}'` 按本地 GBK 码页发出,服务端 UTF-8 解析失败(**不是后端 bug**)。冒烟用纯 ASCII,或把 JSON 写成 UTF-8 文件后 `--data-binary @file`。
- ⚠️ **Git Bash 会把 `/xxx` 形式的参数转成 Windows 路径**(MSYS 行为):给脚本传接口路径 `/users/me` 会变成 `C:/Program Files/Git/users/me`,请求全打空。对策:整条 URL 当一个参数传(含 `://` 不转),或前缀 `MSYS_NO_PATHCONV=1`。
- ⚠️ **`CELERY_` 前缀的键千万别放 `.env`**:Celery 配置**环境变量优先**(`celery/app/utils.py`:`os.environ.get('CELERY_BROKER_URL') or 配置值`),`load_dotenv` 一灌进环境就压过 settings 的一切覆盖(踩过:测试任务漏进开发 broker DB1,被 dev worker 真执行)。本项目键名 **`BROKER_URL`**;回归用例 `config.tests.CelerySkeletonTests.test_broker_uses_isolated_db_in_tests` 钉死。
- ⚠️ **`on_commit` 的语义是「DB 提交后」,不是「响应后」**(无 `ATOMIC_REQUESTS` 时不在事务里就立即同步执行)——别再往里塞慢调用。
- 验证码状态机(`accounts/sms_codes.py`):Redis hash `sms:code:{phone}`(`h`=HMAC 码/`n`=错误数/`c`=已消费)+ `sms:lock:`(15min 锁)+ `sms:send:`(60s 重发占位);校验走**单个 Lua 脚本**原子完成;校验成功不删码,TTL 缩短为 `SMS_REPLAY_TTL`(60s)幂等重放窗口。历史坑(已修):LocMem 时代 autoreload 重启验证码「凭空过期」→ 已迁 Redis(2026-09-12)。
- request_id(`config/request_id.py` + `middleware.py`):响应带 `X-Request-Id`;日志每行 `[request_id]`;`chatapp.request` 记录「方法 路径 状态 耗时」(≥`REQUEST_SLOW_MS` 升 WARNING);Celery header 透传;错误体 `{code, message, request_id}`。`LOG_FILE` 置路径则落盘(手测配 `--noreload`,防双进程抢写)。
- 限流维度:号码(60s 重发占位)+ IP(DRF throttling,计数在 Redis);额度 env 可调(DEBUG 放宽 200/600,生产 20/60);429 一律带 `Retry-After`。
- 分页约定:`/matches`、`/blocks` 用 LimitOffset(`{count,next,previous,results}`);前端 `ApiClient.getAllPages()` 跟 `next` 拉全量(匹配缓存要全量才能翻译所有会话名);候选卡不在此列。

## 合规与审核

- 封禁两级:`banned_light` 只禁滑卡(检查在 `discovery/views.py`);`banned_heavy` 全域 403——由全局权限类 `moderation/permissions.py::IsNotHeavyBanned` 拦截,**新增业务接口自动被覆盖**;白名单只有 `GET /users/me` 和 `GET /users/tags`。
- admin 小抄(`/admin/`,登录字段是手机号):照片审核在 users→照片(勾选后选动作,自动重算完善状态,驳回可能掉回未完善);举报队列在 moderation→举报(改「已处理」自动补处理人/时间);封禁在 users→资料(改 `status`+填 `ban_reason` → 自动 BanLog + 踢 IM)。拉黑/封禁日志是**只读对账页**(拉黑必须走 App 接口才会同步 IM)。
- 拉黑链路:双向不可见由 `moderation.services.blocked_user_ids` 统一过滤(候选、`/matches`、`GET /users/{id}` 404 全靠它);IM 黑名单经任务队列同步;拉黑方本机会话由 App 端 `deleteConversation` 删除。
- ⚠️ 前端写操作后要失效相关缓存(黑名单列表 provider 是全局缓存的,拉黑成功必须 `ref.invalidate(blockedUsersProvider)`;M3 手测 bug)。
- 举报:`POST /reports`,同人已有待处理 → 幂等返回已有(201 新建/200 已有);限流 20/天。
- 协议:`app/lib/features/legal/legal_texts.dart` 存文本 + `legalVersion`;**改文案要把 legalVersion +1**(弹窗会重新出现一次);测试脚手架 `pumpApp` 默认「已同意」,协议用例传 `{'legal.agreed_version': 0}`。

## 运营审核台 /ops/

- 独立 Django app `ops`:服务端模板 + HTMX;静态 vendored 在 `ops/static/ops/vendor/`(Pico.css/htmx),**不依赖 CDN,生产需 collectstatic**。
- 判据 `is_staff`(登录页直接拒非 staff;已登录非 staff 访问任何 ops 页面 → 403);建运营账号 = 建一个 is_staff 用户。
- 写操作与 admin 同源:`log_ban_change`(封禁审计+踢 IM)、`users/services.py::review_photos`(审核+资料状态重算+`reviewed_by/at` 审计)。解封走 `refresh_status()` 重算(admin 是手改状态,别混用)。
- 照片任何状态都可再审(已通过可「撤回并驳回」);「已跳过」= 照片已被用户删除的陈旧页面。

## 广场(feed)

- 五表 Post/PostImage/PostLike/PostComment/PostReport;限流 scope:`post_create 20/day`、`post_comment 60/day`、`post_report 20/day`(throttle 类对非 POST 放行)。
- ⚠️ **`visible_posts` 必须显式 `order_by`**:annotate 触发 GROUP BY 时 Django 会丢弃 Meta.ordering(SQL 里没 ORDER BY,顺序随数据库);流/我的动态两个查询都踩过。
- 删除收口 `feed/services.py::delete_post`:先关闭该动态全部 pending 举报(标 handled「动态已删除」+ 通知举报者),再删图片文件与行;**作者自删(DELETE /posts/{id})与 ops「删除动态」共用**。`PostReport.post` 是 **SET_NULL**(动态删除后举报行留档)。
- 评论通知链:评论创建 → `feed/services.py::notify_post_commented`(作者本人不通知)→ `im/tasks.py::post_commented` → 系统通知灰条。
- ops 两菜单:动态管理 `/ops/posts/`、动态举报 `/ops/post-reports/`(处理后给举报者发 `report_handled`;待处理 badge 在 `ops/context_processors.py`)。

## 在线状态(presence)

- 写入点唯一:`accounts/authentication.py::SessionJwtAuthentication.get_user()` 校验通过后 `users/presence.py::touch()`(**被顶号旧令牌 401 时不写**);Redis 键 `presence:{user_id}` = 最后活跃秒(TTL 7 天)。**前端零上报**(45s 心跳 + 日常请求天然在线)。
- 「在线」判据:最近 120 秒内有认证请求(`ONLINE_WINDOW_SECONDS`);App 被杀 → ≤2 分钟转离线。
- 接口 `GET /api/v1/presence?user_ids=`(逗号分隔,去重后 ≤100;`users/presence.py::PRESENCE_MAX_IDS`);省略:被拉黑(双向)/不存在/自己/重封禁;Redis 挂 → 全 null 不 500;限流 scope `presence`。
- ⚠️ 单次上限 100 个 id,**`PresenceController.refresh` 内部分片**——新增「随翻页增长的登记源」不用再操心上限(2026-09-13 起)。
- 在线状态是**公开信息**,不依赖配对;IM id → 账号 id 用 `u{id}` 约定(`accounts/models.py::im_user_id`),**不用 matchCache 翻译**(配对被清时旧实现会瞎)。

## 管理命令(补漏)

- `im_setup_system_account`(建「系统通知」账号,新环境跑一次,幂等);`im_sync_nicknames`(昵称全量同步,幂等);`seed_fake_users --count N`(造数,幂等、直调 IM 不必等 worker)。
