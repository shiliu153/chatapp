# P10 · Celery 异步副作用（约 309 行）

> 上一批：[P09 IM 抽象层与签名](P09-IM抽象层与签名.md) · 下一批：[P11 合规与封禁两级](P11-合规与封禁两级.md)
> 预计 2.5 小时 · 本批是所有"跨系统副作用"的汇聚点。读完你能回答：**为什么这个项目的响应能一直很快**

---

## §1 本批目标

1. 说出 Celery 的 broker / worker / task 三者关系，以及本项目为什么用 Redis 当 broker；
2. 解释"任务参数一律传 `user_id`、任务内自己查库"这条纪律的原因；
3. 解释 `client` 返回 False → `tasks` 抛异常 → Celery 重试 这条链；
4. 说出 `request_id` 是怎么从 HTTP 请求传进 worker 的；
5. 知道改了任务代码必须**重启 worker**。

---

## §2 读前必建概念

### 1）三个角色

| 角色 | 是什么 | 本项目的形态 |
|---|---|---|
| broker（消息队列） | 存"待执行任务"的中间件 | Redis 的 **DB1**（`CELERY_BROKER_URL`），开发环境 DB14 |
| producer（生产者） | 把任务推进队列的人 | Django 进程（视图 / service 里的 `task.delay(...)`） |
| worker（消费者） | 从队列取任务并执行 | 单独的进程：`python -m celery -A config worker` |

**没有 worker 时**：任务只是躺在 Redis 队列里，业务照常成功（所以 P08 实验 4 能看到 `LLEN celery` 有消息）。**这正是"响应快"的代价与收益**：用户不等外部调用，代价是"最终一致"（通知可能晚几秒到）。

### 2）为什么参数必须是 `user_id`

任务在**另一个进程**里执行，那里没有 `request`、没有当前用户对象，甚至可能在你入队后几秒才跑。传对象（不可序列化）、传 `request`（进程间不存在）都不行。所以纪律是：**只传 id，任务内自己查库**。好处是任务与"入队时刻"解耦，且天然幂等（重试时重新查最新状态）。

### 3）重试策略的四要素

```python
RETRY_POLICY = dict(autoretry_for=(Exception,), retry_backoff=True, retry_jitter=True, max_retries=5)
```
- `autoretry_for=(Exception,)`：**任务体抛异常就自动重试**（所以任务体必须"失败就抛"，不能吞掉——这正是 P09 里 client 与 tasks 的分工）
- `retry_backoff=True`：指数退避（1s → 2s → 4s …），避免立刻重试又立刻失败
- `retry_jitter=True`：加随机抖动，避免大量任务同时重试造成"惊群"
- `max_retries=5`：上限，超过就彻底失败（日志里能看到）

### 4）`ACKS_LATE` 与"至少一次"语义

settings 第 155 行 `CELERY_TASK_ACKS_LATE = True`：任务**执行完才 ack**，worker 中途崩溃不会丢任务。代价是**任务可能被执行两次**（执行完了但 ack 没送到）。所以任务体必须**幂等**——本项目处处可见这个意识：

- `kick_pending`：先检查标记还在不在（`im/tasks.py` 第 151–152 行）
- `ensure_account`：7015 视为成功（P09）
- `sync_profile`：查不到资料就静默返回

### 5）`request_id` 怎么跨进程

`config/celery.py` 用三个 signal 把它串起来（见 §3 第 1 条）。**实测验证**（下面 §4 实验 3）：消息 header 里确实出现了 `"request_id": "..."`。

---

## §3 精读清单

### 1. `config/celery.py`（44 行）——应用与"追踪 ID 渗透"

| 行 | 在干什么 | 要抓的点 |
|---|---|---|
| 12–13 | `app = Celery("chatapp")` + `config_from_object("django.conf:settings", namespace="CELERY")` | **所有 Celery 配置都来自 Django settings 且必须带 `CELERY_` 前缀**（这条规则解释了 P02 里 `BROKER_URL` 那个坑） |
| 14 | `autodiscover_tasks()` | 自动发现各 app 的 `tasks.py`——所以新增 app 只要写 `tasks.py` 就会被注册 |
| 17–19 | `@app.task def ping()` | 冒烟任务（本册实验用它验证连通性） |
| 22–23 | ⚠️ 注释 | **不要用 `@signal.connect` 装饰器注册 signal**：装饰器会把函数名绑到 signal 对象上，函数就再也无法单独调用/测试。本项目用 `signal.connect(函数)` 显式注册 |
| 26–30 | `_inject_request_id(headers=...)` | `before_task_publish` 时：把**当前请求的 request_id** 塞进消息 header |
| 33–35 | `_bind_request_id(task=...)` | `task_prerun` 时：从 header 取出并写进 contextvar（worker 侧日志从此带上同一个 id） |
| 38–39 | `_clear_request_id()` | `task_postrun` 时清掉（P03 讲过为什么必须清） |
| 42–44 | 三行注册 | 一一对应上面三个函数 |

> 这个文件只有 44 行，却实现了"**HTTP 请求 → 队列 → worker** 的日志串联"，是本项目可观测性设计的核心。P03 实验 4 留下的疑问（"任务日志怎么带上同一个 id"）在这里闭环。

### 2. `im/tasks.py`（160 行）——**本册主体**

| 行 | 内容 | 要抓的点 |
|---|---|---|
| 1–5 | docstring | 三句宪法：①所有腾讯 REST 统一走这里 ②响应路径禁止直接调 ③client 返回 False，这里转异常让重试生效 |
| 20–21 | `RETRY_POLICY` | 见 §2 第 3 点 |
| 23–24 | `KICK_PENDING_TTL=300`、`KICK_BACKSTOP_DELAY=20` | 标记有效期 / 兜底任务延迟（P09 讲过用途） |
| 27–28 | `kick_pending_key(user_id)` | 标记 key 的唯一构造点（**视图与任务共用同一个函数**，避免两边拼错） |
| 31–33 | `_require(ok, what)` | **把 bool 转异常的唯一入口**——这是"client 不抛 / tasks 抛"的分界实现 |
| 36–37 | `_user(user_id)` | 任务内查库；查不到返回 None（任务体据此静默返回） |
| 40–45 | `send_match_notice` | 配对灰条。**注意第 43–44 行：用户被删了就静默返回**——重试也没意义 |
| 48–61 | `blacklist_add` / `blacklist_remove` | 拉黑同步（P11 调用） |
| 64–74 | `ban_notice(user_id, level, reason)` | 封禁通知。**docstring 关键**：heavy 要"先发消息、再踢下线"，且**放在同一个任务内串行**——这样多 worker 也不会打乱顺序 |
| 77–82 | `ban_lifted` | 解封通知 |
| 85–91 | `report_handled(reporter_id)` | 收件人是**举报者**（不是被举报人）——注释特意强调 |
| 94–109 | `post_commented(comment_id)` | 动态被评论通知（P12 用）。三个细节：**第 97 行延迟导入**（避免 app 加载顺序问题）、自己评自己不打扰（104–105）、昵称缺失时降级成 `u<id>`（107） |
| 112–132 | `sync_profile(user_id, kind)` | kind=`nick`/`avatar` 两个分支；**第 129 行**：`MEDIA_BASE_URL.rstrip("/") + photo.file.url` 拼绝对 URL（P02 第 305 行那个配置的唯一使用者）；未知 kind 抛 `ValueError` |
| 135–140 | `import_account(user_id)` | 新用户建号（P05 入队） |
| 143–160 | `kick_pending(user_id)` | 兜底踢：**标记不在就返回**（幂等）；踢成功才清标记；踢失败 `raise` 让它重试 |

### 3. `notifications/`（26 行）

| 文件 | 行 | 内容 |
|---|---|---|
| `tasks.py` | 6–8 | `send_sms_code(phone, code)`：**同样的重试策略**，任务体只有一行——调后端 |
| `backends.py` | 10–17 | `ConsoleSmsBackend.send_code` 只打日志；`get_sms_backend()` 现在两个分支都返回它，注释写明"M4 按 `settings.SMS_BACKEND` 选生产实现" |
| `apps.py` | 6 | app 配置 |

> 读完后回答：**要接入真实短信商，改动范围是什么？**（答：在 `backends.py` 加一个类 + 在 `get_sms_backend()` 里按配置返回 + 在 settings 加一个开关。**调用方 `accounts/views.py` 一行都不用改**——这就是 P04 里"入队"这层间接的价值。）

### 4. 三个管理命令（79 行）

| 文件 | 行 | 用途 | 值得学的写法 |
|---|---|---|---|
| `im_send.py` | 34 | 以某人身份发消息（手测） | `--text` 与 `--notice` 互斥校验（第 24–25 行）；失败 `CommandError` 并提示"看上面的 IM 错误日志（账号没导入会报 7013 之类）" |
| `im_setup_system_account.py` | 21 | 创建"系统通知"账号（一次性环境步骤） | 幂等：已存在视为成功 |
| `im_sync_nicknames.py` | 24 | 全量同步昵称到 IM | 统计成功/失败数，按结果选用 `style.SUCCESS` 或 `style.WARNING` 输出（第 23 行）——**命令的退出观感也是设计的一部分** |

### 5. 回看 settings（第 154–157 行）

| 配置 | 含义 |
|---|---|
| `CELERY_TASK_IGNORE_RESULT = True` | 副作用任务不需要结果（所以 worker banner 里 `results: disabled://`） |
| `CELERY_TASK_ACKS_LATE = True` | 执行完才 ack（见 §2 第 4 点） |
| `CELERY_WORKER_PREFETCH_MULTIPLIER = 1` | 一次只预取一个任务，防止"一个 worker 囤一堆任务而其他 worker 闲着" |
| `CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True` | 启动时 broker 没起来也会重试连接（而不是直接崩） |

---

## §4 动手实验

### 实验 1 · 起 worker，看它把自己介绍清楚

```powershell
cd D:\pycharmproject\chat_app\chatapp
python -m celery -A config worker -l info --pool=solo
```
**实测 banner 关键行（2026-10-09，Celery 5.6.3）**：
```
.> app:         chatapp:0x...
.> transport:   redis://127.0.0.1:6379/1
.> results:     disabled://
.> concurrency: 20 (solo)
[tasks]
  . config.celery.ping
  . im.tasks.ban_lifted / ban_notice / blacklist_add / blacklist_remove / import_account
  . im.tasks.kick_pending / post_commented / report_handled / send_match_notice / sync_profile
  . notifications.tasks.send_sms_code
```
**观察点**：①`transport` 就是 broker 地址（DB1）；②`results: disabled` 对应 `IGNORE_RESULT`；③任务清单证明 `autodiscover_tasks()` 生效。
> `--pool=solo`：Windows 上 Celery 的多进程池不好用，官方推荐 solo（`CLAUDE.md` 也这么写）。

### 实验 2 · 让一个任务穿过队列（端到端）

保持 worker 运行，**另开终端**：
```powershell
# 触发"发验证码":请求路径只入队,真正执行在 worker
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/auth/sms/send `
  -ContentType 'application/json' -Body (@{ phone = "13900000009" } | ConvertTo-Json)
```
**worker 终端的实测输出**：
```
[2026-10-09 18:57:41,752: INFO/MainProcess] Task notifications.tasks.send_sms_code[d95b665a-...] received
[2026-10-09 18:57:41,752: INFO/MainProcess] [短信-控制台] phone=13800138000 code=999999
[2026-10-09 18:57:41,753: INFO/MainProcess] Task notifications.tasks.send_sms_code[d95b665a-...] succeeded in 0.0s: None
```
> ⚠️ 注意这一行**没有** `[request_id]` 前缀：它由 `notifications.backends` 这个 logger 打出，走的是 Celery 接管的 root logger（Celery 格式）。**本项目有两套日志格式**：Django 配置的（`accounts`/`im`/`chatapp.request` 三个 logger，带 `[request_id]`）与 Celery 接管的（不带）。要观察带 id 的任务日志，看 `im` 域的任务失败路径（`im.client` 的 warning/exception）。

### 实验 3 · 亲手验证 `request_id` 进了消息 header（我在 P10 就是这么确认的）

**先停掉 worker**（否则消息会被立刻消费走）：
```powershell
# 在 worker 终端按 Ctrl+C
```
```powershell
cd D:\pycharmproject\chat_app\chatapp
$code = @'
import os, json, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()
from config.request_id import set_request_id
from notifications.tasks import send_sms_code
import redis as redis_lib
from django.conf import settings

broker = redis_lib.from_url(settings.CELERY_BROKER_URL)
set_request_id("manualreq003")                 # 伪造"当前请求的 ID"
send_sms_code.delay("13800138000", "999999")
msg = json.loads(broker.lindex("celery", 0))   # 队列里最老的一条
print("RESULT|request_id|", msg["headers"].get("request_id"))
broker.delete("celery")                        # 清掉实验消息
'@
$code | python - | Select-String 'RESULT'
```
**实测输出**：`RESULT|request_id| manualreq003`
> 结论：`before_task_publish` 把 request_id 写进了消息 header。worker 侧 `task_prerun` 再把它绑回 contextvar——**这就是"一条请求的日志能跨越进程串起来"的机制**。

### 实验 4 · 观察重试（破坏一个外部凭据）

```powershell
# 1) 把 .env 里 IM_SECRETKEY 临时改错(如末尾加一个 x)
# 2) 重启 worker(Ctrl+C 后重新起)
# 3) 触发一个 IM 任务:改自己的昵称(会入队 sync_profile)
Invoke-RestMethod -Method Patch -Uri http://127.0.0.1:8000/api/v1/users/me -Headers $H `
  -ContentType 'application/json' -Body (@{ nickname = "重试测试" } | ConvertTo-Json)
```
预期：worker 日志出现 `Received task ... sync_profile` → `Retrying ... ` 若干次（退避 1s/2s/4s…）→ 最后 `Task ... raised unexpected: RuntimeError: IM sync_profile:nick 失败`，并在 `im.client` 的日志里看到 `IM portrait_set 调用失败`（这行**带 `[request_id]`**，因为 logger 名是 `im`）。
**改回 `.env` 后务必重启 worker**（配置在启动时读取），再触发一次确认恢复成功。

### 实验 5 · 观察"无 worker 时任务积压"

```powershell
# 停掉 worker
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/auth/sms/send -ContentType 'application/json' -Body (@{ phone = "13900000010" } | ConvertTo-Json)
docker exec chatapp-redis redis-cli -n 1 LLEN celery     # = 1(或更多):任务在排队,业务已 200
docker exec chatapp-redis redis-cli -n 1 LINDEX celery 0 | Select-Object -First 1
# 起 worker → 积压消息立刻被消费
```
> 这一步让你亲眼看到"**响应路径与外部调用解耦**"的物理形态：用户已经拿到 200，短信还在队列里等。
> 观察完记得 `docker exec chatapp-redis redis-cli -n 1 DEL celery` 清掉测试消息。

### 实验 6 · 读任务的测试

```powershell
python manage.py test im.tests.ImTaskTests im.tests.ImSideEffectTaskTests --noinput
```
重点读 `im/tests.py`：
- 第 417 行 `test_import_failure_raises_so_celery_retries` —— **测试名直接说明了设计意图**（"抛异常是为了让 Celery 重试"）
- 第 470 行 `test_ban_notice_heavy_sends_then_kicks` —— 断言"先发后踢"的顺序
- 第 495 行 `test_sync_profile_avatar_uses_absolute_url` —— 断言绝对 URL 拼接
- 第 501 行 `test_sync_profile_avatar_without_approved_photo_is_noop`

> 任务体测试的标准姿势：**直接调 `task.run(...)`**（不经过 broker），并 mock 掉 `im.client.*`（腾讯一次都不能真打；见 `docs/pitfalls/testing.md` 第 9–10 条）。

---

## §5 自查题

**Q1. 没有 worker 时，业务会失败吗？**

**参考答案**：不会。视图只做"写库 + 入队"，入队成功即返回成功（P04 的短信接口就是这样）。任务会积压在 broker（Redis DB1）里，等 worker 起来后集中消费。代价是**最终一致**：用户看到"发送成功"时短信还没真发出去。唯一的例外是入队本身失败（broker 挂了）——那时 `sms_send` 会回滚并返回 50301（fail-closed，P04）。

**Q2. 为什么任务参数一律传 `user_id`？**

**参考答案**：任务在另一个进程执行，没有 `request`、没有 ORM 对象可传（也不可序列化）。传 id 让任务与"入队时刻"解耦：重试时会重新查最新状态，天然更幂等。

**Q3. `im/client.py` 返回 False，`im/tasks.py` 为什么要把 False 变成异常？**

**参考答案**：因为 Celery 的重试由**异常**触发（`autoretry_for=(Exception,)`）。如果 tasks 也吞掉失败，重试永远不会发生，任务会"静默丢失"。分层语义：client 负责不发疯，tasks 负责让队列知道"这次没成功"。

**Q4. `ACKS_LATE=True` 带来什么风险？项目怎么应对？**

**参考答案**：任务可能被执行两次（执行完但 ack 丢失时）。应对方式是**把任务体写成幂等的**：`kick_pending` 先查标记还在不在、`ensure_account` 把"已存在 7015"当成功、`sync_profile` 是覆盖式写入、查不到对象就静默返回。

**Q5. `request_id` 是怎么从 HTTP 请求传到 worker 日志里的？**

**参考答案**：三段。①`config/celery.py` 的 `before_task_publish` 把当前 contextvar 里的 id 写进消息 header；②worker 侧 `task_prerun` 从 header 取出并写回 contextvar；③`task_postrun` 清理。实测证据见 §4 实验 3（header 里出现 `manualreq003`）。注意只有配置了 `RequestIdFilter` 的 logger（`accounts`/`im`/`chatapp.request`）才会把它打进日志格式。

**Q6. 改了 `im/tasks.py` 的代码，为什么必须重启 worker？**

**参考答案**：worker 是独立进程，任务代码在它启动时导入并常驻内存；Django 的 `runserver` 自动重载对 worker 无效。不重启就会继续跑旧代码——这是排查"我改了怎么没生效"的第一嫌疑。

**Q7. 要把短信从"控制台后端"换成真短信商，需要改哪些文件？**

**参考答案**：在 `notifications/backends.py` 新增一个后端类、在 `get_sms_backend()` 里按 settings 开关返回它、在 settings 加配置项（可能还有凭据）。**调用方（`accounts/views.py`、`notifications/tasks.py`）一行都不用改**——任务只依赖 `send_code(phone, code)` 这个接口。

---

## §6 卡住时查哪里

| 需要 | 去处 |
|---|---|
| worker 启不来 / 任务不执行 / 重试行为 | [../../pitfalls/backend.md](../../pitfalls/backend.md)、[../../pitfalls/im.md](../../pitfalls/im.md) |
| 测试里怎么 mock 任务 | [../../pitfalls/testing.md](../../pitfalls/testing.md) 第 9–11 条 |
| Celery 配置项语义 | Celery 官方 `configuration` 文档（一次只查一项） |
| 任务与接口的对应关系 | [../../api/im.md](../../api/im.md) |

---

## §7 验收

1. 能画出"视图 → broker → worker → 腾讯 REST"的完整链路，并指出每一步失败会怎样；
2. 实验 2、3、5 亲手跑过：看到过任务被消费、验证过 header 里的 request_id、看到过任务积压；
3. 能解释"两套日志格式"的区别与原因；
4. 读过 `ImTaskTests` / `ImSideEffectTaskTests`，能说出每个 `test_*_raises_so_celery_retries` 在保护什么；
5. 笔记 `docs/learning/backend-notes/P10-Celery.md`，勾掉总纲 P10。
