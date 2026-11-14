# chat_app · 交友应用全栈工程

> Flutter 客户端 + Django REST 业务后端 + 自建 C++ 长连接服务：三个进程、两个数据库、一套契约。
> **业务事实**(账号、资料、滑卡、配对、广场、举报、通知偏好)留在 Django/MySQL；
> **会话与消息状态**(消息体、序号、已读位点、配对镜像)由 imserver/MySQL 持有。
> 两侧只通过签名内部 API 与异步任务交互，响应路径不出现任何第三方调用。

**在线实例**:<https://chat.shiliu153.cn> —— PC 浏览器进网页端,移动端浏览器进引导页。

[![Backend CI](https://github.com/shiliu153/chatapp/actions/workflows/backend.yml/badge.svg?branch=main)](https://github.com/shiliu153/chatapp/actions/workflows/backend.yml)
[![App CI](https://github.com/shiliu153/chatapp/actions/workflows/app.yml/badge.svg?branch=main)](https://github.com/shiliu153/chatapp/actions/workflows/app.yml)
[![Web CI](https://github.com/shiliu153/chatapp/actions/workflows/web.yml/badge.svg?branch=main)](https://github.com/shiliu153/chatapp/actions/workflows/web.yml)
[![IM Server CI](https://github.com/shiliu153/chatapp/actions/workflows/imserver.yml/badge.svg?branch=main)](https://github.com/shiliu153/chatapp/actions/workflows/imserver.yml)
[![Contract CI](https://github.com/shiliu153/chatapp/actions/workflows/contract.yml/badge.svg?branch=main)](https://github.com/shiliu153/chatapp/actions/workflows/contract.yml)
[![Web E2E](https://github.com/shiliu153/chatapp/actions/workflows/web-e2e.yml/badge.svg?branch=main)](https://github.com/shiliu153/chatapp/actions/workflows/web-e2e.yml)
[![API Docs](https://img.shields.io/badge/API%20docs-reference-blue)](docs/api/README.md)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

**中文** · [English Abstract](#english-abstract)

---

## 目录

- [1. 系统架构](#1-系统架构)
- [2. 关键技术要点](#2-关键技术要点)
- [3. 功能范围](#3-功能范围)
- [4. 技术选型与理由](#4-技术选型与理由)
- [5. 目录结构](#5-目录结构)
- [6. 快速开始](#6-快速开始)
- [7. 测试与门禁](#7-测试与门禁)
- [8. 部署、容量与运维](#8-部署容量与运维)
- [9. 文档索引](#9-文档索引)
- [10. 许可](#10-许可)
- [English Abstract](#english-abstract)

---

## 1. 系统架构

### 1.1 进程与数据边界

```
      Flutter App (app/)            Vue 3 SPA (web/)
            │  HTTPS /api/v1            │  同源
            └────────────┬──────────────┘
                         ▼
              ┌──────────────────────────────┐
              │ nginx :443 / :80             │
              │  TLS 终止 · 静态直出 · 反代  │
              └───┬──────────────────┬───────┘
   /api/v1/*      │                  │  /im/ws(101 Switching Protocols)
                  ▼                  ▼
      ┌────────────────────┐   ┌─────────────────────────────┐
      │ gunicorn -w 2      │   │ imserver(C++20)             │
      │ Django 5.2 + DRF   │   │ WS :9100 · HTTP :9101       │
      └──┬──────────┬──────┘   └──┬───────────────┬──────────┘
         │          │             │               │
    ┌────▼─────┐ ┌──▼─────────┐ ┌─▼────────────┐  │
    │ MySQL 8  │ │ Redis 7    │ │ MySQL 8      │  │
    │ chatapp  │ │ DB0 缓存   │ │ chatapp_im   │  │
    │ 业务事实 │ │ DB1 broker │ │ 会话 / 消息  │  │
    └──────────┘ │ DB2 IM 状态│ └──────────────┘  │
                 └──┬─────────┘                   │
              ┌─────▼──────┐                      │
              │ Celery     │◀─────────────────────┘
              │ 副作用任务 │  POST /internal/push/new-message
              └────────────┘  (仅「消息落库 + 目标不在线」时回调;推送通道固定 off)
```

| 关注点 | 归属 | 关键约束 |
|---|---|---|
| 账号 / 资料 / 照片 / 滑卡 / 配对 / 广场 / 举报 / 通知偏好 | Django + `chatapp` 库 | 唯一写者;所有对外契约由 `/api/v1` 定义 |
| 会话 / 消息体 / 序号 / 已读位点 / 配对镜像 | imserver + `chatapp_im` 库 | 消息只经 imserver 落库,Django 不写消息表 |
| 跨进程调用方向 | Django → imserver | `im/self_client.py` 调 HMAC 内部 API,签名串 `ts\nMETHOD\npath\nbody`,带时间戳窗口 |
| 反向回调 | imserver → Django | 仅 `POST /internal/push/new-message` 一个入口:同密钥 + 300s 窗口 + 按 `msg_id` 幂等(推送通道固定 `off`,见 §3) |
| 身份映射 | 两侧一致 | IM 账号 = `u{user_id}`;JWT 里的 `user_id` claim 是字符串 |

**为什么这样切分**:消息的写入热点在长连接侧,业务事实的写入热点在 REST 侧。把两者放进同一个进程会让
「一条消息落库」与「一次资料更新」争夺同一套事务与连接池;拆开后各自可以独立回滚(回退 imserver 镜像 /
回退后端 SHA),也不必为了聊天吞吐去扩容业务后端。

### 1.2 三条贯穿全栈的约束

1. **响应路径零第三方调用** —— 请求处理过程中不发起任何外部网络调用。所有跨系统副作用
   (IM 建号、发消息、刷头像、系统通知)在 `transaction.on_commit(fn, robust=True)` 中投递 Celery 任务。
   接口耗时因此与 IM 通道的抖动解耦,失败可重试且有独立指标。
2. **IM 副作用唯一出入口 `im/tasks.py`** —— 任务参数是任务相关的 id(多数是账号 id,命名随语义变:`reporter_id` / `owner_id` / `other_id` / `user_a_id` / `user_b_id`;`post_commented` / `post_replied` 传评论主键 `comment_id`;唯一**不查库**的例外是 `delete_account`,参数是 `im_user_id`),任务内部自行查库,任务体内不接触 request 对象;
   `im/client.py`(语义层)与 `im/self_client.py`(传输层)对外永不抛异常,失败以状态位与指标表达。
3. **错误信封唯一形状** —— 失败一律 `{"code": <HTTP 状态码>, "message": "<中文>", "request_id": "..."}`,
   业务码 = 前 3 位 HTTP 状态 + 2 位序号(`config/error_codes.py`);`request_id` 同时写入结构化日志、指标标签与客户端上报。

---

## 2. 关键技术要点

**已搬到 [`docs/architecture.md`](docs/architecture.md)**:长连接侧的会话状态与消息序号、已读回执的乱序防护、
双令牌与会话版本、游标分页与反连接、媒体管线、契约工程(四处生成物 + 四处门禁)、可观测性与容量方法学、
交付与恢复纪律、测试形态。

容量数字的**唯一 owner** 是 [`docs/ops/capacity-and-reliability.md`](docs/ops/capacity-and-reliability.md) ——
引用容量口径时引用它,本页不再抄第二份(手写副本必然漂移)。

---

## 3. 功能范围

| 域 | 能力 |
|---|---|
| 账号与鉴权 | 手机号 + 验证码登录(未注册自动建号);准入名单收口(名单外 `403 + 40301`);JWT 双令牌轮换;单设备登录;注销即硬删除并释放号码 |
| 资料与偏好 | 昵称 / 性别 / 生日 / 城市 / 简介 + 12 个兴趣标签;照片上传与审核状态;资料完善度由后端判定并返回缺项;择偶偏好(性别 / 年龄区间 / 城市) |
| 发现与配对 | 候选卡(偏好过滤 + 排除已划过/已配对/双向拉黑,只推有已过审照片者);滑卡幂等;互喜配对并在事务提交后向双方投递系统消息;喜欢我的人;谁看过我(含隐身开关) |
| 聊天 | 自建 IM:文本 / 图片 / 语音 / 表情;会话列表四态;消息搜索与定位;已读回执;撤回与解除配对后的双向拉黑;在线状态(120 秒内有认证请求) |
| 广场 | 动态发布 / 点赞 / 评论(两级楼中楼 + 回复提醒) |
| 治理 | 举报、拉黑、两级封禁、举报处理通知;运营审核台(`/ops/`:举报队列 / 照片审核 / 意见反馈 / 准入名单 / 封禁操作),TOTP + IP 白名单 + 登录锁定保护 |
| 通知 | 站内系统消息(配对成功、举报处理结果、封禁提示)与四类通知偏好开关。**不做离线推送**(2026-11-05 决定):服务端保留设备/偏好接口与 `off / log / jpush` 通道抽象,通道固定 `off`,客户端不集成推送 SDK |
| 客户端 | Flutter App(Android 已发签名包;iOS 工程就绪未签名)与 Vue 3 网页端(仅 PC 浏览器,移动端进引导页),共用同一套接口 |

---

## 4. 技术选型与理由

| 层 | 选型 | 理由 |
|---|---|---|
| 客户端 | Flutter | 自定义绘制密度高(设计语言要求 token 化的色板 / 字阶 / 动效),Flutter 的绘制控制力优于 WebView 方案;单代码库覆盖双端 |
| 客户端状态 | Riverpod + go_router | provider 可组合且不依赖 `BuildContext`,测试中可直接覆写依赖;路由表集中声明,未登录重定向与深链只有一处定义 |
| 网络层 | dio + 自定义 Interceptor | 401 统一走刷新通道并做并发去重,是单设备登录能落地的前提 |
| 网页端 | Vue 3 + TypeScript + Pinia + Vite | Flutter Web 实测不可行(IM 插件依赖 `dart:ffi`),改用 Vue;桌面场景下构建链路与类型生态更完整 |
| 网页端测试 | Vitest + MSW + Playwright | 组件与 store 保持真实,只在网络层用 MSW 拦截;端到端跑构建产物 + `vite preview` 而非 dev server |
| 业务后端 | Django 5.2 LTS + DRF | LTS 维护周期;ORM / 迁移 / admin 可直接承载运营审核台的鉴权体系 |
| 数据访问 | MySQL 8 | 需要唯一约束与 `CheckConstraint` 保证配对幂等与并发正确性;`EXPLAIN` 与索引可控 |
| 缓存 / 队列 | Redis 7 + Celery | 验证码、限流、候选池缓存、broker 分库隔离;跨系统副作用全部异步化 |
| 长连接 | 自建 C++20 imserver | 消息写入与广播需要可控的线程模型与背压策略;单后端、无灰度开关,回退方式是回退镜像 |
| 可观测 | Prometheus + Grafana + Alertmanager | 指标与告警链路自建,不引入 SaaS 依赖;告警落地为邮件,与日报共用通道 |
| 部署 | 阿里云轻量 2C2G + 面板托管 | 容量实测在该配置上完成,升级触发条件写在决策记录里(p50 持续 > 1s 或同时在线 > 100) |

---

## 5. 目录结构

**owner 是 [`CLAUDE.md`](CLAUDE.md)「目录结构」** —— 那张表按 `app/` / `chatapp/` / `imserver/` / `web/` /
`docs/` / `flutter/`(SDK,勿改)逐项写清了「里面有什么」;这里不再维护第二份目录树。
每个子目录「有哪些文档」看 [`docs/README.md`](docs/README.md)(扫描生成,禁止手改)。

---

## 6. 快速开始

**环境准备、后端/前端/网页端的启动与常用命令、出签名包**:[`docs/standards/dev-commands.md`](docs/standards/dev-commands.md)
(前置要求表 + 首次 setup 六步 + 日常命令 + 服务器入口)。
**提交流程、CI 怎么跑、提交信息与 PR 规矩**:[`CONTRIBUTING.md`](CONTRIBUTING.md)。
**推之前必须跑什么**:[`AGENTS.md`](AGENTS.md) §三(唯一入口 `scripts/verify.sh`)。
**发版(版本号 / tag / Release 三件事同时做)**:[`docs/ops/release.md`](docs/ops/release.md)。

> 开发期 `SMS_DEV_MODE=1` 时验证码固定 `123456`,不接短信服务商;`AUTO_APPROVE=1` 时上传照片自动过审。
> 生产环境二者必须关闭,准入由 `accounts.PhoneAllowlist`(运营入口 `/ops/allowlist/`)收口。

---

## 7. 测试与门禁

**验证入口只有 `scripts/verify.sh`**:改后端跑 `scripts/verify.sh backend`,网页端 `web`,imserver `imserver`,
App `app`,只改文档/脚本 `contract` —— 完整对照表在 [`AGENTS.md`](AGENTS.md) §三,门禁清单在
[`scripts/gates.toml`](scripts/gates.toml)(本地与 CI 调**同一个执行器**,两边条数相等)。

**测试形态与各层工具**在 [`docs/architecture.md`](docs/architecture.md) §9「测试形态:真实装配 + 假外部世界」;
违反就会红的硬性约束在 [`AGENTS.md`](AGENTS.md) §四。

---

## 8. 部署、容量与运维

线上形态、nginx 三条硬要求与两个易错点、更新流程:**[`docs/ops/runbook.md`](docs/ops/runbook.md) §10**
(备份与恢复见同文件 §5,准入名单见 §6,告警处置见 §1–§4)。

容量与告警口径的数字只在 [`docs/ops/capacity-and-reliability.md`](docs/ops/capacity-and-reliability.md);
观测栈配置见 [`docs/ops/observability.md`](docs/ops/observability.md)。**部署前必须跑
`python scripts/deploy_gate.py`**(只认合并后 SHA 且该 SHA 的 check 全绿)。

---

## 9. 文档索引

**唯一入口是 [`docs/README.md`](docs/README.md)** —— 它由 `scripts/docs_index.py` 扫描 `docs/`
生成(**禁止手改**;`python scripts/docs_index.py --check` 比对生成物,CI `contract` 轨会拦)。
按目录分组的文档清单、每目录份数、归档份数与归档清单入口都在那里;本节不再维护第二份手写列表,
也不再写任何「N 份 / M 个操作」的手写计数(手写计数必然过期)。

按任务去哪:待办 → [`docs/backlog/`](docs/backlog/2026-11-03-todo.md);交付时间线 →
[`docs/milestones.md`](docs/milestones.md);接口 → [`docs/api/README.md`](docs/api/README.md);
某条事实谁说了算 → [`docs/standards/sources-of-truth.md`](docs/standards/sources-of-truth.md);
写文档的规范 → [`docs/standards/writing.md`](docs/standards/writing.md)。

---

## 10. 许可

以 [MIT](LICENSE) 许可开源。仓库在开源前做过全历史脱敏:服务器地址、口令、个人路径与商业化规划文档
在工作区与全部提交中被统一替换或移除,脚本见 [`tools/sanitize.py`](tools/sanitize.py),规则可复核。
基于本项目部署时,务必自行更换 `SECRET_KEY`、数据库口令与 IM 密钥,并关闭
`DEBUG` / `SMS_DEV_MODE` / `AUTO_APPROVE` 三个开发期开关。

**已知取舍**:照片存储使用本地磁盘(生产建议对象存储 + CDN);无深色模式(v1 列为非目标,避免半成品);
iOS 仅工程层面就绪;**不做离线推送**(服务端保留设备/偏好接口与通道抽象,`PUSH_PROVIDER` 固定 `off`,
客户端不集成推送 SDK,未读状态由站内会话列表承担);备份的异地副本依赖内网设备,尚无对象存储预算。

---

## English Abstract

**chat_app** is a full-stack dating application built as three cooperating processes: a **Flutter** client,
a **Django 5.2 + DRF** business backend, and a **self-hosted C++20 IM server** for long-lived connections.
Business facts live in MySQL behind Django; conversation and message state live in a separate MySQL database
owned by the IM server. The two sides interact only through a signature-verified internal API and asynchronous
tasks, and the request path performs no third-party network calls.

The engineering focus is on **architecture boundaries and enforceable contracts**:

- **Single writer per data domain** — messages are written only by the IM server, business state only by Django,
  so either side can be rolled back independently (image tag / backend SHA).
- **One error envelope** for every non-2xx response (`code` / `message` / `request_id`), with business codes
  derived from HTTP status codes and the request id threaded through logs, metrics and client-side reports.
- **One gateway for IM side effects** (`im/tasks.py`): tasks receive only `user_id`, look up state themselves,
  and never touch request objects; the IM client layers never raise.
- **Contracts as build gates** — human-readable API docs are cross-checked against
  the URLconf, the OpenAPI document is generated from `@extend_schema` annotations and diffed in CI, field-level
  consistency is asserted against client types on both Web and App, and WebSocket frame fixtures are shared by
  all three runtimes so a frame change breaks all three CI tracks at once.
- **Session semantics that survive reordering** — read receipts are single-writer with `GREATEST` semantics,
  so late-arriving frames cannot move a read pointer backwards; clients are monotonic by construction.
- **Cursor pagination and reverse-join exclusions** — opaque keyset cursors keep deep pages independent of depth,
  `NOT EXISTS` replaces growing `IN` lists, and query-count budgets plus index assertions turn regressions into
  CI failures.
- **Observability and capacity as measured artifacts** — Prometheus with multi-process aggregation, alert rules
  routed to email, reproducible load scenarios in `perf/`, and capacity reports that state their measurement
  caveats (a figure measured on a DB-free endpoint does not transfer to authenticated endpoints; both are
  recorded in [`docs/ops/capacity-and-reliability.md`](docs/ops/capacity-and-reliability.md)).
- **Delivery and recovery discipline** — CI workflows gate every merge, release only from the merged
  `origin/main` SHA with a recorded rollback point, three independent backup layers, and a restore drill that
  was actually executed.

Testing follows the same principle: UI tests run the **real provider tree and real router** against scripted
network and fake IM adapters, so they exercise production wiring rather than mocks of it. The repository was
sanitized across its entire commit history before being open-sourced ([`tools/sanitize.py`](tools/sanitize.py)).

Licensed under [MIT](LICENSE).
