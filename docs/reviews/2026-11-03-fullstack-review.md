# chatapp 全栈工程审查报告

| 项 | 内容 |
|---|---|
| 审查日期 | 2026-11-03 |
| 审查对象 | `chat_app` 仓库（Flutter App + Django API + 自建 C++ IM + Vue Web + Docker 部署） |
| 基线 commit | `f275e1a`（master，工作区干净） |
| 代码规模 | 后端 ~60.8k 行 / App ~26.2k 行 / Web ~10.3k 行 / imserver ~1.8k 行 |
| 审查方式 | 静态代码阅读（逐文件），未运行测试、未连生产环境 |
| 审查范围 | 后端全部业务 app、imserver 传输层与服务层、Web/App 的 IM 与网络层、CI 四轨、deploy 脚本、可观测性配置 |
| 未覆盖 | 运行期性能实测、真实并发行为、数据库执行计划实测、iOS/Android 打包链路 |

---

## 一、结论摘要

**工程质量显著高于同类个人全栈项目的平均水平。** 已具备的能力包括：693 个后端测试、查询预算（N+1）门禁、注释覆盖率门禁、接口文档双向门禁、CI 四轨（backend / web / app / imserver）、压测与容量报告、三轮安全审计整改记录、Prometheus + Alertmanager + Grafana 观测栈。

因此本报告不讨论"缺测试""缺文档""没做限流"这类问题——这些项目已做得比多数生产系统更严谨。

本次审查的缺陷集中在三个维度，且**绝大多数无法被现有测试门禁发现**：

1. **一处真实的功能性缺陷**（Web 端 IM 静默断连），源于"服务端空闲超时 + 客户端无心跳 + 传输层不暴露关闭事件"三者叠加，任一端单独看都合理；
2. **数据层随规模劣化的三处缺索引 + 两处分页缺陷**，CI 全绿是因为门禁只钉了 SQL 条数、没钉执行计划；
3. **跨栈契约与运维尾部风险**——三套客户端手抄同一份协议、备份与数据库同盘、前端无错误上报。

另有一组**已记录但未关闭的严重风险**（固定验证码、无机器审核、无推送、无实名），本报告单列并给出优先级判断。

**风险最高的两项（与代码质量无关）：固定验证码 `123456` 与备份同盘手动。**

---

## 二、本次新发现的缺陷

### N-1【P0·功能正确性】Web 端 IM 静默断连，前端无感知、无重连

#### 现象

网页端打开聊天页后，若 75 秒内用户没有主动发送消息，服务端关闭 WebSocket；前端不监听关闭事件，状态仍显示 `ready`，此后对方发来的新消息**静默丢失**——会话列表、未读角标均不更新。用户必须刷新页面，或主动发一条消息（会卡 10s × 3 次重试后失败）才能恢复。

#### 证据链

三处独立设计叠加导致，缺一不成：

| # | 位置 | 事实 |
|---|---|---|
| 1 | `imserver/src/net/ws_server.cpp:231-247` | `arm_idle_timer()` 每 15s 检查一次，`:239` 判断 `idle > 75s` 即 `do_close(1000)` |
| 2 | `imserver/src/net/ws_server.cpp:292-298` | `last_frame_` **只在 `on_read` 中更新**（业务数据帧），`:212` 仅在连接建立时初始化一次 |
| 3 | `imserver/src/net/ws_server.cpp:331-337` | 只有收到业务层 `{"type":"ping"}` 才回 `pong` 并刷新计时 |
| 4 | `app/lib/im/self_im_client.dart:163-168` | App 每 **25 秒**发一次业务 `ping` → App 不受影响 |
| 5 | `web/src/im/self/transport.ts:2-6` | `SelfTransport` 接口只声明 `onFrame / connect / send / close`，**没有 `onClose`**；`:31-33` 的 `close()` 只供调用方主动关闭 |
| 6 | `web/src/im/self/client.ts:60` | 连接后只挂 `transport.onFrame(...)`；`:75-145` 的 `onFrame` 处理 auth_ok / kicked / error / ack / message / revoked，**无任何关闭或断线分支** |
| 7 | `web/src/stores/chat.ts`（全仓 `setInterval` 扫描） | 仅登录倒计时、录音计时、presence 轮询三处，**没有 IM 心跳定时器** |

补充机制说明：Beast 的 `async_read` 在协议层内部消费控制帧（含浏览器对服务端 ping 自动回的 pong），不会进入 `on_read`，因此**WS 层的 keep-alive 不能刷新 `last_frame_`**。这也是为什么服务端 `timeout::suggested` 的 keep-alive ping 救不了这条连接。

> 说明：`do_close(1000)` 使用的是正常关闭码，即便前端补上 `onclose` 监听，也无法从关闭码区分"正常关闭"与"空闲踢出"，必须无条件按断线处理。

#### 影响

- 用户侧：网页端"以为在线、实际收不到消息"，是最伤信任的一类聊天故障；且故障表现与"对方没发"完全一样，用户难以归因。
- 排查侧：服务端无 5xx、无 error 日志（`do_close(1000)` 是正常路径），Prometheus 指标不报警，只有前端用户能感知——与 N-7（无错误上报）叠加后几乎不可发现。

#### 建议修复

1. `SelfTransport` 增加 `onClose(fn)`，`BrowserWebSocketTransport` 挂 `ws.onclose` / `ws.onerror`；
2. `SelfImClient` 增加 25s 心跳（与 App 对齐），并把 `onClose` 映射为 `kickedOffline` 之外的独立事件 `disconnected`；
3. `stores/chat.ts` 收到 `disconnected` 后置 `status = 'reconnecting'` 并按 1/2/4/8/16/30s 退避重连，重连成功后**必须补拉**会话与当前会话消息（服务端有 seq 与离线补拉能力，可直接复用）；
4. 注意与既有设计冲突：`stores/chat.ts:131-143` 明确「同端多标签互踢时**不得**自动重连」（实测 10 秒内打了 27 次 `user_sig` 被限流）。因此重连必须区分 `multiAccount`（不重连、等用户接管）与 `disconnected`（自动重连）两种原因，不能合并处理。

#### 建议测试

用假 transport 注入 `onClose` 事件 → 断言 `status` 变 `reconnecting` → 断言退避后重新 `connect` → 断言重连后触发消息补拉。这条测试可直接钉死该缺陷的回归。

---

### N-2【P1·性能】三处缺失索引，数据量增长后线性劣化

同一类问题你们已经在 `imserver/migrations/002_search_index.sql`（`im_conversation.idx_user_b`）中踩过并修复，但 Django 侧同样的三个坑仍在。

| # | 表 / 位置 | 现有索引 | 受影响的查询 | 后果 |
|---|---|---|---|---|
| 1 | `Match`（`chatapp/discovery/models.py:68-72`） | 仅 `unique(user_a, user_b)` | `match_list`：`Q(user_a=me) \| Q(user_b=me)`（`discovery/views.py:160`） | `user_b` 不是任何索引的前导列 → OR 退化为全表扫 + filesort |
| 2 | `Swipe`（`chatapp/discovery/models.py:33-37`） | 仅 `unique(swiper, target)` | `likes_received_queryset`：`filter(target=me, action=like)`（`discovery/services.py:126-135`） | `target` 不是前导列 → 全表扫；该 queryset 同时服务列表与计数两个接口 |
| 3 | `Photo`（`chatapp/users/models.py:232-233`） | Meta 中无任何 `indexes` | 子查询 `Photo.objects.filter(status=APPROVED).values("user_id")`，被候选池（`services.py:48`）、喜欢我的人（`:125`）、访客（`:149`）三处复用 | `status` 无索引 → 每次缓存未命中都扫全表 photo |

#### 为什么 CI 全绿

`chatapp/config/test_query_budget.py` 只钉 **SQL 条数**（防 N+1）与**页大小不变性**，不检查执行计划与索引命中。这两件事正交：一条扫全表的 SQL 也只算 1 条。

#### 建议

1. `Match` 增加 `Index(fields=["user_b"])`；
2. `Swipe` 增加 `Index(fields=["target", "action"])` 或 `Index(fields=["target", "-created_at"])`（按实际执行计划二选一）；
3. `Photo` 增加 `Index(fields=["status", "user_id"])`；
4. 可选增强：给查询预算测试加一条 EXPLAIN 断言（`type` 不得为 `ALL`），把这类问题纳入门禁。

---

### N-3【P1·性能】`GET /matches` 在内存中分页

`chatapp/discovery/views.py:159-167`：

```python
matches = Match.objects.filter(...).select_related(...).prefetch_related(...)   # 无切片
entries = [_match_entry(match, me, request) for match in matches]               # 全量构建
page = paginator.paginate_queryset(entries, request)                            # 在 list 上分页
```

配对数上千的用户，每次拉第一页都会把**全部**配对行连同双方照片 prefetch 进内存。这是全仓唯一一处绕过数据库分页的列表接口——feed / likes / visits 均为 queryset 分页。

**建议**：改回 queryset 分页（`Match.Meta.ordering = ["-created_at"]` 已保证翻页顺序稳定），头像绝对 URL 在序列化阶段生成。

---

### N-4【P1·性能】候选池的排除列表无上限增长

`chatapp/discovery/services.py:36-53`：

```python
swiped_ids = Swipe.objects.filter(swiper=me).values_list("target_id", flat=True)
matched_ids = [...]                       # 先 list() 再 user_id__in=
blocked_ids = blocked_user_ids(me)        # 同样是 list
```

滑卡限流为 300/小时，重度用户数月即可积累数万 id，`IN (...)` 的 SQL 长度与解析开销随活跃度线性增长——而这正是你们用 `Profile.shuffle_key` 精心优化掉 `ORDER BY RAND()` 的那条接口，优化收益会被这部分抵消。

**建议**：三处改为 `Exists()` 相关子查询或反连接（`~Exists(...)`），彻底消掉 Python 侧 id 列表。

---

### N-5【P2·正确性】广场动态流使用 offset 分页

`chatapp/config/pagination.py:9-10` 全局 LimitOffset，`feed/views.py` 沿用。动态流是"头部持续插入"的列表，offset 分页在发帖后必然出现**翻页重复与漏读**（新帖插入后第 2 页会重复第 1 页内容）。

值得注意的是，`Post` 已经建了 `(-created_at, -id)` 索引（`feed/models.py:29`），说明排序设计本就 cursor 友好，只是分页协议没跟上。

**建议**：`/posts` 增加 cursor（`created_at` + `id` 复合游标）分页；`/discovery/likes`、`/discovery/visits`、`/matches` 同理（都是"按时间倒序、头部插入"的语义）。

---

### N-6【P1·可用性】备份与数据库同盘、手动执行、无异地、无恢复演练

- `deploy/chatapp:55-60`：`backup` 子命令把 `mysqldump` 写到 `$APP_DIR/backups/`——**与数据库同一块磁盘**；
- 无 cron 定时任务（`docs/ops/runbook.md` 仅覆盖告警处置与进程恢复，无备份章节）；
- 无异地/对象存储同步（全仓无 `ossutil` / `rsync` / 对象存储相关配置）；
- 无恢复演练记录；`CLAUDE.md` 中 T-18「备份策略」仍挂在待办。

**影响**：磁盘故障 = 用户数据全丢。这是当前**最大的单点风险**，严重性高于本报告任何一条代码缺陷。

**建议**：`mysqldump` → 加密 → 上传 OSS（异地）→ 保留 N 天；`backup-media` 同步；写一页「从备份恢复」演练文档并**实际跑一次**（未演练的备份等于没有备份）。

---

### N-7【P1·可观测性】前端无错误上报

全仓 `sentry` / `bugsnag` / `rollbar` 零命中。Prometheus 覆盖服务端 5xx 与 p99，但**前端白屏、JS 运行时异常、Flutter 崩溃**在服务端指标中可能完全不出现（用户不刷新就没人知道）。与 N-1 叠加后形成"故障只在用户侧可见"的盲区。

**建议**：Web 接 Sentry（或自建 GlitchTip），App 接 `sentry_flutter`；两侧都把 `request_id` 作为 tag 透传，与服务端日志对齐。

---

## 三、已记录但未关闭的严重风险

以下各项在 `CLAUDE.md` / `docs/security/` 中已有记录，本报告不重复分析，仅给出**优先级判断**——其中第 1 项我认为应视为最高优先，而非"待办"。

| # | 风险 | 当前状态 | 本报告判断 |
|---|---|---|---|
| K-1 | **短信验证码固定为 `123456`**（`settings.py:356` 默认 `SMS_DEV_MODE=1`；`notifications/backends.py` 中 `SMS_DEV_MODE=0` 分支只是打 error 日志、不发短信） | 产品决定暂不修，仅封闭测试 | **全项目第一风险。** 任何知道手机号的人可直接登录该账号，读走全部聊天记录。它使另外 40 余项安全整改的价值大幅打折。要么接真实短信商（阿里云/腾讯云 SMS，约半天工作量），要么用邀请码/号码白名单把注册面彻底关死 |
| K-2 | 聊天图片/语音无机器审核（仅人工抽审兜底） | 上线阻断项，已记录 | 备案后监管最易命中的项，优先于任何性能优化 |
| K-3 | 无消息推送（P1-4 挂起，待极光 key 与备案域名） | 挂起 | 聊天产品缺推送 = 用户不会回来，属产品闭环缺口而非技术债 |
| K-4 | 无实名认证；年龄仅取用户自填生日 | 未启动 | 交友类应用合规硬要求，建议与 K-2 同批推进 |

---

## 四、结构性债务（非缺陷，但决定后续迭代成本）

| # | 债务 | 证据 | 影响 |
|---|---|---|---|
| D-1 | **三套客户端手抄同一份契约，无 OpenAPI/代码生成** | `config/api_doc_coverage.py:105-125` 的门禁**只比对「HTTP 方法 + 路径」**；Flutter 与 TS 的模型均为手写 | 字段改名、类型变更、错误码新增时：测试全绿、文档全对、客户端悄悄崩。版本号需三处手改（`pubspec.yaml` / `app_info.dart` / `package.json`）是同一根因 |
| D-2 | **双 IM 后端并存** | `IM_SELF_GRAYLIST=all` 后，`im/client.py` 的腾讯分支、`tencent_im_client.dart`、`routing_im_client.dart`、Web 的 `im/routing.ts` 仍在维护 | 纯维护负担，且必须持续防腐化。建议给腾讯路径一个明确的删除日期 |
| D-3 | **跨栈协议无契约测试** | imserver 集成测试由 Python 侧发帧；App/Web 的 IM 测试全部使用假 transport | "服务端改了帧格式"只有人工手测能发现。建议把协议帧样例固化为共享 fixture，三端各跑一遍 |
| D-4 | **单机单点** | 2C2G 单机、单 MySQL 实例、手工记 SHA 回滚、无蓝绿 | 单机天花板已实测（200–250 msg/s）并写清，很诚实；但"再往上必须换架构"尚无落地路径 |
| D-5 | **e2e 不进 CI** | `web.yml` 注释：端到端需真后端 + Redis + Celery，不进 CI；Playwright 8 条靠人工 | 跨栈集成在 CI 中零覆盖，回归依赖人工 |

---

## 五、修复优先级路线图

按「风险 × 成本」排序，前三项合计约两天。

| 顺序 | 内容 | 对应项 | 预估成本 | 收益 |
|---|---|---|---|---|
| 1 | Web IM 心跳 + `onClose` + 退避重连 + 重连后补拉 | N-1 | 半天 | 直接修掉一个静默丢消息的 P0，且可用测试钉死 |
| 2 | 三个索引 + `matches` 改 queryset 分页 + 排除列表改 `Exists` | N-2 / N-3 / N-4 | 一天 | 数据涨 10 倍时曲线不变 |
| 3 | 备份上 cron + 同步 OSS + 写恢复演练；前端接错误上报 | N-6 / N-7 | 半天 | 关掉"数据全丢"与"线上白屏无人知"两个尾部风险 |
| 4 | 接真实短信商或关死注册面 | K-1 | 半天 ~ 一天 | 消除账号接管风险 |
| 5 | 机器审核（图片/语音）+ 实名 | K-2 / K-4 | 数天（含第三方对接） | 解除上线阻断 |
| 6 | cursor 分页 | N-5 | 一天 | 动态流翻页不再重复/漏读 |
| 7 | OpenAPI + 客户端代码生成 | D-1 | 数天 | 消除三端契约漂移的根因 |

---

## 附录 A：N-1 的复现与验证步骤

**前置**：后端 + Redis + Celery 运行中，两个账号 A（网页端）与 B（App 或另一个浏览器）。

1. 账号 A 在浏览器登录，进入任意聊天会话页，确认能正常收发；
2. **静置 80 秒**，期间 A 不发任何消息（保持页面在前台、不切标签页）；
3. 用账号 B 向 A 发送一条消息；
4. 观察 A 的页面：预期缺陷表现为——消息不出现、会话列表不更新、未读角标不变，且页面无任何错误提示；
5. 交叉验证服务端：`docker logs imserver` 应能看到该连接以 `1000` 关闭（正常关闭码，无 error 日志）。

**对照实验**：同样步骤在 App 上执行，消息应正常到达（App 有 25s 心跳）。

**判定**：若步骤 4 复现，则 N-1 成立，按第二节建议修复；若不复现，请检查该会话是否因其他原因（如 presence 轮询触发的 HTTP 请求）被算作"活动"——但按 `ws_server.cpp:292-298` 的实现，HTTP 请求不会刷新 WS 的 `last_frame_`，故理论上不应影响结论。

---

## 附录 B：本次审查的局限

1. **未运行代码**。全部结论来自静态阅读，N-1 的机制链在代码上闭合，但仍建议按附录 A 实测确认后再排期；
2. **未做执行计划实测**。N-2 的三处缺索引依据的是模型定义与查询形态，实际劣化拐点需在真实数据量下 `EXPLAIN` 确认；
3. **未审计生产配置**。K-1 的实际风险取决于线上 `.env` 中 `SMS_DEV_MODE` 的真实取值（若为 `0`，则用户收不到验证码、登录不可用，问题性质从"可被接管"变为"不可用"）——两种取值都是严重问题，需现场确认；
4. **未覆盖**：iOS/Android 打包与证书链路、腾讯云 IM 分支（已判定为待删除）、ops 后台模板层、`perf/` 压测脚本本身。
