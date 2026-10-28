# 踩坑手册 · 后端(Django / 接口 / 数据)

> 索引见 [README.md](README.md)。铁律级契约见 `CLAUDE.md`「核心契约与纪律」;部署形态见 [项目 README](../../README.md)「部署」。

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

## 账号注销(T-17)

- **`user.delete()` 之后 `user.id` 会变成 `None`** —— Django 的 Collector 会把被删实例的主键置空。所有要在 `transaction.on_commit` 里用到的值(`user_id`、`user.im_user_id`)必须在 `delete()` **之前**取好,否则会拼出 `uNone`,而且**不报错、静默错**。`users/services.py::delete_account` 里 `user_id` / `im_user_id` 都在删行前取。
- **`on_commit` 回调在 `APITestCase` 里默认不执行**(整个用例包在事务里且最终回滚)。要测副作用必须 `with self.captureOnCommitCallbacks(execute=True):` 包住请求。
- **IM 删号任务的参数是 `im_user_id` 而不是 `user_id`** —— 全项目唯一一处例外。原因:该任务在用户行删除**之后**入队,任务内查库必然拿到 `None`,沿用 `_user()` 兜底会静默跳过、删号永不发生。`im/tasks.py::delete_account` 的 docstring 有完整说明。
- **重封禁用户的注销天然被 403 挡住** —— `moderation/permissions.py::BAN_EXEMPT` 白名单只含 `("GET", "/api/v1/users/me")` 与 `("GET", "/api/v1/users/tags")`,`DELETE` 不在内。这是「防注销洗白」的屏障,**不要**为了「让被封禁的人也能注销」把 DELETE 加进白名单。
- **`feed.PostReport` 是 `post=SET_NULL`**:注销用户时,「别人举报他动态」的那些举报行会保留(`post` 置 NULL,运营留档),而「他举报别人」的行随 `reporter` 级联删除。这是既有模型行为,不是 bug。
- **给 `@api_view` 加方法会让文档门禁立刻变红** —— `ApiDocsCoverageTests` 双向比对 URLconf 与 `docs/api/*.md` 的信息行,新增 `DELETE /api/v1/users/me` 必须在同一次改动内写进 `docs/api/users.md`(分册首段的「含 N 个接口」计数也要改)。
- **DRF 的权限检查在方法分发之前**:给 `me` 加 DELETE 后,匿名请求拿 401、重封禁拿 403,都不会落到 405 —— 所以 `test_requires_auth` / 重封禁用例在实现前就是绿的,别被「实现前只有 7 例红」误导。
- **测试里别断言 refresh token 的具体值**:App 启动 `bootstrap()` 会静默刷新一次令牌,存的 refresh 已经不是登录时那个了。要断言「凭证没被清」就用 `isNotNull`。

## 安全加固(2026-10-28)

- **图片必须先看 `size` 再解码**:`config/images.py::open_checked()` 只 `Image.open` 读文件头,检查 `width*height <= 2000 万` 后才允许 `exif_transpose`/`load`。反过来写(先转置再检查)等于让解压炸弹先分配几百 MB;测试用 `patch("config.images.MAX_IMAGE_PIXELS", 100)` + 20×20 图就能覆盖,不必真的造 1.4 亿像素。
- **重编码才等于剥离 EXIF**:只做 `exif_transpose` 不重编码,原始字节里的 GPS 仍在。三个入口(资料图/广场图/聊天图)统一 `normalize()` → 新 PIL 对象 → `save()`,并清空 `info`;测试用 `Image.Exif()` 写入 `0x010F`/`0x8825` 再读回断言不存在。
- **测试环境的 `DEBUG` 是 `False`**:Django 测试运行器会把 `DEBUG` 置 False,所以「空密钥放行」的旧用例会突然变红。媒体签名现在的规则是「未配密钥时只有 `DEBUG` 放行」,相关测试要显式 `@override_settings(DEBUG=True)`,验签类测试则统一给类加 `@override_settings(IM_MEDIA_SIGN_SECRET="s")`(签名与验签必须用同一个 secret,别在 `with` 里签、`with` 外验)。
- **`OPS_OTP_REQUIRED` 在测试里默认 0**:`DEBUG or TESTING` 时默认关闭,否则所有 ops 用例都会被 302 到 `/ops/otp/`。要测门禁必须 `@override_settings(OPS_OTP_REQUIRED=True)`;`force_login()` 只绕过密码,不绕过中间件,所以「已登录未验证」的状态正好可测。
- **TOTP 绑定是「先放 session,确认后才写库」**:首次进入 `/ops/otp/` 生成 `otp_pending_secret` 放 session,用户输入 App 上的码校验通过才写 `User.totp_secret`。不要一生成就写库——用户没绑成功就退出的话,下次登录会拿着一个自己不知道的密钥被锁死。
- **登录锁定用自定义后端,不是中间件**:`accounts/backends.py::ThrottledModelBackend` 在 `authenticate()` 前后计数,`/admin/` 与 `/ops/` 共用;锁定期间直接返回 `None`(与密码错误同表现,不泄漏状态)。测试要 `cache.clear()`,否则上一个用例的失败计数会串。
- **举报去重键在 `save()` 里维护**:`Report.dedupe_key` 是唯一约束,`save()` 会在 `status != pending` 时清空,并把 `dedupe_key` 补进 `update_fields`(只改 `status` 时也能清掉)。并发创建靠唯一约束 + `get_or_create` 回查,不要只在视图里 `filter().exists()` 判重。
- **`NUM_PROXIES=1` 的语义**:DRF 取 XFF 的**最后一段**作为客户端 IP。nginx 必须用 `proxy_set_header X-Forwarded-For $remote_addr;` 覆盖客户端传入值;若继续用 `$proxy_add_x_forwarded_for`,最后一段仍是真实 IP,但前面会保留伪造值,日志里别拿整条 XFF 当可信来源。
- **依赖锁定用 `requirements.lock`,不要直接 `pip install -r requirements.txt`**:`requirements.txt` 只表达区间,lock 是依赖闭包的精确版本(含 gunicorn 与传递依赖)。生成方式:在通过全量测试的环境里,从 `requirements.txt` 的直接依赖出发,用 `importlib.metadata` 递归 `requires`,按 `default_environment()` 合并 `sys_platform=linux` 求值 marker,输出 `名字==版本`。**换 Python 大版本必须重新生成**——celery/redis 的条件依赖(`async-timeout`/`exceptiongroup`)是按 Python 版本挂的。`config/tests.py::DependencyLockTests` 会拦住「加了直接依赖却没进 lock」和「lock 里出现区间」两种情况。
- **ffmpeg 处理上传音频必须给协议白名单**:只加超时不够 —— HLS/concat 这类 playlist 会让 ffmpeg 去拉 http 或读任意本地文件。现在统一 `-protocol_whitelist file,pipe`(输入是临时目录里的文件、输出是本机文件),再加 `-nostdin` + `stdin=DEVNULL` 防交互、`-map_metadata -1 -sn -dn` 丢弃元数据与字幕/数据流、`-threads 1` 限并发。POSIX 下用 `preexec_fn` 设 `RLIMIT_CPU/AS/FSIZE` 兜底解码炸弹;**Windows 没有 `resource` 模块,这段必须按 `os.name == "posix"` 跳过**,否则本地测试直接 ImportError。
- **ops 抽审私聊媒体要留审计**:`ops.MediaAccessLog` 每次打开聊天图片/语音列表写一条(操作人/类型/筛选/条数/IP);列表的 `?reported=1` 只显示「最近 7 天被举报过的发送者」,与举报详情页的证据窗口一致。**审计写失败只能告警,不能 500**——否则 Redis/DB 抖一下运营就看不了队列。
- **抓取监控用 `cache.add` 去重,不要用自增计数**:同一小时内重复看同一个人不该累加,`cache.add(per_target_key)` 返回 False 就跳过;计数 key 首次 `incr` 会抛 `ValueError`(key 不存在),要捕获后 `set(1)`。整段包 `try/except` 静默降级:监控代码永远不能影响资料接口。

## 注释规范

- **规则文档**:`docs/standards/python.md` 是 Python 注释的单一事实来源(模块头模板、`Args`/`Returns`/`Raises` 写法、行内注释禁令、豁免清单)。改注释前先看它,不要自创格式。
- **门禁在哪**:`chatapp/config/comment_coverage.py`(纯标准库 AST 检查)+ `config/tests.py::CommentCoverageTests`。`python manage.py test` 会跑,漏写即红;本地秒级自查 `cd chatapp && python config/comment_coverage.py`(不依赖 Django,不必等测试框架启动)。
- **为什么 `test_*` 用例豁免**:用例名本身就是完整句子(`test_testing_uses_isolated_redis_db`),再补一句 docstring 是纯噪音。同理豁免 `setUp`/`tearDown` 等框架生命周期钩子、`Meta` 这类声明式内部类、函数内的闭包与局部类(测试里大量 `fake_request`/`FakeTask` 打桩属于此类)。
- **为什么口语词只提示不拦截**:`--warnings` 的词典必然误报 —— 「兜底」在技术语境里合法,「踩坑记录」更是规范模板自己要求的写法(所以黑名单对「坑」做了 `(?<!踩)` 排除)。做成硬门禁会逼后人写 `# noqa`,反而降低规范权威性。硬拦的只有三项:模块头缺失、函数/类 docstring 缺失、emoji/`⚠` 类装饰符号。
- **豁免规则一律按名称与嵌套形态判定,不按文件路径**。基于文件名的特判(判断 `test*.py` 还是 `*tests.py`、路径分隔符、大小写)是门禁脚本最容易出错的地方,值得为它放弃几十行注释的「整齐」。
- **改写注释时信息只增不减**:本项目大量注释承载踩坑结论(踢人顺序、`BROKER_URL` 前缀、`account_import` 覆盖行为)。清理语气与格式可以,**技术结论一条都不能丢**。
- **验证「只改了注释」的土办法**:用 `ast.dump` 剥离 docstring 后比对改动前后的 AST,两边一致即证明代码零改动。本次规范化全程用它兜底,抓到过一次补 docstring 时误删函数体的事故。

## 令牌硬化(2026-10-28)

- **Web 的 refresh 只走 Cookie,App 仍走响应体**:`accounts/cookies.py::wants_cookie()` 只认请求头 `X-Client: web`。不要用 User-Agent 判断 —— UA 可伪造且难测;自定义头跨域会触发预检,而生产 CORS 白名单为空,第三方站点发不出来。
- **Cookie 的 `Path` 是 `/api/v1/auth/`**,只在 refresh/logout 两个请求上携带。改成 `/` 会让每个业务请求都带上这个 30 天凭证,暴露面白白扩大。
- **`Secure` 必须跟 `HTTPS_ENABLED` 联动**:本地 http 调试时加 `Secure` 会被浏览器直接丢弃,表现成「登录成功但刷新立刻掉线」。
- **刷新轮换要留宽限(`REFRESH_REUSE_GRACE`,默认 60 秒)**:`BLACKLIST_AFTER_ROTATION=True` 下,两个标签页同时刷新时先到者会把旧 refresh 拉黑,后到者原本会 401 被踢回登录页。轮换时把「旧 jti → 新 refresh」写缓存,命中就复用同一对新令牌(不再轮换);超过宽限的复用视为泄露重放。**宽限不能绕过单设备登录** —— 命中缓存后仍要校验 `session_version`,否则被顶下线的设备能借宽限续命。
- **读 Cookie 分支时别直接碰 `request.data`**:Web 的刷新请求体是空的,DRF 解析空 JSON 体会抛 `ParseError`(400)。`views._body_refresh()` 把它当「没带」处理,再回落到 Cookie。
- **注销必须幂等**:`POST /auth/logout` 对「没有 token / 已过期 / 已拉黑」一律 204。`blacklist()` 可能因缺 `OutstandingToken` 抛异常,这里只能吞掉 —— 注销的目标是「以后不能用」,不是「本次一定拉黑成功」。
- **`response.delete_cookie()` 没有 `secure` 参数**:Django 5.2 的签名是 `(key, path, domain, samesite)`,传 `secure` 会 `TypeError`。要清 Secure Cookie 靠同名同 Path 即可。
