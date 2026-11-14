---
状态: 生效中
复核: 每次架构变更时
---

# 架构与技术要点

> 从 [README.md](../README.md) §2「关键技术要点」与 §7 的「测试形态」段搬来
> (2026-11-14 治理第 6 节:README 只留「门面 + 指针」,细节搬进 `docs/`)。
> **系统边界与三条贯穿全栈的约束仍在 README §1**;容量数字的 owner 是
> [ops/capacity-and-reliability.md](ops/capacity-and-reliability.md),本页不抄第二份。

## 1. 长连接侧的会话状态与消息序号

imserver 是消息的唯一写者:客户端发送经 WS 帧或 `POST /internal/send`,服务端在单个事务内分配会话内自增
`seq`、写入消息体、更新会话摘要,再向收发双方推送下行帧。客户端只依赖 `seq` 做排序与补拉,
离线重连时按本地最大 `seq` 请求增量。连接池对 MySQL `wait_timeout` 做存活探测,
避免空闲连接被服务端回收后 IM 永久失联(`readyz` 探针同源)。

## 2. 已读回执:单写者语义 + 乱序防护

事实来源是 `im_conversation_state.read_seq`,语义是「**我**读到哪」;对端视角通过会话列表的
`peer_read_seq` 暴露。判定永远是「我方消息 `seq <= peer_read_seq` = 已读」,与「我没读的条数」是两条独立链路,
不可互推。服务端在 `read` 帧落库后**回读实库**再向对端广播,落库用 `GREATEST` 语义 —— 乱序到达的旧帧
不会把已读位点推回去;客户端侧只增不减。`read` 帧单独限流(2/s,突发 30),超限静默丢弃而非报错,
避免用户快速滚动时产生错误反馈。

## 3. 鉴权:双令牌轮换 + 会话版本绑定

- **JWT 双令牌**:access 30 分钟 / refresh 30 天,刷新即轮换,旧 refresh 进入黑名单;
  网页端 refresh 落 HttpOnly Cookie(响应体不含 refresh),App 落系统安全存储;轮换后保留 60 秒宽限以支持并发标签页。
- **会话版本 `sv`**:IM token 携带 `sv`,imserver 与 `im_user.session_version` 比对,不一致返回 `40101`;
  **WS 握手与 `/im/api/*` 两个入口同口径**,避免「REST 被踢、长连接仍活」的半失效状态。
- **单设备登录**:登录时同步 `session_version` 到 imserver,被顶设备的三条退出路径(REST 401、WS 关闭、刷新失败)互为兜底。
- **两级封禁**:`banned_light` 仅禁滑卡;`banned_heavy` 全域 403。由全局权限类实现,新接口自动继承,
  白名单只有 `GET /users/me`、`GET /users/tags`。

## 4. 数据访问:游标分页、反连接与查询预算

- **keyset 游标分页**:`config/cursor.py` 以 base64url 编码 `<排序时间>|<主键>` 生成**不透明**游标
  (`?before=`),响应返回 `next_cursor` / `has_more`。排序键带主键兜底,翻页期间有新数据插入也不会重复或漏读;
  深翻页耗时与页深无关。`offset` 参数保留为兼容分支,老版本客户端不因协议升级而卡住。
- **排除列表用 `NOT EXISTS` 反连接**:候选池需要排除「已划过 / 已配对 / 双向拉黑」三类集合,
  原先的 `IN (子查询)` 会随活跃度线性膨胀;改为相关子查询后走索引探测。**必须拆成两次 `exclude`** ——
  `exclude(a, b)` 的语义是 `NOT (a AND b)`,与「不同时满足」并不等价。
- **索引与门禁**:`Match(user_b)`、`Swipe(target, action, -created_at, -id)`、`Photo(status, user_id)`
  三条索引支撑列表与角标查询;`config/test_query_budget.py` 以 `assertNumQueries` 锁定查询条数预算,
  并对「排除必须走 EXISTS」「三条索引必须存在」做断言 —— 查询性能退化会在 CI 阶段暴露,而不是等到线上。

## 5. 媒体管线:重编码、签名地址与配额

资料图 / 广场图 / 聊天图统一经 `config/images.py`:校验 MIME 与像素上限(≤2000 万像素、长边 4096),
`exif_transpose` 校正方向后**重新编码以剥离 EXIF/GPS**。聊天媒体不出公开 URL,改为限时签名地址
(TTL 默认 3600),由 nginx `auth_request` 子请求 `/im/images/auth` 验签后才放行 —— 直链可撤销、不可枚举。
存储配额按库内 `bytes` 求和(单账号默认 200MB),检查发生在落盘之前,超限返回 `413 + 41301`;
删除与 30 天过期回收都不依赖计数列,避免并发下的漂移。

## 6. 契约工程:四处生成物 + 四处门禁

接口与协议的「一致性」不靠自觉,而是四个可执行门禁:

| 契约 | 事实来源 | 派生 / 校验 |
|---|---|---|
| HTTP 接口文档 | 视图与序列化器 | `docs/api/`(份数与操作数以 `openapi.yml` 为准,由 `scripts/docs_index.py` 机械校验)+ `ApiDocsCoverageTests` 双向比对路由与文档 |
| 机器可读 schema | 视图上的 `@extend_schema` | `docs/api/openapi.yml` 由 `drf-spectacular` 生成(禁止手改),CI 重新生成后 `git diff --exit-code` |
| 字段级一致性 | 文档参数表 ↔ schema 字段 | `config/api_schema_contract.py` 双向比对;Web 侧 `openapi-typescript` 生成 `schema.d.ts` 并对手写类型做编译期断言;App 侧 `scripts/check_app_models.py` 扫描 `models.dart` 的 JSON 键 |
| WS 帧协议 | `imserver/tests/fixtures/ws/*.json` | imserver(`frames.h` 序列化)、App、Web 三端各自用真实解析路径消费同一份 fixture,任一端改帧格式三轨同时变红 |

版本号同样收敛到单一来源:`app/pubspec.yaml` 为事实来源,`scripts/sync_version.py --check` 校验
App 常量、Web `package.json` 与关于页测试期望三处一致(CI `contract` 轨拦截)。

## 7. 可观测性与容量工程

- **指标**:`prometheus_client` 自建 registry;gunicorn `-w 2` 下必须用 `PROMETHEUS_MULTIPROC_DIR` +
  `MultiProcessCollector`,否则计数器按进程分裂、`rate()` 误判重置。业务指标含
  `logins_total` / `swipes_total` / `matches_total` / `im_calls_total`。
- **采集**:Prometheus 多 target(api / im / node / celery / mysqld / redis),Grafana 概览看板,
  Alertmanager 规则经宿主机 relay 转邮件(与 22:00 服务器日报同一条链路,去重键 `groupKey + status`);
  Loki 作为可选 profile 按需启用。**target 数与规则条数的 owner 是
  [ops/observability.md](ops/observability.md)**,本页不写数字。
- **日志**:单行 JSON,字段含 `route` / `status` / `duration_ms` / `request_id`;前端未捕获异常经
  `POST /client-errors` 汇总为同一条日志流与 `client_errors_total{platform}` 指标,两侧 `request_id` 对齐。
- **容量方法学**:`perf/` 是可复现的压测与回归工具(`run.py` + `baseline.json`),覆盖读、写、multipart 上传、
  70/30 混合、WS 重连风暴、0→1000 突发等场景;报告只记录「合成规模 + 合成请求模型」,并明确标注口径。
  **实测基线与「数字怎么读」的唯一 owner 是
  [ops/capacity-and-reliability.md](ops/capacity-and-reliability.md)**(原始数据在
  [`docs/reports/`](reports/README.md))—— 引用容量数字时引用它,不要在别处抄第二份。

## 8. 交付与恢复纪律

- **CI 的 workflow(当前 10 个)**:`backend` / `app` / `app-ui` / `web` / `web-e2e` / `imserver` /
  `contract` 七条判定轨,另有 `auto-merge`(白名单自动合并)、`main-health`(每天检查默认分支每条
  workflow 的最新 push run)、`l4-intake`(需求自动入队,总闸默认 `off`)。
  **门禁清单的 owner 是 [`scripts/gates.toml`](../scripts/gates.toml)**:本地 `scripts/verify.sh contract`
  与 CI 调**同一个执行器**(`scripts/run_gates.py`),两边条数相等。
  **`contract` / `backend` / `web` 是默认分支的必需检查**(2026-11-12 起),backend / web 的重活按改动面跑
  (`scripts/ci-scope.sh`,无关时 `skipped`)。
- **发布只认 `origin/main` 的 SHA**:分支 → PR → CI 全绿 → squash 合并 → 部署合并后的 commit;
  部署前先记回滚点(旧 SHA / 旧镜像 tag / `.env` 备份),禁止把未合并的本地提交直接上线。
  清单见 [ops/release.md](ops/release.md),部署闸门是 `python scripts/deploy_gate.py`。
- **备份三层**:03:20 自建双库全量(应用库 + IM 库 + 媒体 + 配置,每份带 `.sha256`,并断言 dump 末行
  `-- Dump completed` 以防截断包)、03:30 面板原生备份、04:10 树莓派以只读账号主动拉取;
  保留 14 天,三项均进日报,**恢复演练已实际执行**(干净 MySQL 实例恢复后走完整登录链路)。
  步骤与演练记录见 [ops/runbook.md](ops/runbook.md) §5。
- **故障演练**:MySQL 双杀演练两轮,检测延迟与 MTTR 记录在
  [ops/runbook.md](ops/runbook.md) §2.4;演练本身暴露并修复了看门狗锁文件被守护进程继承导致的
  自我关闭缺陷。

## 9. 测试形态:真实装配 + 假外部世界

测试形态的取舍是「**真实装配 + 假外部世界**」:UI 测试运行真实的 Riverpod provider 树与真实路由,
只把网络与 IM 替换为可控替身,因此测到的是生产装配而不是 mock 的装配。

| 层 | 工具与形态 | 门禁 |
|---|---|---|
| 后端 | `manage.py test` 全量;IM 副作用一律 mock(`im.tasks.*.delay`),并发正确性用唯一约束 + `CheckConstraint` 覆盖 | 全量绿 + 查询预算 + 注释覆盖 + 接口文档双向比对 + schema 字段级比对 |
| 客户端 | `flutter test`;`test/support/` 提供脚本化假网络、假 IM 客户端与 `pumpApp` 组合入口 | `flutter analyze` 零告警 + 全绿 |
| 网页端 | vitest + MSW(组件与 store 真实);Playwright 端到端跑构建产物 | `vue-tsc` 零错误 + `eslint --max-warnings 0` + 覆盖率门槛 70/60/70/70 |
| 长连接 | imserver unit / DB / WS / HTTP 四套;跨栈帧 fixture 三端共享 | 三轨 CI 各自校验同一份 fixture |
| 端到端 | 冒烟场景进 CI(真 MySQL + Redis + Django + preview);全量场景需 imserver + Celery,本地执行 | 失败上传 Playwright 报告 |

关键业务不依赖人工点击:配对并发、限流窗口、验证码锁定、封禁分级、单设备登录的三条退出路径、
已读回执的乱序防护、游标分页的翻页一致性,都有对应用例。**推之前跑什么见
[`AGENTS.md`](../AGENTS.md) §三**;门禁清单见 `scripts/gates.toml`。
