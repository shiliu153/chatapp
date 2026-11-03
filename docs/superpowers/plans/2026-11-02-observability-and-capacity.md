# 可观测性与容量工程整改方案（2026-11-02）

> 触发：面试叙事缺口——「有多少人用 / 扛得住多少量 / 你怎么知道它没坏」。
> 结论先行：**三项里有两项其实已有硬证据**（§1），缺的不是数字，而是「可复现、可持续、可展示」；
> 第三项（可观测性）确实是零，且 `docs/ops/stress-test-2026-11-01.md` 自己压出来的 4 个缺陷还没修。
> 执行方式：`executing-plans` 内联逐批完成，不派子 agent；每批全绿再进下一批。

## 0. 现状盘点（有据可查，不凭印象）

| 面试问题 | 现有证据 | 缺口 |
|---|---|---|
| 有多少人用 | 封闭测试 9 用户 / 3 配对 / 56 条消息；灰度名单 7,8 → all | 没有产品级指标（DAU/留存/消息量），也没有采集管道；不能也不该编造真实用户数 |
| 扛得住多少量 | HTTP 稳定 **550–600 rps**（并发 20→400，p99 101ms→995ms，0 个 5xx）；WS **1000 连接 / 2000 条消息 0 失败**；IM 单机吞吐 **215 msg/s**，2C2G 天花板 200–250 msg/s | 一次性报告，脚本在 `docs/ops/stress/` 但无基线、无回归门禁、无场景矩阵；数据量恒为 9 用户，未验证「数据涨 4 个数量级后」的表现 |
| 怎么知道它没坏 | `health`/`readyz` 探针（每分钟、连续 2 轮才告警）；结构化程度仅 `request_id` 文本日志 | **无 metrics、无看板、无推送告警、无 tracing、无错误聚合**；P2-5 明确写了「告警只落日志，没人看得到」 |
| 后端深度 | imserver：间隙锁死锁修复、prepared statement 缓存、unread 合并、连接池 ping、进程内画像缓存 | Django 侧几乎纯 CRUD：`cache.*` 全仓仅 5 处（短信限流/运营登录锁/refresh 宽限/presence），**无候选池缓存、无削峰、无并发一致性测试**，`assertNumQueries` 为 **0 处** |

## 1. 判断：真正的缺口是三条

1. **数字没有变成能力**。压测是一次性的，换台机器、改个接口就复现不了；面试官追问「再压一次」时拿不出 5 分钟出结果的东西。
2. **没有「持续知道」的手段**。现在靠人肉 `curl readyz` + 看日志，MTTR 111s（全栈打崩那次），且 90 秒宕机都没触发告警。
3. **Django 侧没有可讲的后端深度**。深度全在 C++ imserver，而面试官问的往往是业务后端（缓存一致性、削峰、并发）。

所以整改不是「再做一次压测」，而是：**把压测报告升级成容量工程，把探针升级成可观测体系，把 CRUD 升级成有落点的三个深度改造**。

## 2. 方案总览：四轨

| 轨 | 回答的问题 | 产出物（可展示） | 硬指标 |
|---|---|---|---|
| A 可观测 | 怎么知道它没坏 | Prometheus + Grafana 四块板 + 企业微信告警 + runbook | 故障发现 ≤ 60s；MTTR ≤ 30s |
| B 容量工程 | 扛得住多少量 | `perf/` 可复现脚本 + `baseline.json` + `docs/ops/capacity.md` | 任意机器 5 分钟复现；发版回归 >20% 报警 |
| C 后端深度 | 业务后端会什么 | 缓存一致性层 + 削峰链路 + 并发测试 | 缓存命中 ≥90%、DB QPS −60%、突发 3× 时 p99 不劣化 |
| D 叙事 | 怎么讲 | 每项「before/after + 一张图 + 一段复盘」 | 简历 3 条、面试 3 个追问有答案 |

---

## A. 可观测性（P0，先做最小闭环）

### A.1 指标层

- [x] `chatapp/config/metrics.py`：`prometheus_client` 自建 `CollectorRegistry`；
      `http_requests_total{method,route,status}`、`http_request_duration_seconds`（直方图，5ms–5s）、
      `http_inflight`。
- [x] `chatapp/config/middleware.py`：新增 `MetricsMiddleware`，只按 **路由模板** 打标签
      （`request.resolver_match.route`，实测为 `api/v1/users/<int:user_id>`，避免基数爆炸）；
      排除 `/metrics`；异常上抛前记一次 500。
- [x] `chatapp/config/urls.py`：`/metrics` 挂在根路由（不在 `/api/v1` 下，不纳入接口文档门禁）；
      配 `METRICS_TOKEN` 时校验 `X-Metrics-Token` / `Authorization: Bearer`，
      未配令牌时只对回环开放、非回环一律 404。
- [ ] 业务指标（低基数，按需加）：登录成功数、滑卡数、配对成功数、IM 发消息数、Celery 任务失败数。
- [x] `imserver/src/util/metrics.{h,cpp}` + `/metrics`（回环限定）：`im_connections`、
      `im_sends_total{result}`、`im_deadlock_retries_total`、`im_db_pool_wait_seconds` /
      `im_db_pool_waits_total`。热路径只多一条 relaxed `fetch_add`。
- [ ] Celery：`celery-exporter`（或手写 Redis `llen` Gauge）。
- [ ] `mysqld_exporter` + `redis_exporter`（容器）。

### A.2 展示与告警

- [x] `deploy/observability/docker-compose.yml`：prometheus + grafana + alertmanager +
      alert-relay + node_exporter，全部 host 网络、抓 127.0.0.1，内存 `mem_limit` 合计约 350MB。
- [x] 看板 `deploy/observability/grafana/dashboards/chatapp-overview.json`：
      概览（QPS / 5xx / p99 / inflight）、各路由 p99、IM 连接与发送、死锁重试与池等待、主机 CPU/内存/磁盘。
- [x] 告警规则（`alerts.yml`，9 条）→ Alertmanager → `alert_relay.py`（40 行标准库代码，
      把 Alertmanager JSON 转成企业微信格式）：5xx 比例、p99、inflight 饱和、IM 掉线、
      死锁重试、发送失败率、池等待、磁盘、内存。
- [ ] 探针改 30s 一次（现每分钟、连续 2 轮才 ALERT，实测漏报 90s 宕机）——**服务器侧，待上线**。
- [x] **MySQL 系统级守护**（stress 文档 P0-2）：`deploy/ops/mysql-watchdog.sh` + systemd drop-in；
      上线后 MTTR 目标 ≤30s。
- [x] `docs/ops/runbook.md`：告警 → 看哪块板 → 处置动作；`docs/ops/observability.md`：部署与指标口径。

### A.3 日志与错误聚合

- [x] 日志切 JSON（自写 40 行 formatter，不引依赖）：`config/logging.py`，`LOG_FORMAT=json` 生效；
      字段白名单 `ts/level/logger/message/request_id` + `user_id/route/status/duration_ms/sql_count`，
      白名单外的 `extra`（可能是手机号）不会泄漏，异常进 `exc` 字段。
- [x] 请求日志结构化：`RequestIdMiddleware` 通过 `extra` 带 `status/route/duration_ms`；
      慢请求（`REQUEST_SLOW_MS`）自动升 WARNING；`sql_count` 仅在 `DEBUG=1` 采集。
- [x] 错误聚合：Loki + Promtail 作为 compose 的 `logs` profile（默认不启动，约 176MB），
      Grafana 加 Loki 数据源；LogQL 可按 `request_id` / `status>=500` / `duration_ms>500` 查。
      配置经 `loki --verify-config`、`promtail --check-syntax` 校验通过。
- [x] 测试 4 条（`config.tests.JsonLogTests`）：字段齐全、未知 extra 不泄漏、异常序列化、
      请求日志带结构化字段。

**验收**：`kill -9` gunicorn 后 60s 内企业微信收到告警；Grafana 能看到该时段 5xx 曲线与 p99；
`/metrics` 在公网 404、回环 200。

---

## B. 容量工程（P0 脚本入库，P1 场景矩阵）

### B.1 可复现

- [x] 新入口 `perf/run.py`：`--scenario api_read|api_health|ws_burst|ws_steady`，
      统一 CLI；WS 场景委托 `imserver/scripts/bench_ws.py` 并合并结果。
- [x] 统一 JSON：`scenario / started_at / machine(cpu,mem) / params / result(rps,p50,p95,p99,error_rate,codes) / resources(load1_peak,mem_used_mb_peak)`。
- [x] `perf/report.py` 生成 Markdown 表；`--baseline perf/baseline.json` 逐点对比，
      RPS −20% / p99 +20% / 错误率 +1pp 判定回归，`--fail-on-regression` 退出码 1。
- [x] `perf/baseline.json` 写入 2C2G 实测基线（HTTP 5 个并发档 + WS 3 条）。
- [x] `perf/README.md` 写清「压测器不能和被压服务同机」——stress 文档已踩过（公网侧 conc=400 时 RPS 反降到 72）。
- [x] 冒烟验证：本机 dev server 10 并发 5 秒 → 303 rps / 0 错误 / p99 83.8ms；
      伪造一条 rps=300 的结果对基线 → 正确判出 −50.7% 与 p99 +78.2%，退出码 1。

### B.2 场景矩阵（进行中）

> 写场景的前提是登录态，而**写接口的限流都按用户计**（滑卡 300/小时、发动态 20/天）：
> 单账号跑几秒就撞 429，压出来的是限额不是容量。所以先补齐「多账号令牌」这条链路，
> 而不是只给 `run.py` 加一个 `--header`。

- [x] `perf/run.py` 请求层补齐：`--method`、`--header`（可重复）、`--headers-file`
      （一行一套头、连接轮转，一个账号一个令牌）、`--body`（`@文件` 读入、`{i}` 替换为全局自增序号）、
      `--i-start`，以及新场景 `api_write`。
- [x] 令牌脱敏：结果 JSON 只记头名与头集套数，**头的值不落盘**（结果文件会进 git）；
      `perf/test_run.py` 有 24 条自测（含真实 TCP 回显服务器验证头/体确实发出），CI 会跑。
- [x] 多账号令牌来源 `manage.py perf_tokens`：用 `SessionRefreshToken.for_user` 库内签发
      （走短信登录会被 `sms_verify` 的 IP 限流卡住，且每登一次 `session_version += 1` 互相顶号）；
      默认只签 `seed_scale_users` 的 199 号段、排除 staff/superuser、`DEBUG=0` 需显式 `--allow-production`。
- [x] 写路径冒烟（本机 dev server，非容量数字）：`POST /discovery/swipe` 2 连接 5 秒
      **395 次全 200 / 0 错误 / p99 42ms**；`{i}` 自增体在真实链路上确认（DB 落 6 条不同目标的 Swipe）。
- [x] 顺带实测到「单账号压不出写容量」的具体形状：`POST /posts` 单账号 85 次 = **20 × 201 后 65 × 429**
      （`post_create` 20/天额度）；DB 落 20 条正文互不相同的动态，证明 `{i}` 在表单体里也生效。
- [x] **2C2G 写路径基线**（2026-11-03 实测，报告 `docs/ops/write-baseline-2026-11-03.md`）：
      `POST /discovery/swipe` 20/50/100/200 并发 = **33.4 / 35.8 / 38.5 / 39.2 rps**，
      p50 552→4922ms，全程 **0 个 5xx/429**；`perf/baseline.json` 已补 4 个 `api_write` 点。
      同批量到三个事实：① 加并发只涨延迟不涨吞吐（天花板是整机 CPU/内存，不是 8 个线程）；
      ② MySQL 不是瓶颈（每次 swipe ≈10 条查询 / 读 4.7 行，无全表扫）；
      ③ 内存压力（swap 在用、`si≈1MB/s`）与 4–10 秒的 p99 尖刺同源。
- [ ] **重跑读基线**（本次顺带发现：同接口同并发 `app_config` 从 608 掉到 **410 rps**，
      观测栈上线后旧读点偏乐观 ~1/3；不重跑则 `report.py` 的「RPS −20%」会误报）。
- [ ] 定位这 1/3 的归属（逐容器停掉复测；候选：观测栈合计 ~344MB 上限、mysqld RSS 510MB、swap）。
- [ ] `GET /discovery/candidates` p99 **9.5s**（20 并发）单独查——发现页主路径，比写路径更影响体感。
- [ ] 读多：`GET /discovery/candidates`、`/matches`、`/posts`（feed）、`/users/{id}`。
- [ ] 写：`POST /discovery/swipe`、`POST /posts` 已可压；`POST /im/images` 未压
      （multipart 文件体，`--body` 目前只支持文本体）。
- [ ] 混合 70 读 / 30 写，跑 30 分钟看内存曲线（补 stress 文档「未测：>1h 稳定性」）。
- [ ] WS：`bench_ws.py` 已有，补「重连风暴」场景（imserver 重启后 1000 客户端同时重连）。
- [ ] 突发：0→1000 并发 in 10s，看是否触发限流/排队而非 5xx。

### B.3 规模（替代「多少人用」的诚实口径）

- [x] `seed_scale_users` 管理命令：批量造账号/资料/照片/动态，幂等（`ignore_conflicts`）、
      `--clean` 只删 199 号段、`--dry-run`。实测 2 万用户 + 10 万动态 **12.1 秒**。
- [x] `scale_probe` 管理命令：跑线上同款查询，输出各 offset 的中位耗时 + MySQL 执行计划。
- [x] 规模上重跑并定位问题：**广场列表 10.5 万条时单请求 3.35 秒**——聚合在 LIMIT 之前，
      全表分组；加 `(created_at,id)` 索引后仍全扫，因为 `exclude(author__profile__status=...)`
      生成的 LEFT JOIN 让优化器放弃索引。
- [x] 修复：两段式分页（先取当页 id 再聚合 10 条）+ 复合索引 + 改 NOT IN 子查询。
      结果 **3354ms → 77ms（offset 0）/ 3521ms → 163ms（offset 50000）**。
- [x] 报告 `docs/ops/scale-report.md`：口径、造数、EXPLAIN 前后、剩余瓶颈（COUNT 45ms、OFFSET 跳读 106ms）。
- [x] 行为不变的回归测试 `feed/test_pagination.py`（顺序、总数、重封禁排除、分页链接）。
- [ ] keyset 分页（`?before=`）替代 offset：深翻页从 106ms 降到与页深无关，
      但要改 App/Web/接口文档三端契约，单独立项。
- [x] 报告口径明确写「**合成数据 + 合成请求模型**，不代表真实 DAU」——比编 DAU 可信。

**验收**：`docs/ops/capacity.md` 一张表覆盖「机器规格 / 场景 / RPS / p99 / 错误率 / 数据量」，任何人照 README 能复现。

---

## C. 后端深度（P1，三个落点，每个都要 before/after）

### C.1 缓存一致性（候选池 + 资料卡）

- [x] `chatapp/config/cache_utils.py`：Cache-Aside + 三防（空值哨兵 / `SETNX` 单飞 / TTL ±10% 抖动）+ fail-open。
- [x] `chatapp/discovery/services.py::candidate_pool_ids`：池子查询缓存，键为
      `disc:cand:{uid}:u{用户版本}:g{全局版本}:p{池大小}`；TTL 默认 30s（`CANDIDATE_CACHE_TTL`）。
- [x] **失效用版本号而不是延迟双删**：写路径 `INCR` 版本，旧键立即不可达；
      `discovery/cache_keys.py` 提供两级版本（用户级 / 全局级），避免 `moderation`↔`discovery` 循环依赖。
- [x] 写路径接入：滑卡（自己 + 配对成功时的对方）、改偏好、改资料、上传/删除照片、
      ops 照片审核、封禁/解封。
- [x] 一致性测试 `discovery/test_cache_consistency.py`（13 条）：重复读只查一次库、
      滑卡后目标消失、改偏好后重查、全局版本失效、空池缓存、Redis 故障降级 200、
      哨兵不外泄、50 线程 × 20 次 bump 不丢计数。
- [x] 指标：`cache_hits_total` / `cache_misses_total` / `cache_errors_total{name}` 已进 `/metrics`。
- [ ] **DB QPS 下降比例**：需在 2C2G 上跑 `perf/run.py` 对比开关缓存的两次结果（B 轨重跑基线时补）。

### C.2 削峰（滑动 → 匹配 → 副作用）

- [x] 队列分级：`critical`（封禁/踢人/聊天权限）、`default`、`notify`（配对/评论/举报）、
      `bulk`（资料同步/导入），见 `CELERY_TASK_ROUTES`。**critical 不限速**——封禁不能被通知堵住。
- [x] `notify` 类任务 `rate_limit=IM_NOTICE_RATE_PER_SEC`（默认 50/s，0=关闭），
      限的是「突发灌入 imserver」而不是「用户写操作」。
- [x] 指标 `celery_queue_depth{queue}`（抓取时从 broker 读）+ 告警 `CeleryQueueBacklog`。
- [x] 实测（`imserver/scripts/bench_notice_burst.py`，500 条同一批通知）：
      不限速 p50 **227.9ms** / p99 271ms；限速 50/s p50 **24.1ms** / p99 178.6ms；
      两者都 0 失败。1500 条（3×）不限速 p99 310.7ms。
      结论：**不是稳定性问题，是延迟问题**——限速把 p50 压了 9 倍，代价是总耗时 5.8s→11s。
- [x] 文档 `docs/ops/peak-shaving.md`：机制、部署命令（两个 worker 分队列）、验证方法、局限。
- [ ] 全局精确限速（跨 worker 的 Redis 令牌桶）：当前规模不值得，`rate_limit` 是每进程一份。
- [ ] 队列满拒绝入队：通知类丢不起，延迟入队比丢弃安全；用户写接口的背压已有 429。

### C.3 并发正确性与查询质量

- [x] 并发幂等测试 `config/test_concurrency.py`（`TransactionTestCase` + 6 线程）：
      同时点赞只留一行、只有一次 201；同时滑同一个人只留一条 `Swipe`、一个 `Match`，
      且所有请求 `matched` 一致、无 5xx。
- [x] **没有「计数器列」可改**：赞数/评数是查询时 `COUNT(DISTINCT)` 注解，不是冗余列，
      所以不存在「并发自增丢更新」的问题——计划里那条 `F()` 改造不适用，已据实调整。
- [x] `assertNumQueries` 门禁（此前全仓 0 处）：`config/test_query_budget.py` 给候选池/
      配对列表/广场列表设固定预算，并加「limit 5 → 10 时 SQL 条数必须不变」的 N+1 守卫。
- [x] 顺手修两处重复查询：`get_profile` 做**请求内记忆**（候选冷请求 19→16、热请求 8→7）；
      `page_visible_posts` 复用同一个 `visible_base`，不再重复执行 `blocked_user_ids`（广场 15→13）。
- [x] 连接池已是健康配置：`CONN_MAX_AGE=60` + `CONN_HEALTH_CHECKS=True`（复用前 `SELECT 1`），
      与 imserver 踩过的 `wait_timeout` 坑同源，无需改动。

---

## D. 叙事（贯穿，不单独占工期）

- [x] 每个改造产出三件套：**before/after 数字 + 证据链接 + 一段复盘**——汇总在
      [capacity-and-reliability.md](../../ops/capacity-and-reliability.md)。
- [x] 简历口径示例（4 条，全部带数字与限定条件）：
      「2C2G 单机支撑 600 rps / 1000 条 WS 长连接，修复冷启动建会话死锁（失败率 82% → 0）」；
      「Prometheus + Grafana + 10 条告警，故障发现降到 60 秒内」；
      「广场列表 10 万条数据 3354ms → 77ms」；「配对通知突发 p50 228ms → 24ms」。
- [x] 面试追问预案（6 问）：为什么不上 K8s/微服务、为什么不分库分表、缓存一致性怎么保证、
      限速是否全局、数字能否复现、怎么知道线上没坏。
- [x] **主动交代边界**：没有真实 DAU（封闭测试）、观测栈待上线、看门狗待安装、
      keyset 分页未做、图片/语音无机器审核。

---

## 3. 排期与优先级

| 阶段 | 内容 | 工期 | 完成标志 |
|---|---|---|---|
| P0-1 | 修 stress 文档 4 个坑（P0-1 死锁 / P0-2 MySQL 守护 / P1-3 启动重试 / P2-4 JSON 500） | 2–3 天 | 冷会话 500 并发 0 失败；双杀 MySQL 自动恢复；DB 宕机返回 JSON |
| P0-2 | A.1 + A.2 最小闭环（/metrics、4 条告警、企业微信、MySQL 看门狗） | 3–4 天 | 故障 60s 内告警；看板可查 |
| P0-3 | B.1 脚本入库 + baseline | 2 天 | 任意机器 5 分钟复现 |
| P1-1 | C.1 缓存一致性 + 指标 | 4–5 天 | 命中率 ≥90%、DB QPS −60%、一致性测试绿 |
| P1-2 | B.3 规模造数 + 报告 | 3 天 | 10 万用户下 p99 表 |
| P1-3 | C.2 削峰 | 4–5 天 | 3× 突发 p99 不劣化 |
| P2 | C.3 并发/查询、Loki、CI 性能门禁、tracing | 按余力 | — |

> 若只有一周：P0-1 + P0-2 + B.1。这三件已经能把「怎么知道它没坏」和「扛多少量」答完整，
> 且 P0-1 的四个坑本身就是最好的面试素材（「我自己压出来的死锁，根因是 RR 间隙锁」）。

## 4. 验收口径（全部可量化，不接受「感觉快了」）

- 可观测：故障注入 → 告警到达 ≤ 60s；MTTR ≤ 30s；`/metrics` 公网不可达。
- 容量：同一脚本、同一规格，RPS 波动 ≤10%；p99 数字可复现。
- 深度：缓存命中 ≥90%；DB QPS 降幅 ≥50%；3× 突发错误率 <0.1%；并发测试 0 丢失更新。
- 工程纪律：后端全量测试绿 + `flutter analyze` 零告警 + `vue-tsc`/eslint 零告警；新增 `.py` 补 docstring（`CommentCoverageTests`）；接口变化同步 `docs/api/`。

## 5. 明确不做

- 不上 K8s / 微服务拆分（2C2G 无收益，面试追问会被打穿）。
- 不做分库分表（10 万量级用不上，先索引 + cursor）。
- 不编造真实 DAU/留存；只用「合成规模 + 合成请求模型」并明确标注。
- 不为刷 QPS 数字改业务语义（如去掉鉴权、放宽限流）。

## 6. 风险

- 2C2G 上 Prometheus + Grafana + Loki 可能挤占内存 → 先只上 Prometheus + Grafana（≤250MB），Loki 放 P2。
- 缓存引入一致性 bug → C.1 的并发一致性测试必须先于缓存上线（TDD：先写测试再改实现）。
- 削峰引入「滑动成功但匹配延迟」→ 匹配判定保持同步，只有副作用异步，语义不变。
- 规模造数污染开发库 → `seed_scale_users` 只写独立前缀账号（`u9xxxxxx`）并提供 `--clean`。

---

## 7. 执行记录

### P0-1 冷启动并发建会话死锁（2026-11-02 完成）

- [x] `imserver/src/store/conversation_repo.cpp::lock_pair`：`INSERT ... ON DUPLICATE KEY
      UPDATE id=LAST_INSERT_ID(id)` 提到事务最前面，随后按主键 `SELECT ... FOR UPDATE`。
      不再对「不存在的行」加间隙锁。
- [x] `imserver/src/service/message_service.cpp`：死锁重试 3 → 8 次，退避改为
      `2*(n+1) + 线程本地随机抖动`（固定退避会让撞在一起的线程同时醒来再撞一次）。
- [x] 回归测试 `imserver/tests/store_test.cpp::ColdStartConversationCreationDoesNotDeadlock`
      （16 线程 × 20 个全新配对）。
      **反向验证**：旧实现跑同一用例 **24–29/320 失败**；新实现 **0 失败**。
- [x] 端到端验收 `imserver/scripts/bench_cold_start.py`（造 500 账号 + 环形配对 →
      起 imserver → 500 连接各发 1 条 → 断言 0 失败 → 清理）：
      `connected=500, ack_total=500, send_fail=0, errors_total=0`，**PASS**。
- [x] 全量回归：imserver unit 40 + db 19 = **59/59 绿**；后端 `manage.py test` **643/643 绿**。
- [x] 顺带修一个**既有偶发红**：`im.tests.ImTokenTests.test_reject_tampered` 原来改签名的
      最后一个 base64 字符，而 32 字节签名编码后末字符只有 2 位有效 + 4 位填充，改低位
      可能解出同样的字节 → 验签仍通过。改为改 payload 段，确定性失败。

### P1-3 DB 未就绪时 crash loop（2026-11-02 完成）

- [x] `MysqlPool` 构造新增 `connect_wait_ms`：窗口内每 2 秒重试，窗口内 DB 恢复即正常启动；
      窗口耗尽才抛（此时容器重启退避也已过去，不会叠加等待）。
- [x] 新配置 `IM_DB_CONNECT_WAIT_MS`（默认 60000）；测试用默认 0 = 首次失败立即抛，保持原语义。
- [x] `main.cpp` 传入 `cfg.db_connect_wait_ms`。

### P2-4 DB 故障返回 HTML 500（2026-11-02 完成）

- [x] `config/exceptions.py::api_exception_handler`：未预期异常转 500 JSON 并
      `logger.exception` 保留堆栈（只换响应格式，不吞故障）。
- [x] `config/urls.py::handler500` → `server_error`：非 DRF 路径兜底，`/api/`、`/ops/`
      返回 JSON，其余保持纯文本。
- [x] 测试 3 条（`config.tests.UnhandledExceptionTests`）：DRF 500 JSON、API 前缀 JSON、
      非接口路径纯文本。

### P0-2 MySQL 无系统级守护（已上线 2026-11-03）

- [x] `deploy/ops/mysql-watchdog.sh`：每分钟探活，失败按 systemd/init.d 顺序拉起，
      `flock` 防重入、失败只告警一次、恢复补通知。
- [x] `deploy/ops/mysql-restart-always.conf`：有真 systemd unit 时的 `Restart=always` drop-in。
- [x] `docs/ops/runbook.md`：安装步骤、验证方法、故障处置顺序与告警对照表。
- [x] **上线执行**：`/www/server/ops/mysql-watchdog.sh` + `/etc/cron.d/mysql-watchdog`；
      探活用 `/root/.my.im.cnf`（从 `.env` 的 DB_USER/DB_PASSWORD 生成），
      `MYSQL_START_CMD=/etc/init.d/mysqld start`；手动执行退出码 0。
- [ ] **双杀演练**：会短暂中断生产 DB，留待低峰期按 runbook §2.2 执行。

---

## 8. 上线记录（2026-11-03）

| 步骤 | 结果 |
|---|---|
| 代码 | 服务器 `master` 快进到 `a6263c6`（含 8a7ef1a 的整改提交） |
| 依赖 | venv 安装 `prometheus-client==0.21.1` |
| 迁移 | `feed.0005_post_feed_order_index` 已应用 |
| 环境变量 | `LOG_FORMAT=json`、`METRICS_TOKEN=<48 hex>`；`LOG_FILE` 原有 |
| 进程 | gunicorn / celery 重启，`/api/v1/health` = 200 |
| 指标 | 本机 `/metrics` 带令牌 200、无令牌 403；公网 `https://…/metrics` = **404** |
| 观测栈 | Prometheus / Grafana / Alertmanager / relay / node_exporter 全部 Up；**api / im / node 三个 target 全 up** |
| 看板 | `chatapp 概览` 已由 provisioning 加载（Grafana 需 `chmod -R a+rX`，否则读不到目录） |
| 日志 | `app.log` 输出单行 JSON，带 `route/status/duration_ms/request_id` |
| 告警链路 | relay 收到合成告警并正确格式化；**企业微信 webhook 未配置**（只落日志） |
| imserver | 新镜像 `imserver:8a7ef1a`（P0-1 死锁修复 + `/metrics`）已上线，`readyz=200`、`/metrics=200` |
| MySQL 看门狗 | cron 每分钟，手动执行退出码 0；双杀演练未做 |
| 资源 | 内存 used 1223MB / available 647MB；观测栈实际占用 ≈135MB（Prometheus 31 / Grafana 63 / 其余 40） |

上线时踩到并已修好的三个坑：`/metrics` 被 301 到 https（`SECURE_REDIRECT_EXEMPT`）、
Prometheus 容器读令牌权限（`chown 65534` + `640`）、Grafana 读不到 provisioning（`a+rX`）。

**待办**：企业微信机器人地址（配到 `WECOM_WEBHOOK` 后重启 relay）；Loki `logs` profile 未启动
（内存留余量，需要时 `docker compose --profile logs up -d`）；MySQL 双杀演练。

