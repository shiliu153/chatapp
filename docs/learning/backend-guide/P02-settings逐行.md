# P02 · settings.py 逐行（308 行，分 2 次读）

> 上一批：[P01 请求怎么进门](P01-请求怎么进门.md) · 下一批：[P03 请求怎么出门](P03-请求怎么出门.md)
> 预计 2–3 小时 · **本批是新手最容易崩的一批**：308 行配置没有"剧情"，允许分两次读，但不许跳过

---

## §1 本批目标

1. 说出这个项目的**配置从哪里来**（代码默认值 / `.env` / 环境变量三者的优先级）；
2. 说出 `TESTING` 开关怎么判定、它改变了哪些行为；
3. 说出 `REST_FRAMEWORK` 那一段为什么能让"每个视图不写鉴权代码也有鉴权"。

---

## §2 读前必建概念

### 1）settings.py 是一个被 import 的普通 Python 模块

没有魔法：`config/settings.py` 里就是普通赋值语句。**任何一行的右侧都可以是函数调用**（本项目大量使用 `os.getenv(...)`）。读法：从左往右读"这个配置项叫什么 → 它的值从哪来 → 谁在用它"。

### 2）三层来源与优先级

```
代码里的默认值（os.getenv 第二参数）  <  .env 文件（python-dotenv 读入 os.environ）  <  真实环境变量
```
- 第 18 行 `from dotenv import load_dotenv`、第 23 行 `load_dotenv(BASE_DIR / ".env")`：**settings 被导入时**把 `.env` 的内容灌进 `os.environ`。
- 因为 `load_dotenv` 默认**不覆盖**已存在的环境变量，所以"真实环境变量优先"这条成立。
- 第 21 行 `BASE_DIR = Path(__file__).resolve().parent.parent` 指向 `chatapp/`。

### 3）"开发兜底"与"故意不留兜底"是两种不同意图

- 有兜底：`SECRET_KEY`（第 30 行 `"dev-insecure-change-me"`）、`DEBUG`（第 33 行默认 `"1"`）——为了本地能直接跑。
- **故意无兜底**：第 112–113 行 `DB_PASSWORD` 的默认值是空字符串，且注释写明"代码里不留兜底值（避免把它当成'默认可用'的弱口令）"。**读配置时要能分辨这两种**：有兜底是便利，无兜底是安全决策。

### 4）`TESTING` 开关：用命令行判断"是不是在跑测试"

第 94–95 行：
```python
TESTING = sys.argv[1:2] == ["test"]
```
它在文件后面被用了两处（读的时候要追这两处）：
- 第 118 行 `CONN_MAX_AGE`：非测试 60 秒（持久连接，省掉每请求建连开销），测试 0（保持用例隔离）
- 第 137–143 行：把 Redis 地址换成 `/15`（缓存）与 `/14`（broker）

**实测证据（2026-10-09）**：把 `sys.argv` 伪装成 `["manage.py","test"]` 后读 settings，得到 `TESTING=True`、`CACHES.default.LOCATION = redis://127.0.0.1:6379/15`、`CELERY_BROKER_URL = redis://127.0.0.1:6379/14`。

---

## §3 精读清单

### 第一次读：第 1–152 行

| 行区间 | 内容 | 读的时候要抓的点 |
|---|---|---|
| 13–23 | imports、`BASE_DIR`、`load_dotenv` | `.env` 的加载时机（import 时） |
| 30–35 | `SECRET_KEY` / `DEBUG` / `ALLOWED_HOSTS` | `ALLOWED_HOSTS` 用 `.split(",")` 从字符串变列表；P01 实验里那个 `DisallowedHost` 400 就是它拦的 |
| 40–60 | `INSTALLED_APPS` | 分三段：Django 内置 6 个 / 第三方 3 个（`rest_framework`、`rest_framework_simplejwt.token_blacklist`、`corsheaders`）/ **业务 8 个**（accounts users discovery im moderation ops notifications feed）。第 49 行的 `token_blacklist` 是 P05「刷新即轮换 + 旧 refresh 拉黑」的表来源 |
| 62–72 | `MIDDLEWARE` | **顺序即洋葱层序**。第 63 行 `RequestIdMiddleware` 故意放第 1 位（最外层）→ P03 详解。第 67 行 `CommonMiddleware` 就是 P01 的尾斜杠行为来源 |
| 74 | `ROOT_URLCONF` | 指向 P01 读过的 `config.urls` |
| 76–90 | `TEMPLATES` | `APP_DIRS: True`（各 app 的 `templates/` 自动生效）；第 86 行多注册了一个 `ops.context_processors.ops_badges`（P13 用，给运营台页脚塞角标） |
| 92 | `WSGI_APPLICATION` | P01 已确认：只有 WSGI 生效 |
| 94–95 | `TESTING` | 见 §2 第 4 点 |
| 101–128 | `DATABASES` | 101 行 `utf8mb4`；**102–105 行是性能决策**：本地 MySQL 的 TLS 握手约 250ms，实测每请求 ~280ms 降到 ~22ms，所以 dev 默认 `ssl_disabled=True`，生产置 `DB_SSL_DISABLED=0`；118–119 行持久连接 + 复用前 `SELECT 1` 探活；**120–126 行是环境一致性决策**：显式钉住测试库的字符集/排序规则，否则取 MySQL 8 服务器默认 `utf8mb4_0900_ai_ci`，与 `db_setup.sql` 建的 `utf8mb4_unicode_ci` 不一致，会造成"本地全绿、CI 红" |
| 131–143 | Redis / Celery | 132 行 `REDIS_URL` 默认 `/0`；136 行 `CELERY_BROKER_URL` 默认 `/1`；**133–135 行是本文件最值钱的一条注释**（见 §5 Q1）；137–143 行测试覆盖 |

### 第二次读：第 154–308 行

| 行区间 | 内容 | 读的时候要抓的点 |
|---|---|---|
| 154–157 | Celery 四项 | `IGNORE_RESULT`（副作用任务不存结果）、`ACKS_LATE`（执行完才 ack，任务不丢）、`PREFETCH_MULTIPLIER=1`、启动时重试连 broker。P10 回看 |
| 145–152 | `CACHES` | `django_redis` 后端、`KEY_PREFIX="chatapp"`（与同实例其他项目隔离 key）、连接池 50 |
| 163–176 | `AUTH_PASSWORD_VALIDATORS` | 本项目用短信登录，这套对业务接口基本无感；只有 `createsuperuser`（运营台账号）会用到 |
| 182–188 | 语言/时区 | `zh-hans` + `Asia/Shanghai` + `USE_TZ=True`。**这三个一起解释了 `docs/api/conventions.md` §时间格式 里的两种时间渲染**（带 `+08:00` 与 UTC 带 `Z`） |
| 194–195 | 静态文件 | `STATIC_ROOT` 是 `collectstatic` 产物目录，生产由 nginx 直出 |
| 200 | `DEFAULT_AUTO_FIELD` | 新表的自增主键类型（BigAutoField） |
| 202 | `AUTH_USER_MODEL` | **`accounts.User`**——本项目自定义用户模型。这是"必须在首次 migrate 前定好"的配置项 |
| 204–207 | 限流额度 | 205–206 行 `DEBUG` 下放宽到 200/600 每小时，原因写在注释里：两台模拟器共享 `127.0.0.1` 会互相触发 IP 限流 |
| 209–229 | `REST_FRAMEWORK` | **本批核心**，逐项读（见下） |
| 231–235 | CORS | 允许 `localhost:*` / `127.0.0.1:*`（Flutter Web 调试）；235 行把 `X-Request-Id` 暴露给浏览器 |
| 238–245 | 短信常量 | `SMS_DEV_MODE`、`SMS_DEV_CODE="123456"`、TTL 300、重发 60、最大尝试 5、锁 900、**重放窗口 60**（P04/P05 逐个用上） |
| 247–280 | `LOGGING` | 254 行注册 `RequestIdFilter`；256 行 formatter 里的 `%(request_id)s`；262–267 行只给 `accounts`/`im`/`chatapp.request` 三个 logger（其余走 root）；269–280 行 `LOG_FILE` 可选落盘，**注释警告：手测要配 `--noreload`，否则 autoreload 的两个进程抢写同一文件** |
| 282–287 | `SIMPLE_JWT` | access 30 分钟、refresh 30 天、`ROTATE_REFRESH_TOKENS`（刷新即换新）、`BLACKLIST_AFTER_ROTATION`（旧的立即拉黑） |
| 289–295 | 腾讯云 IM | 凭据只从 `.env` 来；`IM_TIMEOUT=5` 秒（P09 的降级阈值来源） |
| 297–303 | 照片 | `AUTO_APPROVE`（开发期上传即过审）、最多 6 张、单张 ≤5MB |
| 305–308 | 媒体 URL / 登录跳转 | 306 行 `MEDIA_BASE_URL` 的原因写在注释里：**Celery 任务里没有 `request`，拼不出绝对 URL**；308 行 `LOGIN_REDIRECT_URL = "/ops/reports/"`（运营台登录后落到举报列表） |

### `REST_FRAMEWORK`（209–229 行）逐项

| 键 | 值 | 作用 |
|---|---|---|
| `DEFAULT_AUTHENTICATION_CLASSES` | `accounts.authentication.SessionJwtAuthentication` | 全局默认认证方式；**改写了 simplejwt 的认证类**，加了"会话版本"校验（P05） |
| `DEFAULT_PERMISSION_CLASSES` | `IsAuthenticated` + `moderation.permissions.IsNotHeavyBanned` | 全局默认权限：①必须带有效令牌 ②重封禁用户一律 403（P11） |
| `EXCEPTION_HANDLER` | `config.exceptions.api_exception_handler` | 统一错误契约的注入点（P03） |
| `DEFAULT_PAGINATION_CLASS` | `config.pagination.DefaultLimitOffsetPagination` | 默认 20 / 上限 100（P03、P12） |
| `DEFAULT_THROTTLE_RATES` | 8 个业务限流名 | `sms_send`/`sms_verify`/`swipe`/`report`/`post_create`/`post_comment`/`post_report`/`presence`；具体视图用 `throttle_classes` 或 `@throttle_classes` 引用这些名字 |

> **本批最重要的一句话**：正因为 `DEFAULT_PERMISSION_CLASSES` 是全局默认，**新写的接口会自动获得鉴权与封禁约束**；视图里出现的 `@permission_classes([AllowAny])` 才是"破例"的地方（例：`accounts/views.py` 第 27 行探针、第 8 行短信接口）。

---

## §4 动手实验

### 实验 1 · 把配置读出来（不猜，直接打印）

```powershell
cd D:\pycharmproject\chat_app\chatapp
$code = @'
import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()
from django.conf import settings
print("TESTING   =", settings.TESTING)
print("CACHE     =", settings.CACHES["default"]["LOCATION"])
print("BROKER    =", settings.CELERY_BROKER_URL)
print("PERMS     =", settings.REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"])
print("JWT_ACCESS=", settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"])
print("AUTH_USER =", settings.AUTH_USER_MODEL)
'@
$code | python -
```
预期（本机实测）：`TESTING=False`、缓存 `.../0`、broker `.../1`、权限类两项、`0:30:00`、`accounts.User`。

### 实验 2 · 让慢请求告警立刻可复现

把第 249 行临时改成 `REQUEST_SLOW_MS = 0`，起服务器请求任意接口 → 服务器日志级别从 `INFO` 变成 `WARNING`（因为 `config/middleware.py` 第 27 行按阈值选级别）。改回 `500`，`git diff` 应为空。

### 实验 3 · 观察 `DEBUG` 关掉后静态文件失效

临时把第 33 行改成 `DEBUG = False`（或 `.env` 里 `DEBUG=0`）：
- `config/urls.py` 第 14–15 行的 `static(...)` 分支不再挂载 → 上传的图片 URL 返回 404；
- 未捕获异常不再返回 HTML 调试页，而是 500。
改回来，并确认 `git diff chatapp/config/settings.py` 干净。

### 实验 4 · 亲手验证 `.env` 与真实环境变量的优先级

```powershell
$env:SMS_DEV_CODE = "999999"   # 只在本终端生效
# 用实验 1 的脚本打印 settings.SMS_DEV_CODE
```
思考：为什么打印出来仍是 `123456`？（因为 `SMS_DEV_CODE` 是**硬编码**在第 240 行，没有走 `os.getenv`。）要验证优先级请改用走 `os.getenv` 的项（如 `REQUEST_SLOW_MS`）。

---

## §5 自查题

**Q1. `.env` 里为什么必须用 `BROKER_URL` 而不是 `CELERY_BROKER_URL`？**

**参考答案**：settings 第 133–135 行的注释给了确切原因：Celery 的 `broker_url` 属性实现里 `os.environ["CELERY_BROKER_URL"]` **优先于** Django 设置项。如果 `.env` 里写 `CELERY_BROKER_URL`，它会永久压过第 137–143 行的 `TESTING` 覆盖，导致**测试任务漏进开发 broker（DB1）**——测试就不再隔离。

**Q2. `TESTING` 怎么判定？它改变了哪几处行为？**

**参考答案**：第 95 行 `TESTING = sys.argv[1:2] == ["test"]`。影响两处：第 118 行 `CONN_MAX_AGE`（测试关闭持久连接以保证用例隔离）、第 137–143 行 Redis 地址（缓存 → `/15`、broker → `/14`）。实测证据见 §2 第 4 点。

**Q3. 为什么 `DB_PASSWORD` 不给默认值，而 `SECRET_KEY` 给？**

**参考答案**：这是两种不同意图。`SECRET_KEY` 的兜底是为了"本地 clone 下来就能跑"；数据库口令若给兜底，会诱导把弱口令当成"默认可用"，所以第 112–113 行明确留空并注释说明。判断一个配置该不该有兜底，看它是"便利"还是"安全边界"。

**Q4. 为什么这个项目能用 `AUTH_USER_MODEL = "accounts.User"`？如果项目已经 migrate 过再改会怎样？**

**参考答案**：自定义用户模型与 Django 内置 auth 的表结构强耦合，必须在**首次 migrate 之前**定好；本项目在 M0 建库时就设定了。已 migrate 后再改需要手工迁移历史、极复杂，属于要避免的操作。

**Q5. 全局 `DEFAULT_PERMISSION_CLASSES` 里两个类各管什么？这带来什么后果？**

**参考答案**：`IsAuthenticated` 管"必须有有效令牌"；`moderation.permissions.IsNotHeavyBanned` 管"重封禁用户全站 403"。后果是**新接口自动继承这两条**，不需要每个视图重复写；只有像短信、探针这类公开接口才用 `@permission_classes([AllowAny])` 显式破例。

**Q6. `USE_TZ=True` + `TIME_ZONE="Asia/Shanghai"` 与接口文档里的两种时间格式有什么关系？**

**参考答案**：数据库统一存 UTC；响应里 DRF 默认按 UTC 带 `Z` 渲染（分页列表的时间字段），而某些字段（如在线状态的 `last_active_at`）在代码里显式转成本地时区渲染成 `+08:00`。二者是同一绝对时刻的两种表示，见 `docs/api/conventions.md` §时间格式。

---

## §6 卡住时查哪里

| 需要 | 去处 |
|---|---|
| 配置项官方语义 | Django `settings` 参考文档（**一次只查一个键**） |
| `.env` 有哪些键 | `chatapp/.env.example`（29 行，逐行读完） |
| 限流额度的对外口径 | [../../api/conventions.md](../../api/conventions.md) §限流总览 |
| 日志相关坑 | [../../pitfalls/backend.md](../../pitfalls/backend.md) |

---

## §7 验收

1. 能说出三层配置来源与优先级；
2. 能默写出 `TESTING` 影响的两处；
3. 四个实验做完，`git diff chatapp/config/settings.py` 为空；
4. 笔记 `docs/learning/backend-notes/P02-settings.md`（**建议用"配置项 → 值从哪来 → 谁在用"三列表格**，不许整段照抄），并勾掉总纲 P02。
