# 登录鉴权与接口实现标准化 设计

日期:2026-09-12
状态:已与用户逐节确认,待写实施计划
上游文档:MVP 总设计 `specs/2026-09-09-dating-app-mvp-design.md`;单设备登录实现见 CLAUDE.md「单设备登录」节
选型决策:经方案对比,用户选定 **Celery + Redis 标准生产栈**(否决:线程池止血方案、独立鉴权服务)

## 1. 背景与目标

### 1.1 触发问题(2026-09-12 多机手测实录)

- 后端日志出现 `Broken pipe from ('127.0.0.1', ...)`:经查(`django/core/servers/basehttp.py:79-83`)这是 Django 捕获 BrokenPipeError/ConnectionAbortedError/ConnectionResetError 后的日志——**客户端在响应写回前已断开**,不是后端故障。
- 同场手测出现「请求了验证码之后仍无法登录」:后端 `session_version` 2→6,证明**后端 4 次登录全部成功**,而前端 4 次都报失败。
- 根因链:
  1. `accounts/views.py:47-53`:登录响应路径里同步调腾讯 IM kick(`IM_TIMEOUT=5` 秒,connect/read 各一份);`transaction.on_commit` 在无事务包裹时**立即同步执行**,并非"响应后执行"——外部调用被卡在响应路径上。
  2. 响应变慢/抖动 → 客户端 dio(10s receiveTimeout)超时后 `request.abort()` 关闭连接(dio 5.11.1 `io_adapter.dart:167`)→ 服务端写响应失败 → Broken pipe;App 侧弹「网络不给力」。
  3. 但验证码在**校验成功那一刻已被删除**(`accounts/services.py:55`),且此时版本已作废、旧设备已踢——用户拿同一个码重试只会得到「验证码已过期」→ 死循环。
  4. 叠加:验证码/限流计数存 Django 默认 LocMem(settings 无 `CACHES`)→ 改任何 .py 触发 autoreload 重启即清空;两台模拟器经 10.0.2.2 转发后源 IP 均为 127.0.0.1,共享同一条 20 次/小时 IP 限流。
- 项目已有正确范式但未统一:`moderation/services.py::_dispatch_async`、`discovery/services.py::_notify_async` 均把 IM 调用丢后台线程;**唯一破例的就是登录路径**。

### 1.2 目标

1. **鉴权端点可用性不被第三方决定**:`/auth/*` 响应路径只做本机 IO(MySQL/Redis),目标 send <50ms、verify <100ms。
2. **所有跨系统副作用异步化**:经 Celery 队列,带重试、幂等、可观测;`transaction.on_commit` 只用于「提交后入队」。
3. **共享状态统一放 Redis**:验证码、限流、锁、幂等标记;LocMem 退役。
4. **登录失败可恢复**:验证码消费带 60 秒幂等重放窗口,客户端网络级失败自动重试一次即可拿回令牌。
5. **建立全后端通用接口规范**:分层、事务、缓存、限流、错误契约与业务码目录、请求追踪、健康检查。
6. **生产形态就位**:gunicorn + nginx + systemd + Redis + Celery worker,为 M4 上线铺路。

## 2. 范围

**做**:
- 基建:Redis(Docker dev / 服务 prod)、Celery worker、gunicorn+nginx 部署形态、健康检查;
- 登录/鉴权链路重构(accounts + notifications + im 的任务化),作为规范的样板实现;
- 全后端对齐:discovery / moderation / users 的 IM 副作用统一切换到 Celery 任务;
- 通用规范落地:分层约定、错误码目录、request_id 与请求日志、限流维度、日志落盘选项;
- 前端配套(仅登录相关):verify 网络级失败自动重试一次、错误文案区分。

**不做**(明确排除):
- 微服务/独立鉴权服务/API 网关;
- `Idempotency-Key` 全局中间件(只立规范,按需再落地);
- Sentry/APM 接入(M4 备选);
- OpenAPI(drf-spectacular)自动文档(契约由本 spec 与 CLAUDE.md 维护);
- 改动单设备产品规则与 SimpleJWT 体系本身(保留 `session_version` 与刷新轮换)。

## 3. 设计原则

1. **鉴权端点零外部依赖**:响应路径只允许 MySQL/Redis;出现 `requests.*`/短信 API/腾讯 REST 即视为违规。
2. **副作用异步化**:跨系统动作必须经任务队列;入队点统一在 `transaction.on_commit(fn, robust=True)`。
3. **共享状态必须放共享存储**:任何在多进程/重启后仍需正确的状态一律 Redis。
4. **状态显式化**:验证码 = 带状态对象(hash: hmac/attempts/consumed),不是裸字符串。
5. **契约稳定**:统一错误体 `{code, message, request_id}`;业务码集中登记。
6. **环境同构**:dev/prod 同一套代码路径,只换配置(12-factor,`.env` 驱动)。

## 4. 基建形态

| 组件 | 开发 | 生产 |
|---|---|---|
| Redis | `chatapp/docker-compose.dev.yml` 容器(`redis:7-alpine`) | 云 Redis / 本机服务,开 AOF |
| Celery worker | 本机 `--pool=solo`(Windows 无 prefork) | systemd,prefork |
| Django | `runserver`(多机手测 `--noreload`) | gunicorn(同步 worker)× nginx |
| MySQL | 本机(现状) | 不变 |

- **Redis 用途与分库**:DB0 = Django 缓存(含验证码/限流/锁);DB1 = Celery broker。生产可用两个实例,代码不变,只改 env。
- **新增依赖**:`celery`、`redis`、`django-redis`;测试追加 `fakeredis[lua]`。
- **配置(env 驱动)**:
  - `REDIS_URL`(默认 `redis://127.0.0.1:6379/0`)、`CELERY_BROKER_URL`(默认 `.../1`);
  - Django `CACHES` 用 django-redis,`KEY_PREFIX=chatapp`,`CONNECTION_POOL_KWARGS.max_connections=50`;
  - `CELERY_TASK_IGNORE_RESULT=True`(副作用任务不需要结果)、`CELERY_TASK_ACKS_LATE=True`、`CELERY_WORKER_PREFETCH_MULTIPLIER=1`、`CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP=True`;
  - 测试环境 `CELERY_TASK_ALWAYS_EAGER=True`。
- **常驻进程(开发)**:`docker compose -f docker-compose.dev.yml up -d` + `celery -A config worker -l info --pool=solo`;与 runserver 并列,写进 CLAUDE.md。
- **Celery 布局**:`config/celery.py`(app + autodiscover);任务写在各自 app 的 `tasks.py`。

## 5. 登录/鉴权链路设计(样板实现)

### 5.1 时序

**`POST /auth/sms/send`(目标 <50ms)**
1. 序列化校验号码(沿用 `PhoneSerializer`);
2. Redis 原子占位:`cache.add("sms:send:{phone}", 1, SMS_RESEND_INTERVAL)` 失败 → 429(`42901`)+ `Retry-After`;
3. 生成 6 位码(dev 固定 `123456`),**HMAC-SHA256 后**存 Redis hash(见 §5.2);
4. 入队 `notifications.tasks.send_sms_code(phone, code)`;入队失败 → **回滚占位与码**(删 `sms:send`/`sms:code`,否则用户被 60s 间隔卡住却收不到码)并回 503(`50301`,必须 fail-closed);
5. 响应 `{"status": "ok"}`。dev 下 `issue_code` 仍直接打日志(手测在 runserver 控制台可见码)。

**`POST /auth/sms/verify`(目标 <100ms)**
1. Redis Lua 原子脚本完成:锁检查 → 取码 → HMAC 比对 → 失败计数(+1,满 5 锁 15 分钟)→ 成功标记 consumed 并保留 60s 重放窗口(见 §5.3);
2. 本地事务:`get_or_create(phone)` → `session_version += 1` 并保存(单设备作废旧令牌机制不变);
3. 签发 access/refresh(SimpleJWT,轮换+黑名单不变);
4. `transaction.on_commit(lambda: im.tasks.sync_login.delay(user_id, created), robust=True)`——**不等它**;
5. 响应 `{access, refresh, is_new_user, user_id}`(契约不变)。

### 5.2 验证码状态机(Redis 键表)

| 键 | 类型 | 内容 | TTL |
|---|---|---|---|
| `sms:code:{phone}` | Hash | `h`=HMAC(code)、`n`=失败次数、`c`=consumed 标记 | 初始 = `SMS_CODE_TTL`(300s);成功消费后改写为 `SMS_REPLAY_TTL`(新增配置,默认 60s) |
| `sms:lock:{phone}` | String | 错误超限锁 | 900s |
| `sms:send:{phone}` | String | 重发间隔占位 | 60s |

- HMAC 密钥取 `SECRET_KEY`(专用 salt),防 Redis 数据泄露后直接读出码;
- 脚本原子性保证:并发 verify 只有一个能"首次消费",其余走重放分支;失败计数不丢。

### 5.3 Lua 脚本语义(单脚本,`accounts/sms_codes.py`)

```
KEYS[1]=code key  KEYS[2]=lock key
ARGV[1]=候选码 HMAC  ARGV[2]=最大尝试数  ARGV[3]=锁 TTL  ARGV[4]=重放窗口
返回:0=成功(含重放) 1=已过期 2=错误 3=本次触发锁定 4=已锁定
```

逻辑:`已锁定→4`;`码不存在→1`;`HMAC 不匹配→HINCRBY n 1`,达上限则 `SET lock EX 900` + `DEL code` 并回 3,否则回 2;`匹配→HSET c=1 + EXPIRE 60` 回 0。
Python 侧映射:1→400(`40001` 验证码已过期)、2→400(`40002` 验证码错误)、3/4→429(`42902` 错误次数过多)、0→通过。

### 5.4 幂等重放窗口(解决「响应丢失不可恢复」)

- 校验成功后码不删除,而是缩短 TTL 至 60s 并标记 consumed;
- 60s 内同码再次 verify → 视为合法重放,**重新签发令牌**(版本照常 +1),不再消耗尝试数;
- 安全增量:码在用过后 60s 内仍有效;仍受同号约束、尝试锁与频率限制保护,判定可接受。

### 5.5 单设备登录(机制不变;踢旧 IM 会话挪到 IM 登录边界)

- 保留 `session_version` + JWT claim + 鉴权/刷新校验 + 40101(已实测的标准 token-version 模式);
- **踢旧 IM 会话必须发生在新设备的 IM 会话建立之前**(2026-09-12 手测回归的教训):若把 kick 丢成「响应后异步执行」,新设备此时已经用自己的 userSig 登进 IM,腾讯的 kick 会把这条**新会话一起踢掉**,客户端收到 `onKickedOffline` 就会误报「账号已在其他设备登录,请重新登录」(实测日志:同一个登录 1 秒内出现两次 `user_sig`,即被踢后的静默重登);
- 因此改为**标记 + 边界执行**:`verify` 老账号重登时只写 Redis 标记 `im:kick_pending:{uid}`(TTL 300s)并入队一个**延迟 20 秒**的兜底任务;`POST /im/user_sig`(客户端建 IM 会话前的必经一步)发现标记先**同步踢**(~0.5s,该端点本就是后台异步调用,不阻塞任何 UI)→ 成功才删标记 → 再签发新签名。兜底任务只在「App 压根没来拉签名」时补踢(标记仍在),正常路径它空转;
- 客户端不改:现有 6206/70001 重试继续当安全网;`import_account`(新号建号)仍走任务队列,`/im/user_sig` 的存在性保障(§5.6)兜住时序。

### 5.6 IM 账号供给收敛到 im 域

- `POST /im/user_sig` 增加存在性保障:Redis 标记 `im:imported:{uid}` 缺失时,在该端点内同步 `account_import`(幂等,7015 视为成功)并置标记(TTL 30 天);
- 注册路径的 `account_import` 改为任务队列 best-effort(重试);
- 两者冗余是刻意的(defense in depth):保证任何时刻他人发来的配对/系统消息都能送达。

## 6. 通用接口实现规范

| 主题 | 规范 |
|---|---|
| 分层 | view/serializer(校验与序列化)→ service(事务+业务规则)→ tasks(一切跨系统副作用);view 不直接调第三方 |
| 事务 | `atomic` 只包 DB 写;副作用统一 `transaction.on_commit(fn, robust=True)` 入队;`on_commit` 的语义是「提交后」而非「响应后」 |
| 缓存 | 一律走 Redis;键带业务命名空间(`sms:`/`im:`/`match:`…);任何共享状态禁 LocMem |
| 限流 | DRF throttling(计数在 Redis)。维度:号码(重发 60s,自有键)、IP(`sms_send` 20/小时,`SMS_SEND_IP_RATE` env 可调,dev 放宽)、verify 增加匿名 IP 限流;429 带 `Retry-After` |
| 错误契约 | `{code, message, request_id}`;业务码 = 前 3 位同 HTTP 状态 + 2 位序号,常量集中 `config/error_codes.py`(已有 `40101`;新增 `40001/40002/42901/42902/50301`) |
| 列表接口 | 统一 LimitOffset 分页约定;现有 `/matches`、`/blocks` 一并分页(前端同步适配,排期在最后,可单独取舍) |
| 幂等 | 优先天然幂等(唯一约束,如 swipe);需要时再上 `Idempotency-Key` 约定,本次不建中间件 |
| 可观测 | `RequestIdMiddleware`:接受/生成 `X-Request-Id`,注入响应头与日志(contextvar+Filter),随 Celery header 传递;请求耗时日志(>500ms WARNING);`LOG_FILE` env 开启文件日志(RotatingFileHandler,手测配 `--noreload` 避免双进程写同一文件) |
| 健康检查 | `/healthz` 存活(无依赖);`/readyz` 探 MySQL + Redis 往返,异常回 503,生产 nginx 放行内网 |
| IM 接入 | `im/client.py` 保持纯 REST 封装(永不抛异常)→ `im/tasks.py` 统一重试策略(指数退避+抖动,`max_retries=5`,任务幂等,acks_late);响应路径只允许本地签名 |

**任务清单**(`im/tasks.py`):`sync_login(user_id, created)`、`send_match_notice(a, b)`、`blacklist_add / blacklist_remove(owner, other)`、`ban_notice(user_id, level, reason)`、`ban_lifted(user_id)`、`sync_profile(user_id, kind)`(昵称/头像)。
移除 `moderation.services._dispatch_async` 与 `discovery.services._notify_async`(含其测试 patch 点)。

**notifications app**:`notifications/backends.py`(ConsoleSmsBackend + 生产短信商接口占位,`get_sms_backend()` 由 settings 选择)、`notifications/tasks.py::send_sms_code`。

## 7. 前端配套(仅登录相关)

1. `auth_repository.verifySms` 调用方(login_page):网络级失败(timeout/connection error,`ApiException` 无 statusCode)自动重试 1 次——重放窗口保证安全;4xx 业务错误不重试。
2. 错误文案区分:后端已给「验证码已过期,请重新获取」;网络级失败重试仍失败时提示「网络超时,可直接再次点击登录」,替换笼统的「网络不给力」。
3. 可选(小项):debug 构建下加请求日志拦截器(方法/路径/状态/耗时/错误类型),下次断连两端对账用。
4. 其余前端机制不动(单飞刷新、40101 竞态处理、心跳已达标)。

## 8. 测试策略

- **Redis**:单测用 fakeredis(含 lupa 支持 Lua);适配层 `config/test_cache.py`(FakeRedisCache,复用 django-redis 接口)。若 lupa 在 Windows/CI 不可用,回退方案:测试连真 Redis DB15 + `flushdb`。另留少量「真 Redis」集成用例(无 Redis 自动 skip)。
- **Celery**:测试 `task_always_eager=True`;断言「提交后入队了哪个任务」用 patch `tasks.*.delay`(替换现有 `_dispatch_async`/`_notify_async` 的 patch 点)。
- **新增回归用例**:
  - 重放窗口:同码二次 verify 成功且版本 +1;窗口过期后同码 → 40001;
  - 并发 verify:两路并发只有一次「首次消费」(真 Redis 集成用例);
  - 限流维度:号码 60s、IP 小时额度、锁 15 分钟互不串;
  - **响应路径零外部调用**:verify 请求期间 patch 的 IM REST 函数断言未被调用,仅任务被入队;
  - 入队失败容错:broker 不可用 → login 仍 200(robust),`sms_send` → 503。
- **前端**:verify 网络失败自动重试一次、文案区分两条用例。
- **纪律不变**:跑测试前无需 Docker(除非跑集成用例);`analyze` 零告警;每步全绿再进下一步。

## 9. 落地顺序(每步独立提交、全绿)

1. **基建**:`docker-compose.dev.yml`(redis)、settings(CACHES/Celery/限流 env)、`config/celery.py`、依赖安装、ping 任务跑通;CLAUDE.md 补命令。
2. **accounts + notifications 重构**:验证码状态机 + Lua + 重放 + 任务化 + `/im/user_sig` 保障 + 错误码目录(§5、§6 的错误码部分)。
3. **全后端对齐**:`im/tasks.py` 全任务;discovery/moderation/users 线程调用迁移;request_id/耗时日志;fakeredis 测试基建;分页改造(最后,可取舍)。
4. **部署形态**:gunicorn + nginx + systemd(worker/gunicorn)配置、`/readyz`、部署文档(M4 用)。
5. **收尾**:删除旧线程辅助函数;全量后端/前端测试;CLAUDE.md 更新(新命令/新坑)。

## 10. 风险与取舍

- Windows 上 Celery 只能 `--pool=solo`,与生产 prefork 并发模型不同(代码路径一致,行为无差);文档写明。
- Redis 成新增单点:生产用云 Redis 或开 AOF;`/readyz` 暴露依赖状态。
- 测试从零依赖变为依赖 fakeredis(lupa);Windows 兼容性作为验证项,失败走真 Redis 回退。
- 步骤 3 触碰面大,靠「每步全绿再进下一步 + 分步提交」控风险。
- 分页改造会同步改前端(matches/blockedUsers),排在最后,风险独立。
