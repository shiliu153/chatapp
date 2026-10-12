# P09 · IM 抽象层与签名（311 行）

> 上一批：[P08 滑卡与配对](P08-滑卡与配对.md) · 下一批：[P10 Celery 异步副作用](P10-Celery异步副作用.md)
> 预计 2 小时 · 本批讲清"**如何与一个不可靠的外部系统打交道**"，这是全项目最值得抄走的一套工程约定

---

## §1 本批目标

1. 说出 `im/client.py` 的对外约定是什么，以及为什么必须是这个约定；
2. 说出 userSig 的三段构造（JSON → zlib → 腾讯 base64 变体），并能把它解开；
3. 解释 `POST /im/user_sig` 里"先踢旧会话、再签发"的顺序为什么不能反；
4. 说出"IM 账号供给"（建号）为什么放在这个接口里，而不是注册时。

---

## §2 读前必建概念

### 1）跨系统边界的三种姿态

| 姿态 | 表现 | 本项目用在哪 |
|---|---|---|
| 失败就抛（fail fast） | 异常向上传，接口 500 | **绝不用在跨系统调用上** |
| 失败返回 False + 日志 | 调用方决定怎么办 | `im/client.py` 的对外约定 |
| 失败转异常 + 自动重试 | 交给队列与重试策略 | `im/tasks.py`（P10） |

**这个分层是刻意的**：`client` 层只负责"把请求发出去、把结果翻译成 True/False"，不决定业务怎么办；`tasks` 层知道"CELERY 会重试"，所以把 False 变成异常去触发重试（`im/tasks.py` 开头的 docstring 明确写了这句）。

### 2）为什么响应路径禁止第三方调用

一次 HTTP 请求里如果同步调腾讯云：
- 用户要等一个 5 秒超时（`IM_TIMEOUT=5`）；
- 腾讯抖动时，你的接口跟着 500，而业务数据其实已经写成功了；
- 无法重试（请求已经返回了）。

所以本项目纪律是：**响应路径只写库 + 入队**，真正的外部调用在 worker 里做（`CLAUDE.md` 核心契约第 3 条）。

### 3）腾讯云 userSig 的构造（**最容易踩坑的地方**）

```
sig_doc = {"TLS.ver","TLS.identifier","TLS.sdkappid","TLS.expire","TLS.time"}
sig_doc["TLS.sig"] = base64_标准(HMAC-SHA256(SECRETKEY, "TLS.identifier:..\nTLS.sdkappid:..\nTLS.time:..\nTLS.expire:..\n"))
userSig = 腾讯变体base64( zlib.compress( json.dumps(sig_doc) ) )
```
腾讯的 base64 变体：`+` → `*`、`/` → `-`、`=` → `_`。
**注意 `TLS.sig` 用的是标准 base64（会带 `=`），不要一起替换**——`signature.py` 第 6 行注释专门强调这一点。

### 4）为什么要有"待踢标记"（kick_pending）

单设备登录要求：新设备登录时踢掉旧设备的 IM 会话。但"踢"必须发生在**新会话建立之前**，而新会话是客户端拿到 userSig 后才建立的。所以流程被拆成：
1. 登录时只写一个 Redis 标记 `im:kick_pending:<uid>`（P05 第 100–104 行）；
2. 客户端来 `POST /im/user_sig` 时，**先踢、再签**；
3. 同时排一个延迟 20 秒的兜底任务，处理"App 压根没来拉签名"的情况。

`im/views.py` 第 24–25 行的注释记录了一次手测回归：**顺序反了会把本机刚建的会话一起踢掉**，客户端就会误报"账号已在其他设备登录"。

---

## §3 精读清单

### 1. `im/models.py`（3 行）

只有脚手架注释——**IM 域不存任何业务数据**（消息在腾讯侧，业务数据在 accounts/users/discovery 等），所以这个 app 没有 model。`admin.py` 也只有 3 行（同理）。**"一个 app 可以没有模型"这件事本身值得记下来**：app 是按职责切的，不是按表切的。

### 2. `im/signature.py`（55 行）——逐行

| 行 | 在干什么 |
|---|---|
| 1–7 | docstring 把整个流程写成一句话（**先读它，再读代码**） |
| 19–20 | `_b64_variant`：标准 base64 后替换 `+ / =` 为 `* - _` |
| 23–24 | `_b64_variant_decode`：反向替换（调试/测试用） |
| 27–35 | `_hmac_sha256`：把四个 `TLS.*` 字段拼成字符串 → HMAC-SHA256 → **标准** base64 |
| 38–50 | `gen_user_sig(identifier, expire, now)`：`expire`/`now` 可注入（**为了可测试**）；组装 sig_doc → 计算 sig → `zlib.compress` → 变体 base64 |
| 53–55 | `decode_user_sig`：调试用，把 userSig 还原成明文 |

**实测证据（2026-10-09，用本机 `.env` 里的真实凭据）**：
```
sig 前缀      : eJyrVgrxCdYrSy1SslJQMtIz
解码结果      : {'TLS.ver': '2.0', 'TLS.identifier': 'u1', 'TLS.sdkappid': 1600161711,
                'TLS.expire': 604800, 'TLS.time': 1759980000,
                'TLS.sig': 'bvx2GrTxIfXxWQx4RiCyozXjnRtCPKIUavB535W97AY='}
```
注意 `TLS.sig` 结尾是 `=`（标准 base64），整串 userSig 里却看不到 `=`（已被换成 `_`）——**一眼就能验证"两套编码"这个坑**。

### 3. `im/client.py`（211 行）——**本册主体**

| 行 | 内容 | 要抓的点 |
|---|---|---|
| 1–5 | 模块 docstring | "对外**永不抛异常**，失败只记日志并返回 False"——这是全文件的宪法 |
| 18–26 | 文案常量 | 配对灰条文案、系统通知身份 `system_notice`、封禁/解封/举报处理文案、评论通知模板 |
| 29–35 | `_ban_notice_text(level, reason)` | 轻/重封禁两套文案；`reason` 为空时用兜底 `"违反社区规范"` |
| 38–39 | `_random_int()` | 腾讯要求的随机数（1 ~ 2^32-1） |
| 42–54 | `_request(...)`：所有调用的公共骨架 | 参数五个：`sdkappid` / `identifier` / `usersig` / `random` / `contenttype`；`timeout=settings.IM_TIMEOUT`；`raise_for_status()` 把 HTTP 错误变异常（**由调用方的 try/except 接住**） |
| 57–61 | `_check(result, what)` | 腾讯 REST 即使 HTTP 200 也可能返回业务错误码 `ErrorCode != 0` → 记 warning 并返回 False。**"两层错误"（HTTP 层 / 业务层）必须都判** |
| 64–71 | `import_account` | 标准 try/except → `_check` 的模板 |
| 74–92 | `send_custom_elem` | 自定义消息（灰条/通知的载体）。**第 86–87 行注释是关键坑**：REST 的 `identifier` 必须是应用管理员账号（否则腾讯报 60010），而消息的发送方由 body 里的 `From_Account` 决定 |
| 95–100 | `send_match_notice` | **双向各发一条**（这样两个人的会话列表里都会出现这个会话） |
| 103–119 | 黑名单 add/delete + `_black_list` | 第 112 行注释：identifier 语义与 60010 同类问题，**必须用真凭据实测** |
| 122–129 | `kick_user` | 踢在线会话；docstring 说明重封禁必须踢（否则旧的 userSig 最长 7 天还能聊） |
| 132–142 | `ensure_account` | **幂等建号**：已存在（ErrorCode 7015）视为成功。这就是 `/im/user_sig` 敢"每次调用都试一次"的底气 |
| 145–168 | 三个"系统通知"函数 | 封禁说明 / 解封 / 举报处理完成 / 动态被评论 —— 全部以 `system_notice` 身份发 |
| 171–185 | `send_text` | 普通文本（手测/联调用；业务消息走 App 端 SDK） |
| 188–211 | `set_profile_nick` / `set_profile_avatar` / `_portrait_set` | **两处字段名坑写在注释里**：接口是 `profile/portrait_set`（写错报 60008）、头像字段是 `Tag_Profile_IM_Image`（写成 Url 报 40009） |

> 读完后你应该能自己回答：**如果腾讯把 `sendmsg` 改成需要新参数，你要改几个文件？**（答：只有 `im/client.py`——这就是抽象层的价值。P10 的 tasks 与 P08 的 services 都不用动。）

### 4. `im/views.py`（35 行）——`POST /im/user_sig`

| 行 | 在干什么 | 要抓的点 |
|---|---|---|
| 10 | `IMPORTED_FLAG_TTL = 30 天` | 建号标记的有效期；Redis 被清空后下次调用会幂等重建 |
| 13–15 | 装饰器 + 注释 | 重封禁由全局权限类拦（P11），这里不重复检查 |
| 19–21 | **建号**：没标记就 `ensure_account`，成功才写标记 | 注释解释了设计：**建号归 IM 域自己保证**，失败不写标记、下次再试——这样鉴权路径永不依赖腾讯（即使腾讯挂了，也只是没建号，不影响发签名） |
| 26–28 | **先踢旧会话，再签发** | 顺序是硬要求（§2 第 4 点）；且**踢成功才清标记**（失败留给兜底任务重试） |
| 30–34 | 返回 `user_sig` / `sdkappid` / `im_user_id` / `expire` | 客户端拿这些初始化 IM SDK |

> ⚠️ 这是全项目**唯一会在响应路径里同步调腾讯 REST** 的地方，而且它是刻意的：客户端必须拿到 userSig 才能连 IM，这一步省不掉。作者用"标记 + 幂等 + 失败不写标记"把它的风险压到最低——**读到这里要能体会到这是权衡后的例外，不是违规**。

### 5. `im/urls.py`（7 行）

`path("user_sig", views.user_sig)` + `config/api_urls.py` 第 12 行 `im/` 前缀 → `POST /api/v1/im/user_sig`。

---

## §4 动手实验

### 实验 1 · 亲手生成并解开一个 userSig

```powershell
cd D:\pycharmproject\chat_app\chatapp
python manage.py shell
```
```python
from im.signature import gen_user_sig, decode_user_sig
sig = gen_user_sig("u1")
sig[:24]                     # 变体 base64 前缀
"_" in sig, "=" in sig       # 应看到 (True/False, False) —— 变体替换掉了 =
decode_user_sig(sig)         # 明文 JSON，含 TLS.sig 且它带 '='
```
**观察点**：同一条串里，外层用变体、内层 `TLS.sig` 用标准 base64。
> 若报 `ValueError: invalid literal for int()`：说明 `.env` 里 `IM_SDKAPPID` 是 `CHANGE_ME`（凭据只在 `.env`，P02 讲过）。

### 实验 2 · 读 userSig 的三个测试（它们就是规格说明）

```powershell
python manage.py test im.tests.UserSigTests --noinput
```
对照读 `im/tests.py` 第 42–63 行：
- `test_encode_then_decode_keeps_fields`（43）—— 编解码往返
- `test_sig_field_matches_official_hmac_formula`（52）—— **用官方公式独立算一遍**再比对（这是"不抄自己实现"的测试写法）
- `test_uses_tencent_base64_variant`（58）—— 断言变体替换确实生效

### 实验 3 · 调一次 `/im/user_sig`（**会真打腾讯 REST**）

```powershell
python manage.py runserver 127.0.0.1:8000
# 另开终端：用 P05 拿到的 access
curl.exe -i -X POST http://127.0.0.1:8000/api/v1/im/user_sig -H "Authorization: Bearer $($login.access)"
```
预期：200 + `{user_sig, sdkappid, im_user_id:"u<你的id>", expire:604800}`。
同时检查 Redis 标记：
```powershell
docker exec chatapp-redis redis-cli GET im:imported:1        # =1（若账号此前不存在，这一步刚建号）
docker exec chatapp-redis redis-cli TTL im:imported:1        # ≈2592000
docker exec chatapp-redis redis-cli KEYS "im:kick_pending:*"
```
> ⚠️ 这个接口每次调用都会真调腾讯（建号是幂等的，但仍然是网络往返）。**不要放进循环里刷**。

### 实验 4 · 先踢后签的顺序

```powershell
# 手工打上"待踢"标记，模拟"刚在别的设备登录过"
docker exec chatapp-redis redis-cli SET im:kick_pending:1 1 EX 300
# 再拉一次签名
curl.exe -s -X POST http://127.0.0.1:8000/api/v1/im/user_sig -H "Authorization: Bearer $($login.access)" | Out-Null
docker exec chatapp-redis redis-cli GET im:kick_pending:1    # 已被清掉 → 说明"踢"执行成功
```
配合读测试 `im/tests.py` 第 383 行 `test_pending_kick_runs_before_issuing_sig`：它**断言了调用顺序**（先 kick 后 gen），这就是"顺序不能反"的回归防线。

### 实验 5 · 观察"永不抛异常"的降级

```powershell
python manage.py test im.tests.ImClientTests --noinput
```
读第 65–251 行：几乎每个业务函数都有 `test_*_network_error_returns_false` 与 `test_*_error_returns_false` 两个用例。**这是本项目测试覆盖率的来源**——每条外部调用都有"网络炸了"和"腾讯报错"两套断言。

### 实验 6 · 手测工具：以某人身份发消息

```powershell
python manage.py im_send --from u1 --to u8 --text "你好呀"
python manage.py im_send --from u1 --to u8 --notice          # 发配对灰条
python manage.py im_send --from u1 --to u8                    # 报错：--text 和 --notice 必须二选一
```
`im_send` 的实现（`im/management/commands/im_send.py`，34 行）很短，值得读：`add_arguments` + 互斥校验 + `CommandError` + `self.style.SUCCESS`。

---

## §5 自查题

**Q1. `im/client.py` 的函数为什么统一"返回 False 而不是抛异常"？那谁负责重试？**

**参考答案**：响应路径不能因为第三方抖动而失败，且 client 层不该替业务决定"要不要重试"。所以 client 只把结果翻译成 True/False 并记日志；重试交给 `im/tasks.py`——它用 `_require(ok, what)` 把 False 转成 `RuntimeError`，从而触发 Celery 的 `autoretry_for=(Exception,)` 策略（P10）。**分层：client 管"发出去"，tasks 管"重试"，services 管"什么时候发"。**

**Q2. 为什么 `TLS.sig` 用标准 base64，而整串 userSig 用变体？**

**参考答案**：腾讯只要求最外层 userSig 用它的 base64 变体（`+ / =` → `* - _`）；内部的 `TLS.sig` 是 HMAC 摘要，按官方公式用标准 base64。`signature.py` 第 6 行与实验 1 都能验证这一点（内层带 `=`、外层没有）。

**Q3. `POST /im/user_sig` 为什么"先踢后签"？顺序反了会怎样？**

**参考答案**：客户端的流程是"拿到签名 → 建立新 IM 会话"。若先签发再踢，踢的请求可能落在新会话建立之后，把**本机刚建的会话**一起踢掉——客户端收到 KickOffline 会误报"账号已在其他设备登录"（`im/views.py` 第 24–25 行记录的手测回归）。

**Q4. 建号（`ensure_account`）为什么放在这个接口里，而不是用户注册时？**

**参考答案**：两条理由（写在 `im/views.py` 第 17–18 行注释）：①注册流程（`accounts/views.py` 第 98 行）只入队 `import_account` 任务，响应路径不碰腾讯；②把"账号供给"归 IM 域自己保证——不依赖注册任务是否成功，任何时刻第一次拉签名都能幂等补齐（`ensure_account` 把 7015 视为成功）。带 30 天标记只是省掉重复的网络往返。

**Q5. 为什么腾讯 REST 要判两层错误？**

**参考答案**：HTTP 层错误（4xx/5xx、超时）由 `raise_for_status()` / 异常捕获处理；业务层错误是 HTTP 200 但 body 里 `ErrorCode != 0`（如 60010 参数错、7015 已存在、60008 接口名错）。只看 HTTP 状态会把业务失败当成功。

**Q6. IM 域为什么没有 `models.py` 内容？**

**参考答案**：消息实体存在腾讯侧，业务数据在其他 app。IM 域的职责是"封装外部调用 + 把副作用收口到队列"，它自己不需要表。**app 的边界是按职责切的，不是按表切的。**

---

## §6 卡住时查哪里

| 需要 | 去处 |
|---|---|
| IM 相关全部坑（userSig / 60010 / 踢人 / 消息类型 / 聊天 UI） | [../../pitfalls/im.md](../../pitfalls/im.md)（**本册必读**） |
| 接口契约 | [../../api/im.md](../../api/im.md) |
| 单设备登录的三条退出路径 | [../../pitfalls/im.md](../../pitfalls/im.md)、P05 |
| 腾讯云官方 | 只查你要用的那一个接口的文档（别通读） |

---

## §7 验收

1. 能默画 userSig 的构造流程，并说出"两套 base64"的坑；
2. 实验 1、4 亲手跑过：解开过自己的 sig、看到过 `kick_pending` 被清掉；
3. 能用自己的话解释"为什么 client 永不抛异常，而 tasks 必须抛异常"；
4. 读过 `im/tests.py` 的 `UserSigTests` 与 `ImClientTests`，知道测试怎么防这两类坑；
5. 笔记 `docs/learning/backend-notes/P09-IM抽象层.md`，勾掉总纲 P09。
