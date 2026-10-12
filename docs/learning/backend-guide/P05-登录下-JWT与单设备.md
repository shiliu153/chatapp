# P05 · 登录（下）：校验、JWT、单设备登录（约 180 行）

> 上一批：[P04 登录（上）发验证码](P04-登录上-发验证码.md) · 下一批：[P06 资料（上）模型与在线状态](P06-资料上-模型与在线状态.md)
> 预计 2–2.5 小时 · 本批是全项目**最有设计含量**的一段：一套"版本号"机制同时实现了单设备登录与令牌作废

---

## §1 本批目标

1. 画出 `POST /api/v1/auth/sms/verify` 的完整链路，说清"新用户"与"老用户"两条分支；
2. 说出 JWT 里有哪些 claim，`user_id` 为什么是**字符串**；
3. 用自己的话解释**单设备登录**是怎么实现的（`session_version` 世代号）；
4. 说明 `transaction.on_commit(..., robust=True)` 到底在保证什么；
5. 解释"幂等重放窗口"解决了什么真实问题。

---

## §2 读前必建概念

### 1）JWT 是什么（够用版）

三段 base64url 用 `.` 拼接：`header.payload.signature`。
- header：算法（本项目 HS256）
- **payload（claims）**：`token_type`、`exp`、`iat`、`jti`、`user_id`、以及本项目自己加的 `session_version`
- signature：用 `SECRET_KEY` 对前两段签名 → 服务端不查库也能确认"这令牌是我签的、没被改过"

**payload 是明文可读的**（只是被 base64 编码），所以绝不能往里放敏感信息。

### 2）版本号（世代号）机制

不要试图"记住哪台设备在线"，而是：
- 用户表上有一个整数 `session_version`（`accounts/models.py` 第 34 行，默认 1）；
- **每次登录 +1**，并把当前值写进签发的令牌；
- 鉴权时比对"令牌里的版本"与"数据库当前值"，不一致 → 这个令牌过期了 → 401 + `40101`。

新设备登录使旧的令牌全部作废（因为版本变了），天然实现"单设备在线"。同时这也是**不需要黑名单就能让 access 失效**的办法（access 本来无状态、无法撤销）。

### 3）`transaction.on_commit(fn, robust=True)`

- `on_commit`：把 `fn` 排到"当前数据库事务**成功提交**之后"执行。为什么要这样？如果先入队再把数据库操作回滚了，worker 就会处理一个**不存在的用户/订单**。
- `robust=True`（Django 4.2+）：回调抛异常时**记录日志但不向上传播**。这里的作用是——登录已经提交成功了，broker 抖动不该把这次成功登录变成 500。

### 4）幂等重放窗口

客户端可能因为网络问题没收到响应而重试同一个验证码。若严格"一次消费即失效"，用户会以为码错了。所以：校验成功时**不删码**，而是把 `c=1` 标记 + 把 TTL 缩短到 `SMS_REPLAY_TTL=60`，于是**同一码在 60 秒内可以再换一次令牌**。这就是 P04 那段 Lua 第 33–35 行的用意。

### 5）`get_or_create` 与"号码没注册过自动建号"

`User.objects.get_or_create(phone=phone)` 返回 `(user, created)`。`created=True` 就是新用户——UI 用它决定是否跳"完善资料"引导。

---

## §3 精读清单

### 1. `accounts/models.py`（47 行）——自定义用户模型

| 行 | 在干什么 |
|---|---|
| 5–24 | 自定义 `UserManager`：`create_user` 用 `set_unusable_password()`（**短信登录的账号没有可用密码**，这是安全上正确的做法）；`create_superuser` 才用真密码（运营台管理员） |
| 27 | `SESSION_VERSION_DEFAULT = 1` |
| 30–34 | `class User(AbstractUser)`：`username = None`（去掉用户名字段）、`phone` 唯一、`session_version` |
| 36–37 | `USERNAME_FIELD = "phone"`、`REQUIRED_FIELDS = []`——告诉 Django"登录标识是手机号" |
| 41–44 | `im_user_id` 属性：`f"u{self.id}"`。**跨栈约定：全项目只在这里拼 IM 账号**，别处一律用这个属性（P09/P10 会反复出现） |
| 46–47 | `__str__` |

### 2. `accounts/tokens.py`（25 行）——往令牌里加 claim

| 行 | 在干什么 |
|---|---|
| 10–15 | `SessionAccessToken.for_user`：先让父类签发标准令牌，再 `token["session_version"] = user.session_version` |
| 18–25 | `SessionRefreshToken`：**第 19 行 `access_token_class = SessionAccessToken`** 是关键——刷新时签出的新 access 也会带上这个 claim。第 21–24 行同样注入版本 |

> 读法提示：这里用的是"继承 + 覆写类方法"而不是"签完再改字典"，因为 `for_user` 是 simplejwt 的扩展点。

### 3. `accounts/authentication.py`（23 行）——鉴权侧

| 行 | 在干什么 |
|---|---|
| 15–17 | 继承 `JWTAuthentication`，覆写 `get_user` |
| 19 | `token_version = validated_token.get("session_version", SESSION_VERSION_DEFAULT)`——**兼容历史令牌**（签发前没有该 claim 的，按初始版本处理） |
| 20–21 | 版本不一致 → `raise SingleDeviceSessionConflict()` → 401 + `40101` |
| 22 | `touch(user.id)`——**认证通过即刷新"最后活跃"**（P06 的在线状态钩子）；注释说明它内部静默兜底 |

> 这个类是 settings 第 211 行的 `DEFAULT_AUTHENTICATION_CLASSES`，所以**每个需要鉴权的接口都会走这里**——这是全项目最"高频执行"的自研代码之一。

### 4. `accounts/views.py` 第 80–114 行 —— `sms_verify`

| 行 | 在干什么 | 失败出口 |
|---|---|---|
| 80–82 | `@api_view(["POST"])` + 公开 + `SmsVerifyThrottle`（IP 维度） | 超限 → 429 |
| 84–85 | `SmsVerifySerializer`：手机号 + 6 位码 | 格式错 → 400 |
| 87 | `services.check_code(phone, code)` | `40001` 过期 / `40002` 错误 / `42902` 锁定（P04） |
| 89 | `User.objects.get_or_create(phone=phone)` | 首次登录自动建号 → `created=True` |
| 91–93 | **`session_version += 1` 并 `save(update_fields=[...])`** | 作废旧令牌；只更新这一列，减少写放大 |
| 95–106 | `_after_commit`：**新用户** → `im_tasks.import_account.delay(user.id)`；**老用户** → 写"待踢"标记 + `kick_pending.apply_async(countdown=...)` 兜底 | 见下方"两条分支" |
| 106 | `transaction.on_commit(_after_commit, robust=True)` | 回调异常不拖垮登录 |
| 108–114 | `SessionRefreshToken.for_user(user)` → 响应 `{access, refresh, is_new_user, user_id}` | — |

**两条分支为什么要分开**（第 96–104 行的注释是原始设计说明）：
- 新用户：腾讯云侧还没有这个 IM 账号 → 需要 `import_account` 建号；
- 老用户：旧设备可能还挂着 IM 会话 → 需要踢掉。而"踢"必须**早于新会话建立**，所以流程是：本次登录**只打一个标记** `kick_pending_key`，等新设备去 `POST /im/user_sig` 拉签名时先同步踢；同时排一个延迟任务兜底"App 压根不来拉签名"的情况。（细节在 P09/P10 与 `docs/pitfalls/im.md`。）

### 5. `accounts/views.py` 第 117–128 行 —— 刷新时也校验版本

| 行 | 在干什么 |
|---|---|
| 117–118 | 继承 `TokenRefreshView`，docstring 说明意图：旧设备的 refresh 一并作废 |
| 120–124 | 先尝试构造 `SessionRefreshToken`；格式不合法就让父类去报错 |
| 125–127 | 查用户，`token.session_version != user.session_version` → `SingleDeviceSessionConflict`（40101） |
| 128 | 校验通过才交给父类（父类负责轮换 + 把旧 refresh 拉黑，settings 第 285–286 行） |

> **为什么不能只靠 settings 的 `BLACKLIST_AFTER_ROTATION`？** 因为那只能作废"被轮换过的那一个" refresh；顶号场景下旧设备的 refresh 根本没被轮换过，必须靠版本号判死。

---

## §4 动手实验

### 实验 1 · 完整登录一次，并解析 JWT

```powershell
cd D:\pycharmproject\chat_app\chatapp
python manage.py runserver 127.0.0.1:8000        # 终端 A

# 终端 B：先拿码（若 60 秒内已发过，会 42901，等一会儿或换个号码）
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/auth/sms/send `
  -ContentType 'application/json' -Body (@{ phone = "13900000001" } | ConvertTo-Json)

$login = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/auth/sms/verify `
  -ContentType 'application/json' -Body (@{ phone = "13900000001"; code = "123456" } | ConvertTo-Json)
$login | Format-List
$login.access | Set-Clipboard      # 方便粘贴
```
预期：`is_new_user: True`、`user_id: <数字>`、`access`/`refresh` 两段长字符串。

解析 payload 看 claim：
```powershell
$t = (Get-Clipboard).Trim()
$p = $t.Split('.')[1]; while ($p.Length % 4) { $p += '=' }
[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($p.Replace('-','+').Replace('_','/')))
```
**观察点**：`"user_id":"1"` —— **是带引号的字符串**。这是全项目契约（`CLAUDE.md` 核心契约、`docs/api/conventions.md`）：JWT 的 `user_id` claim 是字符串，而 `GET /users/me` 响应里的 `id` 是 profile 表主键、`user_id` 才是账号 ID（P07 会看到两者不同）。

### 实验 2 · 单设备顶号（用"重放窗口"制造第二次登录，不用等 60 秒）

```powershell
$old = $login.access
# 60 秒内用同一个码再登录一次 —— 走 Lua 的重放分支，同样会 session_version += 1
$login2 = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/auth/sms/verify `
  -ContentType 'application/json' -Body (@{ phone = "13900000001"; code = "123456" } | ConvertTo-Json)

# 用旧 access 打受保护接口
try { Invoke-RestMethod -Uri http://127.0.0.1:8000/api/v1/users/me -Headers @{ Authorization = "Bearer $old" } }
catch { $_.Exception.Response.StatusCode.value__; $_.ErrorDetails.Message }
```
预期：**401** + `{"code":40101,"message":"账号已在其他设备登录,请重新登录",...}`。

**刷新接口也一样**（用 `$login.refresh` 去打 `POST /api/v1/auth/token/refresh`）→ 同样 40101。这两条都有现成测试：`accounts/tests.py` 第 317 与 328 行。

### 实验 3 · 幂等重放（实验 2 已顺带验证了它）

用同一个 code 连续两次 `verify` 都能成功 → 这就是 `SMS_REPLAY_TTL=60` 的效果。测试见 `accounts/tests.py` 第 163 行 `test_replay_within_window_issues_new_tokens` 与第 224 行 `test_success_shrinks_ttl_to_replay_window_and_allows_replay`。**顺带观察 Redis**：
```powershell
docker exec chatapp-redis redis-cli TTL sms:code:13900000001   # 成功校验后被缩到 ≤60
docker exec chatapp-redis redis-cli HGET sms:code:13900000001 c # =1 表示已消费
```

### 实验 4 · 直接读"顶号"的测试

```powershell
python manage.py test accounts.tests.SingleDeviceSessionTests accounts.tests.TokenRefreshTests --noinput
```
读 `accounts/tests.py` 第 284–334 行。注意它怎么构造"第二台设备"（直接调接口而不是伪造令牌）——这是本项目测试的典型风格：**从 HTTP 边界进，不 mock 自己人**。

### 实验 5 · 观察"认证通过即刷新在线状态"

```powershell
# 用有效 access 连续打两次 /users/me，然后看 Redis 里的 presence key
docker exec chatapp-redis redis-cli KEYS "presence*"
```
（具体 key 形态在 P06 讲；这里只要确认"**一次受保护请求会留下在线痕迹**"这件事由 `authentication.py` 第 22 行触发。）

---

## §5 自查题

**Q1. JWT 的 `user_id` 为什么是字符串？**

**参考答案**：JWT 规范（RFC 7519）要求 claim 值是可序列化类型，simplejwt 把 `user_id` 按字符串写入（因为它由 `get_user_id` 返回 `str(user.pk)`）。项目把这个事实固化为契约：客户端解析时不要假设它是数字。实测 payload 里是 `"user_id":"1"`。

**Q2. 单设备登录为什么不用"把旧令牌加黑名单"？**

**参考答案**：access 令牌是无状态设计的，若为每个 access 都维护黑名单，等于每次鉴权都要查一次黑名单表（还要清理），代价高且易漏。版本号方案只需在用户表上比对一个整数，天然覆盖**所有**由旧版本签发的 access 与 refresh，包括还没到期的。

**Q3. 登录流程里，`session_version += 1` 为什么必须在签发令牌之前？**

**参考答案**：令牌里的 `session_version` 是签发时从用户对象上读的（`tokens.py` 第 14 行）。先自增再签发，新令牌才带最新版本、才是"有效的那一个"；顺序反了就会一登录就被自己判死。

**Q4. `transaction.on_commit(..., robust=True)` 的两个关键词各解决什么问题？**

**参考答案**：`on_commit` 保证"数据库提交成功之后"才执行副作用，避免 worker 处理不存在的数据；`robust=True` 保证回调里的异常（如 broker 抖动）只记日志、不向上传播，不会把一次已经成功的登录变成 500。

**Q5. 老用户登录时为什么不直接调 IM 接口踢掉旧会话？**

**参考答案**：两个原因写在 `views.py` 第 100–101 行：①响应路径禁止任何第三方网络调用（延迟 + 失败会拖慢/污染登录）；②"踢"必须**早于新会话建立**，而新会话是在客户端随后拉 `user_sig` 时才建立的，所以要先打 `kick_pending` 标记，让 `/im/user_sig` 在签发前同步踢；延迟任务只作为"App 不来拉签名"的兜底。

**Q6. 为什么刷新接口也要自己校验版本（settings 里不是已经配了轮换 + 拉黑）？**

**参考答案**：`BLACKLIST_AFTER_ROTATION` 只能作废"被这次刷新替换掉的那个 refresh"；顶号场景下旧设备的 refresh 从未被轮换，黑名单里不会有它。只有版本号能判死它（`views.py` 第 125–127 行）。

---

## §6 卡住时查哪里

| 需要 | 去处 |
|---|---|
| 鉴权与令牌的对外契约 | [../../api/conventions.md](../../api/conventions.md) §鉴权、[../../api/auth.md](../../api/auth.md) |
| 错误码 40101 的语义 | [../../api/errors.md](../../api/errors.md) |
| 单设备登录的三条退出路径 | [../../pitfalls/im.md](../../pitfalls/im.md)（**必读**，这里列了实现细节与坑） |
| simplejwt 扩展点 | simplejwt 官方文档（`Token.for_user`、`access_token_class`） |

---

## §7 验收

1. 能默画 `sms_verify` 链路，并说出新用户/老用户两条分支的差别；
2. 实验 1–3 亲手跑过：解出过 payload、亲眼见过 40101、观察到 `c=1` 与缩短的 TTL；
3. 能用一句话解释"版本号 = 不需要黑名单的令牌作废机制"；
4. 笔记 `docs/learning/backend-notes/P05-JWT与单设备.md`，勾掉总纲 P05。
