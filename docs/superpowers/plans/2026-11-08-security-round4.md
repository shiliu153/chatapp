# 第四轮安全审计整改设计（2026-11-08）

- 状态:**已实施 / 已合并**（7 张实现单与两项人侧内联全部落地，只剩 A2「Redis 口令」在人侧未做；
  逐单结果见 §0 的「状态」列与 §11「执行结果」，风险闭环口径见 [报告 §3](../security/2026-11-08-api-security-audit-round4.md)）
- 依据:[docs/security/2026-11-08-api-security-audit-round4.md](../security/2026-11-08-api-security-audit-round4.md)（以下简称「报告」）
- 执行方式:设计与评审在本机会话内联完成；**实现走 Issue → superagent worker**。
  只有两项留在人侧内联（`deploy/` 与 CI 工作流，`AGENTS.md` §六 明确禁止 agent 改 `deploy/`）。
- 一单一条栈；契约联动（OpenAPI / `docs/api/*.md` / 注释覆盖）算同栈附带改动。

## 0. 工单总表

| 单号 | 报告项 | 栈 | 标题 | Issue | 依赖 | 状态（issue → PR → 合并 SHA） |
|---|---|---|---|---|---|---|
| R4-A1 | H-1 | backend | 关掉缓存 pickle 反序列化面 + 准入名单快照自证 | #125 | — | **已合并** · #125 → #138 → `57e17e2` |
| R4-B1 | M-1 | backend | 准入名单 fail-closed + 部署期 `check` 硬门禁 | #128 | A1（同改 `settings.py`） | **已合并** · #128 → #141 → `9127e82` |
| R4-C1 | M-3 | backend | 三个新读接口补按用户限流 | #129 | B1（同改 `settings.py`） | **已合并** · #129 → #142 → `8ed6209` |
| R4-B2 | M-2 | backend | 准入名单启停写审计事件 | #130 | B1（同改 `accounts/`、`ops/`） | **已合并** · #130 → #144 → `6093b0d` |
| R4-E1 | M-5 | backend | 推送设备易主留痕 + 通知原账号 | #131 | C1（同改 `notifications/views.py`） | **已合并** · #131 → #145 → `7f1909b` |
| R4-E2 | L-2 | backend | 客户端错误上报降级 + 60 秒采样 | #126 | — | **已合并** · #126 → #136 → `748ef7b` |
| R4-E3 | L-9 | web | 错误上报的 route 去掉 query string | #127 | — | **已合并** · #127 → #139 → `23dce11` |
| R4-F1 | F 批 | docs | runbook / pitfalls / push 文档口径补齐 | #132 | 全部合并后 | **本单** · #132 → PR #146（收尾文档，见 §11「执行结果」） |
| I-1 | M-4 | CI（人） | 自动合并白名单收窄到「无指令语义」的 docs 子集 | — | 人侧内联 | **已合并** · PR #134 → `2011b24` |
| I-2 | L-8 | deploy（人） | 备份拉取脚本远端文件名转义 | — | 人侧内联 | **已合并** · PR #135 → `6964c1e` |
| （计划外） | — | scripts | prune 不再把 0 提交的空 worktree 判成已合并 | — | 派单途中发现 | **已合并** · PR #140 → `1ba82c8` |
| A2 | H-1 剩余 | deploy（人） | 开启 Redis 口令（`requirepass`） | — | 人侧内联（见 §2） | **未做（人侧）** · RCE 面已由 A1 关闭、口令未开 |
| — | L-1/L-3/L-4/L-5/L-6/L-7 | — | 只记录为已知风险 | — | 不排期 | **记录**（本轮不排期） |

> 报告与设计本身（PR #133 → `cdaafbc`）是本计划的出处，不计入上表的整改单。

**并行约束**：worker `maxWorkers=3`，但**同一文件被两单同时改会在合并时冲突**。因此按「文件所有权」排波次：

- 波次 1（互不重叠）：**A1**（`config/settings.py` + `accounts/allowlist.py`）、
  **E2**（`telemetry/views.py`）、**E3**（`web/src/api/clientErrors.ts`）。
- 波次 2（A1 合并后）：**B1**（`settings.py` + `accounts/services.py` + 新建 `accounts/checks.py`）。
- 波次 3（B1 合并后）：**C1**（`settings.py` + `notifications/views.py` + `feed/*`）、
  **B2**（`accounts/models.py` + `ops/*`）。
- 波次 4（C1 合并后）：**E1**（`notifications/views.py`）。
- 波次 5：**F1**（docs，可自动合并）。

---

## 1. R4-A1（backend）：关掉缓存 pickle 面 + 准入名单快照自证

### 1.1 为什么

报告 §4.1 H-1：Redis 无口令 + 与业务容器同网；`django_redis` 默认
`PickleSerializer`（`django_redis/client/default.py:117` 取默认值、`:576` 每次
`cache.get` 都 `serializer.loads`）。因此「能写 Redis」=「能在 web/worker 进程里执行代码」。
准入名单快照也存在 Redis（`accounts/allowlist.py:53-65`），所以同一个前提还顺带
能绕过准入判定。

**本单只做代码侧两步**：① 把 pickle 换成 JSON，去掉反序列化面；② 让名单快照
自证（签名不符即视为未命中）。**开启 Redis 口令属于部署侧**（A2 人侧，见 §2）。

### 1.2 改什么

**(a) `chatapp/config/settings.py` 的 `CACHES["default"]`**

```python
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "KEY_PREFIX": "chatapp",
        # 关键①:换序列化器,消掉 pickle 反序列化面(同网容器能写 Redis 时不再等于 RCE)。
        # JSON 只认 dict/list/str/int/float/bool/None —— 仓库里现有的缓存值都满足
        # （int / str / list[int] / 空值哨兵 "__null__"），唯一条目是名单快照的
        # tuple(frozenset) ，已在 accounts/allowlist.py 改成 JSON 结构。
        "OPTIONS": {
            "CONNECTION_POOL_KWARGS": {"max_connections": 50},
            "SERIALIZER": "django_redis.serializers.json.JSONSerializer",
        },
        # 关键②:切换序列化器后,旧键里存的还是 pickle 字节,JSON 解析会抛异常。
        # 把 VERSION 从 1 改到 2：新键多一段 `chatapp:2:` 前缀，旧键**永不被读取**，
        # 自然过期。不做这一步，上线后第一批请求会 500。
        "VERSION": 2,
    }
}
```

**顺手可验证的收益（不要为此改代码）**：`cache.incr` 在 JSON 下存的是 `b"0"`
这样的纯数字串，Redis `INCRBY` 能直接命中，`config/cache_utils.bump_version`
从「Lua 判整数失败后退回 get+set」变成原子路径。

**(b) `chatapp/accounts/allowlist.py`**

- 模块常量保留 `ALLOWLIST_CACHE_KEY`。
- 新增 `_sign(active, disabled) -> str`：`hmac.new(_key(), payload, sha256).hexdigest()`，
  `_key()` = `hashlib.sha256(f"allowlist:{settings.SECRET_KEY}".encode()).digest()`
  （派生，不直接用 `SECRET_KEY`）；`payload` = `"\n".join(sorted(active)) + "\x00" + "\n".join(sorted(disabled))`。
- `snapshot()` 读到的缓存值必须是
  `{"active": [...], "disabled": [...], "sig": "<hex>"}` 且 `hmac.compare_digest` 通过；
  否则 `logger.warning("allowlist_snapshot_rejected reason=...")` 并**当作未命中**
  （查库 + 回填）。
- 返回值仍是 `(frozenset(active), frozenset(disabled))`，`services.ensure_phone_allowed`
  的调用签名与语义**不变**。
- 缓存写入也用同一结构（先算 sig 再 `cache.set`）。

### 1.3 验收口径（worker 自证）

1. `scripts/verify.sh backend` 全绿（PR 正文贴末尾 20 行）。
2. 新增用例（放 `chatapp/accounts/tests.py` 或新建 `chatapp/accounts/test_allowlist.py`）：
   - `test_snapshot_value_is_json`：`snapshot()` 之后用
     `django_redis.get_redis_connection("default")` 读原始字节，断言**不以**
     `b"\x80\x04"` 开头、且能被 `json.loads` 解析。
   - `test_tampered_snapshot_is_ignored`：直接往缓存写
     `{"active": ["13900000000"], "disabled": [], "sig": "deadbeef"}`，断言
     `snapshot()` 返回的是**库里**的内容（伪造号不出现）。
   - `test_snapshot_returns_frozensets`：返回值类型是 `frozenset`。
   - `test_snapshot_roundtrip_with_entries`：库里放两条（一启用一停用），
     两次 `snapshot()`（第二次必命中缓存）结果一致。
3. `python manage.py test accounts -v 2` 全绿（含既有 `SmsVerifyTests`）。

### 1.4 留给人验（不写成 worker 验收项）

- 生产上线后 `redis-cli --scan --pattern 'chatapp:2:*'` 有键、`chatapp:1:*` 只减不增。
- 观察 `chatapp.allowlist` 日志无 `snapshot_rejected` 刷屏。
- Redis 口令（A2）与本单**分两次上线**：先本单（换序列化器 + 版本号），再开口令。

### 1.5 禁止

不改 imserver；不改 `deploy/`（`AGENTS.md` §六）；不动验证码/名单的**准入语义**
（那是 B1）；不删 `config/cache_utils.NULL` 哨兵；不为了 `incr` 原子性改动调用方。

---

## 2. A2（人侧，不派单）：开启 Redis 口令

不属于 worker 范围（要动 `.env`、compose、重启生产）。顺序与要点：

1. 生成口令 → 同时改三处：`chatapp/.env` 的 `REDIS_URL` / `BROKER_URL`、
   imserver 的 `IM_REDIS_URL`（`redis://:pass@127.0.0.1:6379/2`）、compose 的
   redis 启动参数（`--requirepass`）。
2. `imserver` 侧**无需改代码**：`redis_client.cpp::parse_redis_url` 已支持
   `redis://user:pass@host/db` 并 `AUTH`（E-6②，2026-11-05）。
3. 验收：`redis-cli -a <pass> ping` = PONG；不带口令 `PING` 返回 `NOAUTH`；
   `chatapp readyz` 200；imserver `/internal/healthz` 200；发一条消息成功。
4. 回滚点：先备份 `.env` 与 compose 文件。

---

## 3. R4-B1（backend）：准入名单 fail-closed + 部署期 check 硬门禁

### 3.1 为什么

报告 §4.2 M-1：三个「放行」默认值叠加 —— `SMS_DEV_MODE` 代码默认 `1`
（`settings.py:417`）、名单「库与种子都空即放行」（`accounts/services.py:40-75` 第 5 条）、
一键部署生成的 `.env` 不写 `SMS_PHONE_WHITELIST`。结果是「按默认值 + 一个
`--allow-dev-sms`」= 任意号码可用 `123456` 登录。

### 3.2 改什么

**(a) `chatapp/config/settings.py`** 新增（放在 `SMS_ALLOWLIST_CACHE_TTL` 附近）：

```python
# 名单为空时要不要放行。"" = 按 DEBUG 自动（开发/测试放行，生产拒绝）;
# "1"/"0" 显式覆盖。生产环境留空即 fail-closed：名单空 = 谁都登不进来，
# 而不是「谁都能登进来」——宁可部署失败，也不要静默全开。
SMS_ALLOWLIST_STRICT = os.getenv("SMS_ALLOWLIST_STRICT", "")
```

**(b) `chatapp/accounts/services.py::ensure_phone_allowed`**

- 新增私有 `_strict() -> bool`：读 `settings.SMS_ALLOWLIST_STRICT`；
  `""` → `not settings.DEBUG and not getattr(settings, "TESTING", False)`。
- 第 5 条分支改成：
  - strict：`logger.error("allowlist_empty_strict_reject")` + `raise PhoneNotAllowed()`；
  - 非 strict：保持现行为（放行），并在 docstring 里写明「仅开发/测试」。
- docstring 的「判定顺序」同步更新为 6 条（把 strict 拆成两条）。

**(c) 新建 `chatapp/accounts/checks.py`**（`@register(Tags.security)`）：

- 条件：`not settings.DEBUG` 且 `not settings.TESTING` 且 `settings.SMS_DEV_MODE`
  且 `not settings.SMS_PHONE_WHITELIST` → `checks.Error(id="accounts.E001",
  msg="生产开启了固定验证码(SMS_DEV_MODE=1),但没有任何准入名单种子")`，
  `hint` 必须写清三条出路：① `python manage.py allowlist_seed_import`；
  ② 设 `SMS_PHONE_WHITELIST=13x...`；③ 确认是封闭测试则设 `SMS_ALLOWLIST_STRICT=0`。
- `chatapp/accounts/apps.py::ready()` 里加 `from . import checks  # noqa: F401`。

### 3.3 验收口径

1. `scripts/verify.sh backend` 全绿（贴末尾 20 行）。
2. 新增用例：
   - `test_strict_rejects_when_allowlist_empty`（表空 + 种子空 + `SMS_ALLOWLIST_STRICT=1`
     → `POST /api/v1/auth/sms/send` 403 + `40301`）
   - `test_non_strict_allows_when_allowlist_empty`（`"0"` → 200，开发默认行为不变）
   - `test_strict_still_allows_seed_phone` / `test_strict_still_rejects_disabled_phone`
   - `test_security_check_flags_dev_sms_without_allowlist`：`override_settings`
     后 `checks.run_checks()` 的结果里含 `accounts.E001`
   - `test_security_check_silent_when_seed_present`（不报错）
3. 手工贴一条命令输出（证明 check 真的会红）：
   ```bash
   cd chatapp && SMS_DEV_MODE=1 SMS_PHONE_WHITELIST= DEBUG=0 \
     python manage.py check --deploy 2>&1 | grep accounts.E001
   ```

### 3.4 留给人验

- 生产 `.env` 是否显式设 `SMS_ALLOWLIST_STRICT`；**默认（留空）在生产等于 strict**，
  上线前必须先跑 `allowlist_seed_import` 或配好种子，否则全站登录 403。
- 部署流水线里 `manage.py check` 会因 `accounts.E001` 变红——这是**预期**。

### 3.5 禁止

不改 `SMS_DEV_MODE` 的代码默认值；不改 `PhoneAllowlist` 模型/迁移（那是 B2）；
不改 `deploy/oneclick.sh`（人侧）；不改 `40301` 错误码与错误信封。

---

## 4. R4-C1（backend）：三个新读接口补按用户限流

### 4.1 为什么

报告 §4.2 M-3：`GET /notifications`、`GET /notifications/unread_count`、
`GET /feed/following`、`GET /posts/{id}/comments/{cid}/replies`
都没有 `@throttle_classes`，而它们每请求都要跑聚合 / `COUNT(*)` / 三段 SQL。

### 4.2 改什么

**(a) 新建 `chatapp/notifications/throttles.py`**

```python
class NotificationsThrottle(UserScopedThrottle):
    scope = "notifications"
class NotificationsUnreadThrottle(UserScopedThrottle):
    scope = "notifications_unread"
```

**(b) `chatapp/feed/throttles.py`** 追加

```python
class FollowingReadThrottle(UserScopedThrottle):
    scope = "following_read"
class CommentRepliesThrottle(UserScopedThrottle):
    scope = "comment_replies"
```

**(c) `chatapp/config/settings.py`** 额度（沿用 `_RELAXED` 的既有写法）：

```python
NOTIFICATIONS_RATE = os.getenv("NOTIFICATIONS_RATE", _RELAXED or "240/hour")
NOTIFICATIONS_UNREAD_RATE = os.getenv("NOTIFICATIONS_UNREAD_RATE", _RELAXED or "480/hour")
FOLLOWING_READ_RATE = os.getenv("FOLLOWING_READ_RATE", _RELAXED or "240/hour")
COMMENT_REPLIES_RATE = os.getenv("COMMENT_REPLIES_RATE", _RELAXED or "360/hour")
```
并加进 `DEFAULT_THROTTLE_RATES`：`"notifications" / "notifications_unread" /
"following_read" / "comment_replies"`。

**(d) 加装饰器**

- `notifications/views.py`：`notification_list` → `NotificationsThrottle`；
  `notification_unread_count` → `NotificationsUnreadThrottle`
  （`notification_read` 是写，**不加**，保持现状）。
- `feed/views.py`：`following_posts` → `FollowingReadThrottle`；
  `post_comment_replies` → `CommentRepliesThrottle`。

**(e) 契约文档（同栈附带）**：`docs/api/notifications.md`、`docs/api/feed.md`
的「限流」段落补额度；响应形状**不变**（`429` + `42901` 走全局异常处理）。

### 4.3 验收口径

1. `scripts/verify.sh backend` 全绿。
2. 四个接口各一条「限流生效」用例，做法抄
   `chatapp/discovery/tests.py::VisitsReceivedTests` 里现成的 429 写法：
   逐次请求直到出现 `429`，断言 `body["code"] == 429`（或按现有实现的业务码），
   并断言次数不超过额度。
3. 既有游标分页用例全绿（证明加装饰器没改响应形状）。
4. `docs/api/notifications.md` / `docs/api/feed.md` 的 diff 贴进 PR。

### 4.4 留给人验

生产 `.env` 未覆盖这些新键时用默认额度；如与压测脚本冲突再调。

### 4.5 禁止

不改响应结构、不改游标逻辑、不给写接口加额度、不动其它 scope 的额度。

---

## 5. R4-B2（backend）：准入名单启停写审计事件

### 5.1 为什么

报告 §4.2 M-2：名单是安全边界，但 `/ops/allowlist/` 的加号/启停只写
`is_active` / `note`，**不记操作人**；`created_by` 只覆盖创建，`updated_at` 只是时间戳。

### 5.2 改什么

**(a) `chatapp/accounts/models.py`** 新增模型（+ migration `0005_phoneallowlistevent.py`）：

```python
class PhoneAllowlistAction(models.TextChoices):
    ADD = "add", "加入名单"
    ENABLE = "enable", "重新启用"
    DISABLE = "disable", "停用"
    SEED_IMPORT = "seed_import", "种子导入"

class PhoneAllowlistEvent(models.Model):
    phone = models.CharField("手机号", max_length=20)
    action = models.CharField("动作", max_length=16, choices=PhoneAllowlistAction.choices)
    operator = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                 on_delete=models.SET_NULL, related_name="+")
    note = models.CharField("备注", max_length=100, blank=True, default="")
    created_at = models.DateTimeField("发生时间", auto_now_add=True)
    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["phone", "-created_at"], name="allow_evt_phone_idx")]
```
（模块/类/`Meta` 都要按 `docs/standards/python.md` 写 docstring。）

**(b) 写路径**（都在同一个 `transaction.atomic()` 里，先写库、再 `allowlist.invalidate()`）：

- `ops/views.py::allowlist_add`：新建 → `ADD`；原来是停用 → `ENABLE`；
  本来就在启用 → **不写事件**（只是改备注，避免噪声）。
- `ops/views.py::allowlist_toggle`：按切换后的状态写 `ENABLE` / `DISABLE`。
- `accounts/management/commands/allowlist_seed_import.py`：每导入一条写
  `SEED_IMPORT`（`operator=None`）。

**(c) 展示**：`_allowlist_context` 增 `events`（最近 20 条，`select_related("operator")`），
`ops/templates/ops/partials/allowlist_panel.html` 底部加「最近操作」小表
（时间 / 脱敏号码 / 动作 / 操作人）。

### 5.3 验收口径

1. `scripts/verify.sh backend` 全绿（含新 migration 的 `makemigrations --check --dry-run` 干净）。
2. 用例 4 条：
   - 新增号码 → 1 条 `ADD`，`operator` 是当前 staff；
   - 停用再启用 → `DISABLE` + `ENABLE` 两条，顺序正确；
   - 重复提交已启用号码（只改备注）→ **不新增事件**；
   - `allowlist_seed_import` → `SEED_IMPORT` 且 `operator is None`。
3. `GET /ops/allowlist/` 渲染 200 且模板里出现「最近操作」（抄现有 ops 测试写法）。

### 5.4 留给人验

生产部署要跑 `migrate`（人不代替，但要写进发版/部署步骤）；历史操作无法回填。

### 5.5 禁止

不改 `PhoneAllowlist` 既有字段与语义；不 `drop` 任何列；不做数据回填；
不改 `/ops/` 的鉴权（`staff_required` + OTP 中间件）。

---

## 6. R4-E1（backend）：推送设备易主留痕 + 通知原账号

### 6.1 为什么

报告 §4.2 M-5：`register_device` 用 `update_or_create(registration_id=...)`
直接把设备挂到当前账号，**不校验原归属**。知道别人的 `registration_id` 就能把设备
抢过来（原账号失去推送，且该设备以后收到攻击者的通知）。当前 `PUSH_PROVIDER=off`，
所以现在只是「记录被悄悄改归属」，但一旦打开推送就是真实泄露面。

**产品取舍**：保留「换账号登录 → 设备易主」的语义（否则用户换号后收不到推送），
但要求**留痕**并**通知原账号**。

### 6.2 改什么

`chatapp/notifications/views.py::register_device`：

1. 先 `old = PushDevice.objects.filter(registration_id=...).first()`。
2. 若 `old and old.user_id != me.id`：
   - `logger.warning("push_device_transfer registration_id=%s from_user=%s to_user=%s", ...)`
     （**不要**用 `extra={}` 塞自定义字段，日志格式化器只透出白名单字段）；
   - `transaction.on_commit(...)` 里给原账号写站内通知：
     `notify(old.user, NotificationKind.SYSTEM, target_kind=NotificationTarget.NONE,
     text="你的设备已在另一账号登录,推送已切换")`——注意 `notify` 同步写库、
     偏好过滤用 `system` 开关，调用要放在当前 `transaction.atomic()` 的
     `on_commit` 里，避免回滚后留下脏通知。
3. 其余逻辑（`update_or_create` + 删同账号其它设备）不变。

### 6.3 验收口径

1. `scripts/verify.sh backend` 全绿。
2. 用例 3 条：
   - A 上报 `rid` 后 B 再上报同一 `rid` → 设备行归 B；A 收到 1 条 `SYSTEM` 站内通知；
   - 同账号重复上报 → 不产生通知、不写 transfer 日志（用 `assertLogs` 断言）；
   - B 上报一个全新 `rid` → 不产生通知。
3. 响应仍是 `{"registration_id", "platform"}`，不新增字段（`docs/api/push.md` 由 F1 补语义）。

### 6.4 留给人验

关闭推送时通知只会落在站内通知中心（App/Web 都能看到）；确认产品接受这个提示文案。

### 6.5 禁止

不加模型/不加迁移；不把行为改成「409 拒绝」（会破坏换账号登录体验）；
不改「同账号只留一台设备」的语义；不改 `registration_id` 唯一约束。

---

## 7. R4-E2（backend）：客户端错误上报降级 + 采样

### 7.1 为什么

报告 §4.3 L-2：`POST /api/v1/client-errors` 匿名可调，直接写 `error` 级日志
（`telemetry/views.py:42-55`），既能把日志盘刷满、也能触发基于 `level=error` 的告警；
渲染循环里的同一个异常每秒能上报几十次。

### 7.2 改什么

1. 级别 `logger.error` → `logger.warning`；模块 docstring 补一句
   「本 logger **不参与告警**；服务端健康看 HTTP 5xx 指标」。
2. 60 秒内同一 `platform + message` 只落一条：
   ```python
   digest = hashlib.sha256(f"{platform}\x00{message}".encode()).hexdigest()[:32]
   if cache.add(f"clienterr:sample:{digest}", 1, 60):
       logger.warning("client_error", extra={...})   # 只有第一条落地
   ```
   `cache.add` 抛异常时**照常记**（fail-open，别让 Redis 抖动吞掉错误信息）。
3. `metrics.CLIENT_ERRORS` 仍在**每次**请求上累加（指标要真实计数），只有日志被采样。
4. `docs/api/telemetry.md`（同栈附带）补一行「服务端对同一 message 做 60 秒采样」。

### 7.3 验收口径

1. `scripts/verify.sh backend` 全绿。
2. 用例 3 条：
   - 同一 `platform + message` 连发 3 次 → `assertLogs("chatapp.client_error", WARNING)`
     只出现 1 条；`CLIENT_ERRORS` 指标累加 3；
   - 不同 `message` → 各 1 条；
   - 响应始终 204。
3. 既有 `telemetry` 用例全绿（字段上限、IP 限流不变）。

### 7.4 留给人验

Loki 侧如已有 `logger="chatapp.client_error"` 的告警规则，需要同步改掉（我侧 F1 记录）。

### 7.5 禁止

不改响应码/响应体；不改字段长度上限与 `client_error` 限流额度；不引入新依赖。

---

## 8. R4-E3（web）：错误上报的 route 去掉 query string

### 8.1 为什么

报告 §4.3 L-9：`currentRoute()` 返回 `pathname + search`，分享码/邀请参数会被写进
服务端日志。

### 8.2 改什么

`web/src/api/clientErrors.ts`：

- `currentRoute()` 只返回 `location.pathname`（仍按 `MAX_ROUTE` 截断），
  注释说明「不带 search：query 里可能有分享码等半敏感参数」。
- `describeError` / `rememberRequestId` / 配额逻辑不动。

### 8.3 验收口径

1. `scripts/verify.sh web` 全绿（`type-check` + `lint --max-warnings 0` + `test:run`）。
2. 单测：`web/tests/unit/` 里现有 client-errors 用例（若无则新建）断言
   `route` 不含 `?`：给 `location` 设 `"/chat?code=abc"`，上报体 `route === "/chat"`。
3. 覆盖率门槛不下降（70/60/70/70）。

### 8.4 留给人验

合并后 `npm run build` + 部署 `dist`（发版时一起做，不在本单）。

### 8.5 禁止

不改上报开关（`VITE_ERROR_REPORTING`）、不改配额与去重键、不动 `http.ts` 的拦截器。

---

## 9. R4-F1（docs）：口径补齐

只动 `docs/`，可被 L2 自动合并。

1. `docs/ops/runbook.md`：§6「准入名单日常运维」补首部署步骤
   （`allowlist_seed_import` / `SMS_PHONE_WHITELIST` / `SMS_ALLOWLIST_STRICT` 的三条出路，
   与 `accounts.E001` 的报错原文对照）。
2. `docs/pitfalls/backend.md`：新增「Redis 缓存不能存 pickle」一条
   —— 为什么换 JSON、为什么必须同时改 `CACHES.VERSION`、以及「名单快照要自证」。
3. `docs/api/push.md`：设备易主语义（原账号收到站内通知；`registration_id` 全局唯一）。
4. `docs/ops/observability.md`：`chatapp.client_error` 的日志级别与采样口径；
   若有基于 `level=error` 的告警规则需改。
5. `docs/security/2026-11-08-api-security-audit-round4.md`：把 §3 总表的「状态」
   列按实际合并情况勾掉。

---

## 10. 人侧内联两项

### I-1 自动合并白名单收窄（`.github/workflows/auto-merge.yml`）

- `WHITELIST_PREFIXES` 从 `("docs/")` 改为
  `("docs/api/" "docs/security/" "docs/reviews/" "docs/milestones.md")`；
- 再加一层**显式黑名单**（命中即跳过）：`docs/superpowers/`、`docs/pitfalls/`、
  `docs/ops/`、`CLAUDE.md`、`AGENTS.md`、`CONTRIBUTING.md`；
- 在 `docs/superpowers/specs/2026-11-08-superagent-automation-ladder-design.md` §4
  补一句：「worker 可写 ≠ 可无审入 master：`docs/` 里存在**下一次 agent 会执行的指令**，
  这类目录必须人审」。
- 自验：`bash -n` 不适用（YAML 内联 bash），改为本地跑一次
  `gh workflow view auto-merge.yml` + 用 `workflow_dispatch`（`dry_run=true`）看扫描表。

### I-2 备份拉取脚本转义（`deploy/ops/pull-backup-pi.sh:72`）

- `tar -cf - -- ${missing[*]}` 改成 `printf '%s\0' "${missing[@]}" | $SSH "$TARGET" "cd $REMOTE_DIR && tar -cf - --null -T -"`
  （或对每个名字 `printf '%q'`）；
- 自验：本地造两个文件名（`a b`、`x; echo pwned`）走一遍 dry-run，确认远端没有执行注入。

---

## 11. 派单与收尾清单

1. 波次 1 派单：A1（backend）、E2（backend）、E3（web）—— 三单文件互不重叠。
2. 每个 PR：人评审 →（`app/` 无改动，不需要模拟器）→ squash 合并。
3. **合并后立刻同步本机**：WSL 母体与 Windows 仓库都 `pull --ff-only`，**先 pull 再 prune**，
   然后 `bash scripts/superagent-prune.sh --apply`。
4. 波次 2/3/4 依次派单（见 §0 的并行约束）。
5. 全部合并后跑 `scripts/verify.sh all`，再更新报告 §3 状态列与
   `docs/milestones.md`。

### 执行结果（2026-11-08 收尾，波次 5 / #132）

**7 张实现单全部落地并合入 master**（合并 SHA 见 §0）：A1 `57e17e2`、B1 `9127e82`、
C1 `8ed6209`、B2 `6093b0d`、E1 `7f1909b`、E2 `748ef7b`、E3 `23dce11`；两项人侧内联
I-1 `2011b24`、I-2 `6964c1e` 也已合并 —— 至此 M-1~M-5、L-2、L-8、L-9 全部闭环，
L-1 / L-3~L-7 按报告定为「记录、不排期」。派单途中还修了一处计划外的工具坑
（PR #140 `1ba82c8`：prune 把 0 提交的空 worktree 误判成已合并，且会动在飞工单的 refs）。

**A2（Redis `requirepass`）仍未做，属人侧**：H-1 的两条腿现在只关了一条 —— 代码侧
pickle 反序列化面已消除、名单快照已自证（A1），但 Redis 仍然没有口令。也就是说
「能写 Redis」这个前提还在，只是不再等于「能在 web/worker 进程里执行代码」；按 §2 的
四步开口令之前，H-1 在报告 §3 里只能算「RCE 面已关闭，口令未开」。

**文档口径由本单收尾**（F1 / #132）：runbook §6 补首次部署顺序、pitfalls 补第四轮三条、
push / notifications / observability 的口径与实现对齐、`docs/ops/superagent.md` §4.1
的派单核验窗口从 2 分钟放宽到「3 分钟仍为空再补发」（实测正常轮询约 2.5 分钟）。
