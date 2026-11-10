# 批次 V 实施计划:运营数据看板

- **状态**:待实施
- **Spec 链接**:[批次 R–W 设计](../../specs/2026-11-09-batch-r-w-design.md) §4.5
- **交接来源**:[批次 U/W 交接](2026-11-10-batch-u-w-handoff.md) §2「V 批」
- **Goal**:每天自动留一份**运营数字快照**(DAU / 新注册 / 资料完善 / 滑卡 / 配对 / 消息量 / 活跃时段 / 留存),
  在 `/ops/metrics/` 一页看近 30 天趋势。看板解决的是**历史趋势**,实时指标仍归 Prometheus。
- **Architecture**:`stats.DailyMetric`(一天一行,`date` 唯一)+ `manage.py metrics_daily`(cron 每天算昨天,
  幂等 upsert)+ `/ops/metrics/`(服务端渲染,只读快照表)。**不进 `/api/v1`**,因此不碰 openapi / `docs/api/`
  / App / Web —— 本批是**纯 backend 单栈**,零跨栈契约联动。
- **Global Constraints**:一单一条栈;新增 `.py` 必须补模块与函数 docstring(`Args:`);不动版本号、不发版、不合并 PR;
  不碰 `deploy/`(AGENTS.md 明令禁止);不改既有 `/api/v1` 行为。
- **验收命令**:`scripts/verify.sh backend`

---

## 0. 现状核实(动手前查过,纠正了四处预判)

| 预判 / 交接文档的说法 | 实际 | 影响 |
|---|---|---|
| 需要新建一个 `stats` app | **错**:`chatapp/stats/` 已存在(P 批「使用报告」),但**只有 services/views,没有 `models.py`、没有 `migrations/`**,且 `apps.py` 的 docstring 明写「只读聚合,不建表」 | 本批给它加**第一张表**:`stats/models.py` + `stats/migrations/`,并同步改 `apps.py` 那句 docstring |
| 「DAU = 120 秒内有认证请求」可以直接查出来 | **错**:那是 `users.presence` 的口径,而 presence 是 Redis 单键 + **7 天 TTL 的最后活跃时间戳**,**没有「按天去重的人数」这种历史**;事后回填不出过去任何一天的 DAU | 必须**新增日活记录**(见 Task 1 §1),DAU 与留存**从上线当天起**才有数据,回填日留空 —— 这是本批唯一的新增基建 |
| 「活跃时段分布」可以从库里算 | **错**:同上,库里没有按小时的活动痕迹 | 同 §1 的小时桶一起记,顺手就有 |
| cron 放 **03:40** | **错**:03:40 已被 `refresh_shuffle_keys` 占用(见 `docs/ops/imserver.md` §12.5);03:20 备份、03:30 宝塔备份、04:00 / 04:10 / 04:20 三条媒体维护 | 本批排 **04:30**(全部维护任务之后) |
| 跨库读 `chatapp_im` | 确认:`im_message.created_at` 是 **BIGINT 秒级时间戳**(`imserver/migrations/001_init.sql`),Django 侧无任何 IM 库连接,凭据只在 imserver 的 `IM_MYSQL_DSN`(`mysql://user:pass@host:port/chatapp_im`,**按最后一个 `@` 切分**,密码里可能带 `@`) | 新增 settings `IM_MYSQL_DSN` + 一个**只读、可失败降级**的小客户端 |

其余已核实、本批直接复用的基建:

| 已有 | 位置 | 复用方式 |
|---|---|---|
| 运营台模板体系 + 鉴权装饰器 | `ops/templates/ops/base.html`、`ops/decorators.py::staff_required` | 新页面照抄 `logs.html` / `feedback.html` 的骨架 |
| 运营台路由表 | `ops/urls.py`(整页带斜杠,HTMX 局部端点不带) | 加一条 `metrics/` |
| 直连 Redis 的既有范式 | `accounts/sms_codes.py::get_redis_connection("default")` | 日活集合走它(**键不带 `chatapp:2:` 前缀**,读写同源即可) |
| 命令范式(参数 / 幂等 / dry-run / 退出码) | `users/management/commands/media_bytes_backfill.py`、`refresh_shuffle_keys.py` | 新命令照抄结构与 docstring 风格 |
| 用户注册时间 | `accounts.User.date_joined`(`AbstractUser`) | 新注册数、留存 cohort |
| 滑卡 / 配对 / 动态 | `discovery.Swipe`(`action`+`created_at`)、`discovery.Match`、`feed.Post` | 计数直接 `filter(created_at__range=…)` |
| 资料完善 | `users.Profile.status`(`COMPLETE`)+ `refresh_status()` | 见 §3 的口径(存量列,没有历史,只能按「当前值」近似) |
| 查询预算门禁 | `config/test_query_budget.py` | **只覆盖 `/api/v1`**,本批不动它;但看板页仍要一条 SQL 取完 30 行 |
| 时区 | `settings.TIME_ZONE = "Asia/Shanghai"`、`USE_TZ = True` | 「一天」= Asia/Shanghai 自然日,查询时换算成 UTC 时刻区间 |

---

## Task 1 —— V-1 指标采集与快照命令(backend,先合)

### 1. 新增日活记录:`chatapp/users/activity.py`

这是本批**唯一新增的基建**,也是唯一碰请求热路径的地方(认证路径每个请求都会走)。

- 键(用 `get_redis_connection("default")` 直连,**不要**混用 `cache.set` / `cache.get` —— 后者会套
  `chatapp:2:` 前缀与 JSON 序列化器,读写必然对不上):
  - 日集合 `activity:dau:{YYYYMMDD}`(SET,成员是 `user_id`)
  - 小时集合 `activity:dau:{YYYYMMDD}:{HH}`(SET,`HH` 两位补零)
  - 两者都 `EXPIRE ACTIVITY_TTL_SECONDS = 45 * 24 * 3600`
- 公开函数(全部带 docstring 与 `Args:`,全部**吞异常只记 warning**,与 `presence` 同口径):
  - `touch(user_id: int, at: datetime | None = None) -> None` —— 往日集合与小时集合各 `SADD` 一次;
    `at=None` 取 `timezone.localtime()`;**`at` 参数是为了测试能造历史数据,不要在生产路径上传它**。
  - `day_key(day: date) -> str` / `hour_key(day: date, hour: int) -> str`
  - `daily_users(day: date) -> set[int]` —— `SMEMBERS`;集合不存在返回空集(**不要抛异常**)
  - `daily_count(day: date) -> int | None` —— `SCARD`;集合不存在返回 `None`(区别于「有集合但是 0 人」,
    看板要能显示「无数据」而不是「0」)
  - `hourly_counts(day: date) -> list[int] | None` —— 24 个 `SCARD` 走一次 pipeline;24 个键全不存在返回 `None`
- **接线**:`users/presence.py::touch()` 末尾调 `activity.touch(user_id)`。
  理由:认证通过即刷新 presence(`accounts/authentication.py::get_user`),那是全项目**唯一**的
  「有认证请求」证据点,接在这里口径天然一致,不必再改 `authentication.py`。
- **代价与纪律**:每个认证请求多 1 次 Redis pipeline(4 条命令:SADD ×2 + EXPIRE ×2,同一条 pipeline 一个往返)。
  必须包在 `try/except` 里,失败只 `logger.warning`,**绝不能让活动记录拖累业务请求**(与 presence 同一条纪律)。
- **注意**:45 天 TTL ⇒ DAU / 活跃时段 / 留存**最多只能回看 45 天**,更早的日期没有数据。

### 2. 模型:`chatapp/stats/models.py`(新文件)

```python
class DailyMetric(models.Model):
    """一天的运营数字快照(一天一行,由 ``manage.py metrics_daily`` 写入)。"""
    date = models.DateField("日期", unique=True)          # Asia/Shanghai 自然日
    dau = models.PositiveIntegerField("日活", null=True)   # 无 Redis 记录时 None(不是 0)
    new_users = models.PositiveIntegerField("新注册", default=0)
    profiles_completed = models.PositiveIntegerField("新注册中资料已完善", default=0)
    swipes_like = models.PositiveIntegerField("喜欢", default=0)
    swipes_pass = models.PositiveIntegerField("跳过", default=0)
    matches = models.PositiveIntegerField("新增配对", default=0)
    messages = models.PositiveIntegerField("消息条数", null=True)   # 读不到 IM 库时 None
    active_hours = models.JSONField("活跃时段分布", null=True)      # 24 个整数;无数据 None
    retention_d1 = models.PositiveIntegerField("次日留存", null=True)
    retention_d7 = models.PositiveIntegerField("7 日留存", null=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)
```

- `Meta`:`ordering = ["-date"]`、`verbose_name = "每日指标"`。
- 迁移用 `makemigrations stats` 生成(`stats/migrations/0001_initial.py`,同时需要
  `stats/migrations/__init__.py`)—— **不手写**。
- `stats/apps.py` 的 docstring 从「只读聚合,不建表」改成「个人使用报告 + 每日运营指标快照」。
- **为什么用 nullable 而不是 default=0**:`dau` / `messages` / `active_hours` / 留存 有「**当天没采到**」
  与「**采到了但是 0**」两种状态,看板必须能区分(显示 `—` 而不是 `0`)。其余计数在库里一定有源,缺省 0。

### 3. 口径(写死,不许各算一套)

一天 = `Asia/Shanghai` 自然日 `[00:00, 次日 00:00)`;换算成查询用的 UTC 时刻区间用
`timezone.get_current_timezone()`(即 settings 的 `Asia/Shanghai`),**不要用 `datetime.now()` 直接切**。

| 字段 | 口径 |
|---|---|
| `dau` | `activity.daily_users(day)` 的成员数(去重人数);集合不存在 = `None` |
| `new_users` | `User.objects.filter(date_joined__gte=start, date_joined__lt=end).count()` |
| `profiles_completed` | 上述**当日新注册**的人里,`Profile.status == COMPLETE` 的人数(口径:注册当天即完善;`Profile` 没有 `completed_at`,回填日只能按**当前**状态算 —— 这是已知近似,写进文档) |
| `swipes_like` / `swipes_pass` | `Swipe.objects.filter(created_at__range, action=…)` 的条数 |
| `matches` | `Match.objects.filter(created_at__range).count()`(含事后被解除的,按事件口径) |
| `messages` | IM 库 `im_message` 当日条数(见 §4);读不到 = `None` |
| `active_hours` | `activity.hourly_counts(day)`,24 个整数;无数据 `None` |
| `retention_d1` | cohort = **当日注册**的用户 id 集合;`len(cohort ∩ activity.daily_users(day+1))`;目标日集合不存在 = `None` |
| `retention_d7` | 同上,`day+7` |
| 配对率 | **不落库**,由 `matches / swipes_like` 现算(分母 0 显示 `—`) |

**留存必须按「首日注册 cohort」算**,不要拿「当日活跃」反推 —— 两者分母不同,反推出来的数字看着像留存但没法解释。

### 4. IM 库只读客户端:`chatapp/stats/im_source.py`(新文件)

- `count_messages(day: date) -> int | None`:读 `settings.IM_MYSQL_DSN`;空 → 返回 `None` 并**只记一次 info**;
  连接/查询失败 → 返回 `None` + `logger.warning`(**绝不抛异常**,看板不能因为 IM 库挂了而整页空白)。
- DSN 解析:`mysql://user:pass@host:port/db`,**按最后一个 `@` 切分**(密码里可能有 `@`,见
  `deploy/ops/chatapp-backup.sh` 同一处理);端口缺省 3306。
- 连接用 `pymysql.connect(..., connect_timeout=5, read_timeout=10, charset="utf8mb4")`,**每次用完 `close()`**;
  只跑一条 `SELECT COUNT(*) FROM im_message WHERE created_at >= %s AND created_at < %s`
  (`created_at` 是 **epoch 秒**,`int(start.timestamp())` / `int(end.timestamp())`)。
- 只读:不写、不改 IM 库任何东西;不带 `autocommit` 副作用。
- `config/settings.py` 新增 `IM_MYSQL_DSN = os.getenv("IM_MYSQL_DSN", "")`(放在既有 `IM_*` 段附近);
  `chatapp/.env.example` 补一段注释说明格式、**该账号只需 `chatapp_im` 的 SELECT 权限**、留空 = 消息量显示「无数据」。

### 5. 服务层:`chatapp/stats/metrics.py`(新文件)

- `day_range(day) -> tuple[datetime, datetime]`:Asia/Shanghai 自然日 → 左闭右开的 aware datetime。
- `build_snapshot(day) -> dict`:按 §3 算出全部字段(不落库)。
- `save_snapshot(day) -> DailyMetric`:用 `update_or_create(date=day, defaults=…)` —— **幂等**,重跑同一天覆盖而不新增。
- `fill_retention(day, field) -> bool`:给**已存在**的那一行补 `retention_d1` / `retention_d7`
  (用 `.filter(date=day).update(...)`,行不存在就跳过并返回 `False`,**不要为了补留存凭空造行**)。
- `recent_rows(days: int = 30) -> list[DailyMetric]`:看板用,一条 SQL 取完。
- `match_rate(row) -> float | None`:分母 0 返回 `None`。

### 6. 命令:`chatapp/stats/management/commands/metrics_daily.py`(新文件)

- 参数:
  - `--date YYYY-MM-DD`:算指定日(缺省 = **昨天**,按 Asia/Shanghai);非法日期 → `CommandError`(退出码 1)
  - `--backfill N`:以 `--date`(缺省昨天)为**终点**,往前共 N 天(含端点);`N <= 0` → `CommandError`
  - `--dry-run`:只打印不写库
- 主流程:
  1. 对窗口内每一天 `build_snapshot` → `save_snapshot`(dry-run 则只打印);
  2. 窗口内每一天再试 `fill_retention(day, "retention_d1")` 与 `fill_retention(day, "retention_d7")`
     (目标日的数据不存在就跳过);
  3. **额外**给 `--date` 前 1 天补 `retention_d1`、前 7 天补 `retention_d7` —— 否则「只跑昨天」时,
     昨天的 D+1 留存要等到后天那次运行才会补上,而那次运行的窗口里没有昨天;
  4. 每天打印一行:`2026-11-09 dau=12 new=3 done=1 like=40 pass=25 match=8 msg=137 d1=- d7=-`,
     缺失值打印 `-`;末尾打印一行窗口汇总(天数 / 有数据的天数)。
- 退出码:`0` 成功(含「IM 库读不到,消息量留空」);`1` 参数非法或写库异常。
- 命令 docstring 里写清 cron 用法(见 §7)与「DAU 只有上线后才有」。

### 7. 文档:`docs/ops/runbook.md` 新增 §9「每日运营指标快照」

- 口径表(照抄 §3,含「`profiles_completed` 按当前状态近似」「DAU / 留存只有上线后 45 天内可回看」两条限制);
- 首次上线步骤:`python manage.py migrate`(建 `stats_dailymetric`)→ 手动跑一次
  `python manage.py metrics_daily --backfill 30`(回填日 `dau` / 留存会是空,这是预期的);
- **cron 04:30**(宝塔计划任务,与 03:20 备份 / 03:40 轮换 / 04:00–04:20 媒体维护错开):
  ```
  30 4 * * * cd /www/wwwroot/chatapp/chatapp && <解释器> manage.py metrics_daily >> /www/wwwlogs/chatapp-metrics.log 2>&1
  ```
  `<解释器>` 以服务器上既有维护任务实际用的那个为准(与本机 `crontab` 里其他 `manage.py` 任务保持一致);
- 排障三行:命令输出里 `msg=-` → 查 `IM_MYSQL_DSN`;`dau=-` → 查 Redis `activity:dau:*` 是否存在;
  `/ops/metrics/` 全空 → 先手动跑一次命令。
- 生产 `.env` 要新增 `IM_MYSQL_DSN`(取自 imserver 的 env,**不入库**)—— 写进「留给人验」。

### 8. 测试(必须真的断言)

`chatapp/stats/tests.py`(已有文件,追加)与 `chatapp/users/tests.py`(追加 activity 用例):

1. **activity 读写**:`touch(9, at=<某天 10:30>)` → `daily_count(day) == 1`、`hourly_counts(day)[10] == 1`;
   同一人同一天 `touch` 两次仍是 1(去重);`daily_count(空的一天) is None`。
2. **activity 吞异常**:`patch` 掉连接让它抛异常 → `touch()` 不抛(与 presence 同款断言)。
3. **快照数字**:造已知数据(2 个新注册、1 个 complete、3 like / 2 pass、1 个 match、若干 post),
   跑 `metrics_daily --date <昨天>`,断言每个字段都对得上。
4. **`messages` 降级**:DSN 为空 → `messages is None` 且命令**退出码 0**;
   `patch("stats.im_source.count_messages", return_value=42)` → `messages == 42`。
5. **幂等**:同一天跑两次 → `DailyMetric.objects.count() == 1`,第二次覆盖(改数据后重跑,值跟着变)。
6. **backfill**:`--backfill 3` → 3 行,日期连续且终点是昨天。
7. **留存**:造 D 日注册的 cohort + `touch` D+1 / D+7 的活跃集合 → 跑 `--date D`,
   断言 `retention_d1` / `retention_d7` 是 cohort 与当日活跃的**交集人数**(故意让 cohort 里有 1 人 D+1 没活跃,
   否则这条测试抓不住「按活跃数反推」的实现);目标日无数据时字段是 `None` 而不是 0。
8. **时区边界**:把事件造在「Asia/Shanghai 当日 23:59:59」与「次日 00:00:01」,断言只算进前一天 ——
   这条专抓「用 UTC 日切」的实现。
9. 门禁:`CommentCoverageTests` / 全量 `manage.py test`。

### 验收口径

1. `scripts/verify.sh backend` 全绿(末尾输出贴进 PR 正文)。
2. 上面 9 组测试全过,且**改回错误实现时会红**(时区、留存交集、幂等、降级四条尤其)。
3. `python manage.py metrics_daily --backfill 3 --dry-run` 在本机能打印 3 行(不需要真 IM 库)。
4. `git diff` 里能看到 `stats/migrations/0001_initial.py`,且 `docs/ops/runbook.md` 有 §9。

### 禁止事项

不改既有 `/api/v1` 任何接口与行为(本单**不碰** `docs/api/` 与 `openapi.yml`,它们不该出现在 diff 里);
不改 `users.presence` 的既有语义(只在 `touch()` 末尾加一行调用);不动 `config/test_query_budget.py`;
不碰 `deploy/`(cron 只写进 `docs/ops/runbook.md`,由人在服务器上配);不引入 Celery beat;
不在请求路径上做任何 IM 库查询;不手改迁移文件;不动版本号。

### 不在本期范围

Grafana 新面板、漏斗归因、用户分群、按端(App/Web)拆分指标、把看板做成 `/api/v1` 接口、告警(阈值告警仍归 Prometheus)。

---

## Task 2 —— V-2 `/ops/metrics/` 看板页(backend,依赖 V-1 已合并)

### 改什么

1. `chatapp/ops/views.py`:新增 `metrics(request)` 视图,`@staff_required`;
   `stats.metrics.recent_rows(30)` **一条 SQL** 取 30 行,在 Python 里算:
   - 每行的 `match_rate`(分母 0 → `None`,模板显示 `—`);
   - 近 7 日汇总(7 日新增注册合计 / 7 日均 DAU / 7 日配对率 = Σmatches / Σlike);
   - 「最后一天有数据的行」的 `active_hours`,给活跃时段小节用。
   上下文里带 `rows` / `summary` / `latest` / `today`,**不要在模板里做除法**。
2. `chatapp/ops/urls.py`:加 `path("metrics/", views.metrics, name="metrics")`。
3. `chatapp/ops/templates/ops/base.html`:导航加一项「运营看板」(图标用既有 `stroke` 风格,
   放在「日志」**前面**),`active` 判定与既有各项同款。
4. `chatapp/ops/templates/ops/metrics.html`(新文件):照 `logs.html` 的骨架
   - 顶部 4 个数字卡:昨日 DAU / 昨日新注册 / 近 7 日配对率 / 近 7 日消息量;
   - 「近 30 天趋势」表:日期 / DAU / 新注册 / 完善 / 喜欢 / 跳过 / 配对 / 配对率 / 消息 / 次日留存 / 7 日留存;
     缺失值一律渲染 `—`(**不要渲染 0**),`<caption>` 或表下一行小字写明「`—` = 当日未采集到」;
   - 「活跃时段」小节:最近一天有数据的那行的 24 个小时,用**纯 CSS 横条**(`width: {{ pct }}%`)表示,
     不引任何 JS 库(运营台是 HTMX + 手写 CSS 的风格);
   - 空表(一天都没跑过)时给一句「还没有数据:先在服务器上跑 `python manage.py metrics_daily --backfill 30`」。
5. `chatapp/ops/tests.py` 追加:
   - staff 登录 → `GET /ops/metrics/` 200,页面里出现造出来的那几行数字;
   - 非 staff → 403;未登录 → 302 到登录页(照既有用例写法);
   - 空表 → 200 且出现「还没有数据」提示,不抛异常;
   - 缺失值渲染成 `—` 而不是 `0`(断言 `dau=None` 那行不含 `>0<`);
   - **查询数**:`assertNumQueries` 钉住「30 行一条 SQL」级别(把门禁写进用例,别只靠人看)。
6. `docs/ops/runbook.md` §9 补一段「看板怎么用」(`/ops/metrics/`,需要 staff + TOTP)。

### 验收口径

1. `scripts/verify.sh backend` 全绿(末尾输出贴进 PR 正文)。
2. `python manage.py metrics_daily --backfill 5` 后,本地 superuser 打开 `/ops/metrics/` 能看到 5 行与四个数字卡;
   非 staff 访问 403。
3. 缺数据的行显示 `—`;空表有提示文案,不 500。

### 禁止事项

不写任何数据(本页只读);不在页面里查 IM 库或算实时指标(只读 `DailyMetric` 快照表);
不改 `/api/v1`;不引前端依赖/新 CSS 框架;不动 `ops` 既有页面行为;不动版本号。

### 不在本期范围

导出 CSV、按周/月聚合、图表库、按端拆分、告警推送。

---

## 执行记录

(合并后补:每单 PR / 合并 SHA / 关键交付 / 与计划的偏差 / 踩到的坑 / 验收结论 / 遗留)
