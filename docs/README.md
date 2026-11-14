# docs/ — 文档总索引

> **本文件由 `scripts/docs_index.py` 生成,勿手改。**
> 重新生成:`python scripts/docs_index.py --write`;校验:`python scripts/docs_index.py --check`(CI `contract` 轨 + `verify.sh contract`)。
> 本页的每个数字都是扫描结果 —— 手写的计数不算数(口径见 [standards/sources-of-truth.md](standards/sources-of-truth.md) §2.4)。

## 怎么用这个入口

| 想知道 | 去哪 |
|---|---|
| 现在该做什么(待办总表) | [backlog/2026-11-03-todo.md](backlog/2026-11-03-todo.md) |
| 哪天交付了什么(里程碑时间线) | [milestones.md](milestones.md) |
| 进行中 / 已归档的设计与计划 | [superpowers/README.md](superpowers/README.md) |
| 对外接口(交付级) | [api/README.md](api/README.md) |
| 写代码 / 排障前(踩坑手册) | [pitfalls/README.md](pitfalls/README.md) |
| 编码规范 | [standards/README.md](standards/README.md) |
| 某条事实谁说了算(口径地图) | [standards/sources-of-truth.md](standards/sources-of-truth.md) |
| 运维手册 / 测量报告 / 安全审计 / 教学 | [ops/README.md](ops/README.md) |

下面才是扫描结果:**非归档文档逐份列出**(按目录分组),**归档只报数**(逐份清单在归档自己的 INDEX.md 里,同一份清单不写两遍)。

## 1. 非归档文档

共 **77** 份 / **13** 个目录(不含本文件)。

### `docs/` 根(1 份)

| 文档 | 标题 |
|---|---|
| [milestones.md](milestones.md) | 里程碑时间线 |

### `docs/api/`(16 份)

| 文档 | 标题 |
|---|---|
| [README.md](api/README.md) | 接口文档(API Reference) |
| [app.md](api/app.md) | 应用配置 |
| [auth.md](api/auth.md) | 账号与鉴权 |
| [conventions.md](api/conventions.md) | 公共说明 |
| [discovery.md](api/discovery.md) | 发现与配对 |
| [errors.md](api/errors.md) | 错误码 |
| [feed.md](api/feed.md) | 广场动态 |
| [feedback.md](api/feedback.md) | 意见反馈 |
| [health.md](api/health.md) | 运维探针 |
| [im.md](api/im.md) | IM 会话凭证 |
| [moderation.md](api/moderation.md) | 举报与拉黑 |
| [notifications.md](api/notifications.md) | 站内通知 |
| [push.md](api/push.md) | 推送 |
| [stats.md](api/stats.md) | 个人使用报告 |
| [telemetry.md](api/telemetry.md) | 客户端错误上报 |
| [users.md](api/users.md) | 用户资料 |

### `docs/backlog/`(1 份)

| 文档 | 标题 |
|---|---|
| [2026-11-03-todo.md](backlog/2026-11-03-todo.md) | 待办事项总表(2026-11-03) |

### `docs/learning/`(2 份)

| 文档 | 标题 |
|---|---|
| [README.md](learning/README.md) | docs/learning/ — 后端通读教学材料 |
| [backend-reading-path.md](learning/backend-reading-path.md) | 后端通读学习路线（新手向） |

### `docs/learning/backend-guide/`(16 份)

| 文档 | 标题 |
|---|---|
| [P00-环境与反馈回路.md](learning/backend-guide/P00-环境与反馈回路.md) | P00 · 环境与反馈回路 |
| [P01-请求怎么进门.md](learning/backend-guide/P01-请求怎么进门.md) | P01 · 请求怎么进门（94 行） |
| [P02-settings逐行.md](learning/backend-guide/P02-settings逐行.md) | P02 · settings.py 逐行（308 行，分 2 次读） |
| [P03-请求怎么出门.md](learning/backend-guide/P03-请求怎么出门.md) | P03 · 请求怎么出门（107 行） |
| [P04-登录上-发验证码.md](learning/backend-guide/P04-登录上-发验证码.md) | P04 · 登录（上）：发验证码（约 258 行） |
| [P05-登录下-JWT与单设备.md](learning/backend-guide/P05-登录下-JWT与单设备.md) | P05 · 登录（下）：校验、JWT、单设备登录（约 180 行） |
| [P06-资料上-模型与在线状态.md](learning/backend-guide/P06-资料上-模型与在线状态.md) | P06 · 资料（上）：模型与在线状态（约 230 行） |
| [P07-资料下-序列化与照片.md](learning/backend-guide/P07-资料下-序列化与照片.md) | P07 · 资料（下）：序列化、视图、照片（约 302 行） |
| [P08-滑卡与配对.md](learning/backend-guide/P08-滑卡与配对.md) | P08 · 滑卡与配对（约 276 行） |
| [P09-IM抽象层与签名.md](learning/backend-guide/P09-IM抽象层与签名.md) | P09 · IM 抽象层与签名（311 行） |
| [P10-Celery异步副作用.md](learning/backend-guide/P10-Celery异步副作用.md) | P10 · Celery 异步副作用（约 309 行） |
| [P11-合规与封禁两级.md](learning/backend-guide/P11-合规与封禁两级.md) | P11 · 合规：举报、拉黑、封禁两级（约 364 行） |
| [P12-广场feed.md](learning/backend-guide/P12-广场feed.md) | P12 · 广场 feed（约 387 行） |
| [P13-运维台ops.md](learning/backend-guide/P13-运维台ops.md) | P13 · 运维台 ops（约 369 行） |
| [P14-收尾横扫.md](learning/backend-guide/P14-收尾横扫.md) | P14 · 收尾横扫与文档门禁（约 272 行 + 全局对账） |
| [README.md](learning/backend-guide/README.md) | 后端通读 · 自学指导书（索引） |

### `docs/ops/`(11 份)

| 文档 | 标题 |
|---|---|
| [README.md](ops/README.md) | docs/ops/ — 运维手册(常驻) |
| [capacity-and-reliability.md](ops/capacity-and-reliability.md) | 容量与可靠性:一页讲清楚(2026-11-04) |
| [certificates.md](ops/certificates.md) | 证书与续期（生产） |
| [dual-server-vs-upgrade-2026-11-04.md](ops/dual-server-vs-upgrade-2026-11-04.md) | 双机负载均衡 vs 只升配:决策记录(2026-11-04) |
| [imserver.md](ops/imserver.md) | 自建 IM 运维手册 |
| [nginx-security.md](ops/nginx-security.md) | nginx 安全基线(HTTPS + 安全头 + 后台白名单) |
| [observability.md](ops/observability.md) | 可观测性:指标、看板与告警 |
| [push.md](ops/push.md) | 推送(C-1):链路、开关与验证 |
| [release.md](ops/release.md) | 发版与远端 Release |
| [runbook.md](ops/runbook.md) | 运维手册:告警处置与故障恢复 |
| [superagent.md](ops/superagent.md) | superagent 运维手册(WSL) |

### `docs/pitfalls/`(7 份)

| 文档 | 标题 |
|---|---|
| [README.md](pitfalls/README.md) | 踩坑手册(索引) |
| [android-emulator.md](pitfalls/android-emulator.md) | 踩坑手册 · 模拟器与 Android 构建 |
| [backend.md](pitfalls/backend.md) | 踩坑手册 · 后端(Django / 接口 / 数据) |
| [frontend.md](pitfalls/frontend.md) | 踩坑手册 · 前端(Flutter / Riverpod) |
| [im.md](pitfalls/im.md) | 踩坑手册 · IM 与聊天 |
| [testing.md](pitfalls/testing.md) | 踩坑手册 · 测试 |
| [web.md](pitfalls/web.md) | 踩坑手册 · Web 端(Vue 网页端、构建与部署) |

### `docs/reports/`(8 份)

| 文档 | 标题 |
|---|---|
| [README.md](reports/README.md) | docs/reports/ — 一次性测量报告 |
| [cache-win-2026-11-05.md](reports/cache-win-2026-11-05.md) | 候选池缓存的真实收益:开/关对比实测(2026-11-05,E-7) |
| [imserver-throughput.md](reports/imserver-throughput.md) | 自建 IM 吞吐优化记录(2026-10-22) |
| [peak-shaving.md](reports/peak-shaving.md) | 削峰:配对通知的队列分级与限速(2026-11-03) |
| [read-baseline-2026-11-04.md](reports/read-baseline-2026-11-04.md) | 读基线重跑 + `candidates` 归因 + 场景矩阵补齐（2026-11-04） |
| [scale-report.md](reports/scale-report.md) | 规模数据报告:10 万用户量级下的查询表现(2026-11-03) |
| [stress-test-2026-11-01.md](reports/stress-test-2026-11-01.md) | 2026-11-01 高并发压测与「打崩自愈」演练 |
| [write-baseline-2026-11-03.md](reports/write-baseline-2026-11-03.md) | 2026-11-03 写路径容量基线（swipe） |

### `docs/reviews/`(1 份)

| 文档 | 标题 |
|---|---|
| [2026-11-03-fullstack-review.md](reviews/2026-11-03-fullstack-review.md) | chatapp 全栈工程审查报告 |

### `docs/security/`(5 份)

| 文档 | 标题 |
|---|---|
| [2026-10-27-api-security-audit.md](security/2026-10-27-api-security-audit.md) | chat_app 接口安全审计报告 |
| [2026-10-28-api-security-audit-round2.md](security/2026-10-28-api-security-audit-round2.md) | chat_app 第二轮安全审计（2026-10-28） |
| [2026-11-01-api-security-audit-round3.md](security/2026-11-01-api-security-audit-round3.md) | chat_app 第三轮安全审计（2026-11-01） |
| [2026-11-08-api-security-audit-round4.md](security/2026-11-08-api-security-audit-round4.md) | chat_app 第四轮安全审计（2026-11-08） |
| [README.md](security/README.md) | docs/security/ — 安全审计报告(只增不改) |

### `docs/standards/`(3 份)

| 文档 | 标题 |
|---|---|
| [README.md](standards/README.md) | 编码规范 |
| [python.md](standards/python.md) | Python 注释规范 |
| [sources-of-truth.md](standards/sources-of-truth.md) | 唯一事实来源(口径地图) |

### `docs/superpowers/`(1 份)

| 文档 | 标题 |
|---|---|
| [README.md](superpowers/README.md) | docs/superpowers/ — 设计 spec 与实施计划 |

### `docs/superpowers/specs/`(5 份)

| 文档 | 标题 |
|---|---|
| [2026-09-15-ui-design-language-design.md](superpowers/specs/2026-09-15-ui-design-language-design.md) | UI 设计规则(设计语言「心跳」) |
| [2026-11-07-superagent-dev-workflow-design.md](superpowers/specs/2026-11-07-superagent-dev-workflow-design.md) | Superagent 本地开发流程设计(v1) |
| [2026-11-08-superagent-automation-ladder-design.md](superpowers/specs/2026-11-08-superagent-automation-ladder-design.md) | Superagent 自动化阶梯设计(L0–L4) |
| [2026-11-13-aws-distributed-deployment-design.md](superpowers/specs/2026-11-13-aws-distributed-deployment-design.md) | AWS 两台悉尼机的分布式部署设计 |
| [2026-11-14-docs-and-scripts-governance-design.md](superpowers/specs/2026-11-14-docs-and-scripts-governance-design.md) | 文档与脚本治理:从「补丁式维护」到「机械化一致性」 |

## 2. 归档

`docs/superpowers/archive/` 共 **105** 份 = **40** spec + **65** plan。

逐份清单(日期 / 主题 / plan ↔ spec 对照)见 **[superpowers/archive/INDEX.md](superpowers/archive/INDEX.md)**。

> 这里只报数、不重复列表:同一份清单两处手写,正是本方案要消灭的那类漂移。
> 「哪天交付了什么、结论是什么」看 [milestones.md](milestones.md)。
