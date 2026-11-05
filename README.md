# chat_app · 交友应用全栈工程

> Flutter 客户端 + Django REST 业务后端 + 自建 C++ 长连接服务:三个进程、两个数据库、一套契约。
> **业务事实**(账号、资料、滑卡、配对、广场、举报、推送偏好)留在 Django/MySQL;
> **会话与消息状态**(消息体、序号、已读位点、配对镜像)由 imserver/MySQL 持有。
> 两侧只通过签名内部 API 与异步任务交互,响应路径不出现任何第三方调用。

**在线实例**:<https://chat.shiliu153.cn> —— PC 浏览器进网页端,移动端浏览器进引导页。

[![Backend CI](https://github.com/shiliu153/chatapp/actions/workflows/backend.yml/badge.svg?branch=master)](https://github.com/shiliu153/chatapp/actions/workflows/backend.yml)
[![App CI](https://github.com/shiliu153/chatapp/actions/workflows/app.yml/badge.svg?branch=master)](https://github.com/shiliu153/chatapp/actions/workflows/app.yml)
[![Web CI](https://github.com/shiliu153/chatapp/actions/workflows/web.yml/badge.svg?branch=master)](https://github.com/shiliu153/chatapp/actions/workflows/web.yml)
[![IM Server CI](https://github.com/shiliu153/chatapp/actions/workflows/imserver.yml/badge.svg?branch=master)](https://github.com/shiliu153/chatapp/actions/workflows/imserver.yml)
[![Contract CI](https://github.com/shiliu153/chatapp/actions/workflows/contract.yml/badge.svg?branch=master)](https://github.com/shiliu153/chatapp/actions/workflows/contract.yml)
[![Web E2E](https://github.com/shiliu153/chatapp/actions/workflows/web-e2e.yml/badge.svg?branch=master)](https://github.com/shiliu153/chatapp/actions/workflows/web-e2e.yml)
[![API Docs](https://img.shields.io/badge/API%20docs-51%20operations-blue)](docs/api/README.md)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

**中文** · [English Abstract](#english-abstract)

---

## 目录

- [1. 系统架构](#1-系统架构)
  - [1.1 进程与数据边界](#11-进程与数据边界)
  - [1.2 三条贯穿全栈的约束](#12-三条贯穿全栈的约束)
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
              └────────────┘  (仅「消息落库 + 目标不在线」时回调)
```

| 关注点 | 归属 | 关键约束 |
|---|---|---|
| 账号 / 资料 / 照片 / 滑卡 / 配对 / 广场 / 举报 / 推送偏好 | Django + `chatapp` 库 | 唯一写者;所有对外契约由 `/api/v1` 定义 |
| 会话 / 消息体 / 序号 / 已读位点 / 配对镜像 | imserver + `chatapp_im` 库 | 消息只经 imserver 落库,Django 不写消息表 |
| 跨进程调用方向 | Django → imserver | `im/self_client.py` 调 HMAC 内部 API,签名串 `ts\nMETHOD\npath\nbody`,带时间戳窗口 |
| 反向回调 | imserver → Django | 仅 `POST /internal/push/new-message` 一个入口:同密钥 + 300s 窗口 + 按 `msg_id` 幂等 |
| 身份映射 | 两侧一致 | IM 账号 = `u{user_id}`;JWT 里的 `user_id` claim 是字符串 |

**为什么这样切分**:消息的写入热点在长连接侧,业务事实的写入热点在 REST 侧。把两者放进同一个进程会让
「一条消息落库」与「一次资料更新」争夺同一套事务与连接池;拆开后各自可以独立回滚(回退 imserver 镜像 /
回退后端 SHA),也不必为了聊天吞吐去扩容业务后端。

### 1.2 三条贯穿全栈的约束

1. **响应路径零第三方调用** —— 请求处理过程中不发起任何外部网络调用。所有跨系统副作用
   (IM 建号、发消息、刷头像、系统通知、推送)在 `transaction.on_commit(fn, robust=True)` 中投递 Celery 任务。
   接口耗时因此与 IM / 推送通道的抖动解耦,失败可重试且有独立指标。
2. **IM 副作用唯一出入口 `im/tasks.py`** —— 任务参数只传 `user_id`,任务内部自行查库,任务体内不接触 request 对象;
   `im/client.py`(语义层)与 `im/self_client.py`(传输层)对外永不抛异常,失败以状态位与指标表达。
3. **错误信封唯一形状** —— 失败一律 `{"code": <HTTP 状态码>, "message": "<中文>", "request_id": "..."}`,
   业务码 = 前 3 位 HTTP 状态 + 2 位序号(`config/error_codes.py`);`request_id` 同时写入结构化日志、指标标签与客户端上报。

---

## 2. 关键技术要点

### 2.1 长连接侧的会话状态与消息序号

imserver 是消息的唯一写者:客户端发送经 WS 帧或 `POST /internal/send`,服务端在单个事务内分配会话内自增
`seq`、写入消息体、更新会话摘要,再向收发双方推送下行帧。客户端只依赖 `seq` 做排序与补拉,
离线重连时按本地最大 `seq` 请求增量。连接池对 MySQL `wait_timeout` 做存活探测,
避免空闲连接被服务端回收后 IM 永久失联(`readyz` 探针同源)。

### 2.2 已读回执:单写者语义 + 乱序防护

事实来源是 `im_conversation_state.read_seq`,语义是「**我**读到哪」;对端视角通过会话列表的
`peer_read_seq` 暴露。判定永远是「我方消息 `seq <= peer_read_seq` = 已读」,与「我没读的条数」是两条独立链路,
不可互推。服务端在 `read` 帧落库后**回读实库**再向对端广播,落库用 `GREATEST` 语义 —— 乱序到达的旧帧
不会把已读位点推回去;客户端侧只增不减。`read` 帧单独限流(2/s,突发 30),超限静默丢弃而非报错,
避免用户快速滚动时产生错误反馈。

### 2.3 鉴权:双令牌轮换 + 会话版本绑定

- **JWT 双令牌**:access 30 分钟 / refresh 30 天,刷新即轮换,旧 refresh 进入黑名单;
  网页端 refresh 落 HttpOnly Cookie(响应体不含 refresh),App 落系统安全存储;轮换后保留 60 秒宽限以支持并发标签页。
- **会话版本 `sv`**:IM token 携带 `sv`,imserver 与 `im_user.session_version` 比对,不一致返回 `40101`;
  **WS 握手与 `/im/api/*` 两个入口同口径**,避免「REST 被踢、长连接仍活」的半失效状态。
- **单设备登录**:登录时同步 `session_version` 到 imserver,被顶设备的三条退出路径(REST 401、WS 关闭、刷新失败)互为兜底。
- **两级封禁**:`banned_light` 仅禁滑卡;`banned_heavy` 全域 403。由全局权限类实现,新接口自动继承,
  白名单只有 `GET /users/me`、`GET /users/tags`。

### 2.4 数据访问:游标分页、反连接与查询预算

- **keyset 游标分页**:`config/cursor.py` 以 base64url 编码 `<排序时间>|<主键>` 生成**不透明**游标
  (`?before=`),响应返回 `next_cursor` / `has_more`。排序键带主键兜底,翻页期间有新数据插入也不会重复或漏读;
  深翻页耗时与页深无关。`offset` 参数保留为兼容分支,老版本客户端不因协议升级而卡住。
- **排除列表用 `NOT EXISTS` 反连接**:候选池需要排除「已划过 / 已配对 / 双向拉黑」三类集合,
  原先的 `IN (子查询)` 会随活跃度线性膨胀;改为相关子查询后走索引探测。**必须拆成两次 `exclude`** ——
  `exclude(a, b)` 的语义是 `NOT (a AND b)`,与「不同时满足」并不等价。
- **索引与门禁**:`Match(user_b)`、`Swipe(target, action, -created_at, -id)`、`Photo(status, user_id)`
  三条索引支撑列表与角标查询;`config/test_query_budget.py` 以 `assertNumQueries` 锁定查询条数预算,
  并对「排除必须走 EXISTS」「三条索引必须存在」做断言 —— 查询性能退化会在 CI 阶段暴露,而不是等到线上。

### 2.5 媒体管线:重编码、签名地址与配额

资料图 / 广场图 / 聊天图统一经 `config/images.py`:校验 MIME 与像素上限(≤2000 万像素、长边 4096),
`exif_transpose` 校正方向后**重新编码以剥离 EXIF/GPS**。聊天媒体不出公开 URL,改为限时签名地址
(TTL 默认 3600),由 nginx `auth_request` 子请求 `/im/images/auth` 验签后才放行 —— 直链可撤销、不可枚举。
存储配额按库内 `bytes` 求和(单账号默认 200MB),检查发生在落盘之前,超限返回 `413 + 41301`;
删除与 30 天过期回收都不依赖计数列,避免并发下的漂移。

### 2.6 契约工程:四处生成物 + 四处门禁

接口与协议的「一致性」不靠自觉,而是四个可执行门禁:

| 契约 | 事实来源 | 派生 / 校验 |
|---|---|---|
| HTTP 接口文档 | 视图与序列化器 | `docs/api/`(13 份分册,51 个操作)+ `ApiDocsCoverageTests` 双向比对路由与文档 |
| 机器可读 schema | 视图上的 `@extend_schema` | `docs/api/openapi.yml` 由 `drf-spectacular` 生成(禁止手改),CI 重新生成后 `git diff --exit-code` |
| 字段级一致性 | 文档参数表 ↔ schema 字段 | `config/api_schema_contract.py` 双向比对;Web 侧 `openapi-typescript` 生成 `schema.d.ts` 并对 13 个手写类型做编译期断言;App 侧 `scripts/check_app_models.py` 扫描 `models.dart` 的 JSON 键 |
| WS 帧协议 | `imserver/tests/fixtures/ws/*.json`(上行 8 帧 / 下行 12 帧) | imserver(`frames.h` 序列化)、App、Web 三端各自用真实解析路径消费同一份 fixture,任一端改帧格式三轨同时变红 |

版本号同样收敛到单一来源:`app/pubspec.yaml` 为事实来源,`scripts/sync_version.py --check` 校验
App 常量、Web `package.json` 与关于页测试期望三处一致(CI `contract.yml` 拦截)。

### 2.7 可观测性与容量工程

- **指标**:`prometheus_client` 自建 registry;gunicorn `-w 2` 下必须用 `PROMETHEUS_MULTIPROC_DIR` +
  `MultiProcessCollector`,否则计数器按进程分裂、`rate()` 误判重置。业务指标含
  `logins_total` / `swipes_total` / `matches_total` / `im_calls_total` / `push_sent_total` / `push_skipped_total`。
- **采集**:Prometheus 6 个 target(api / im / node / celery / mysqld / redis),Grafana 概览看板,
  Alertmanager 17 条规则经宿主机 relay 转邮件(与 22:00 服务器日报同一条链路,去重键 `groupKey + status`);
  Loki 作为可选 profile 按需启用。
- **日志**:单行 JSON,字段含 `route` / `status` / `duration_ms` / `request_id`;前端未捕获异常经
  `POST /client-errors` 汇总为同一条日志流与 `client_errors_total{platform}` 指标,两侧 `request_id` 对齐。
- **容量方法学**:`perf/` 是可复现的压测与回归工具(`run.py` + `baseline.json`),覆盖读、写、multipart 上传、
  70/30 混合、WS 重连风暴、0→1000 突发等场景;报告只记录「合成规模 + 合成请求模型」,并明确标注口径。

在 2C2G 单机(含公网 RTT)上的实测基线:

| 场景 | 结果 |
|---|---|
| 极简读接口 `GET /app/config` | 476 rps @100 并发(三次 446–496),0 个 5xx |
| 天花板归因 | 同机裸 WSGI 2626 rps vs Django 478 rps;每请求 Django 2.7ms ⇒ 瓶颈是 2 核上的单请求开销,不是 worker 数 |
| 鉴权读 `GET /users/me` / `GET /discovery/candidates` | 52 / 28.5 rps(候选池冷查询为全表扫 + 4 个反连接) |
| 写 `POST /discovery/swipe` | 饱和约 40 rps,p50 552ms → 4922ms,0 个 5xx / 429 |
| 混合 70 读 / 30 写,30 分钟 | 165.8 rps,期间 swap 换出 +882MB —— 持续高压下的实际稳定吞吐 |
| WS 重连风暴 | 1000 客户端全部恢复,p50 1.67s |

> 口径提醒:476 rps 只对不碰 DB 的极简接口成立;要鉴权、要打库的业务接口是 28–52 rps。
> 两者不可互相推算,这也是「容量报告」里最容易出错的地方。

### 2.8 交付与恢复纪律

- **六条 CI 轨**:backend(MySQL 8 + Redis,含测试与注释/文档门禁)、app(`flutter analyze` 零告警 + 测试)、
  web(`vue-tsc` + `eslint --max-warnings 0` + vitest 覆盖率门槛)、imserver(unit / WS / HTTP 三套)、
  contract(schema 与版本号生成物比对)、web-e2e(真后端 + Playwright 冒烟)。
- **发布只认 `origin/master` 的 SHA**:分支 → PR → CI 全绿 → squash 合并 → 部署合并后的 commit;
  部署前先记回滚点(旧 SHA / 旧镜像 tag / `.env` 备份),禁止把未合并的本地提交直接上线。
- **备份三层**:03:20 自建双库全量(应用库 + IM 库 + 媒体 + 配置,每份带 `.sha256`,并断言 dump 末行
  `-- Dump completed` 以防截断包)、03:30 面板原生备份、04:10 树莓派以只读账号主动拉取;
  保留 14 天,三项均进日报,**恢复演练已实际执行**(干净 MySQL 实例恢复后走完整登录链路)。
- **故障演练**:MySQL 双杀演练两轮,检测延迟 20–24s、MTTR 24.2s / 27.2s,演练本身暴露并修复了
  看门狗锁文件被守护进程继承导致的自我关闭缺陷。

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
| 通知 | 推送设备上报与解绑、四类通知偏好;通道抽象 `off / log / jpush`,imserver 在「消息落库 + 目标不在线」时回调触发 |
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

```
chat_app/
├── app/                        # Flutter 客户端
│   ├── lib/
│   │   ├── core/               #   网络 / 错误映射 / 凭证存储 / 主题 token
│   │   ├── im/                 #   IM 抽象层(测试中以替身替换)
│   │   ├── router.dart         #   go_router 路由表
│   │   └── features/           #   auth onboarding discovery chat square
│   │                           #   profile settings shell presence legal
│   ├── test/                   #   真实 provider + 假网络 + 假 IM(support/)
│   └── assets/fonts/           #   Space Grotesk + OFL 许可
│
├── chatapp/                    # Django 后端
│   ├── config/                 #   settings / 错误契约 / 业务码 / 游标 / 限流 / 指标
│   ├── accounts/               #   自定义 User(手机号为账号)+ JWT + 准入名单 + 探针
│   ├── users/                  #   资料 / 照片 / 标签 / 择偶偏好 / 在线状态
│   ├── discovery/              #   候选池 / 滑卡 / 配对 / 访客
│   ├── im/                     #   IM 凭证签发 / 语义层 / 传输层 / 异步任务(唯一出入口)
│   ├── moderation/             #   举报 / 拉黑 / 封禁
│   ├── ops/                    #   运营审核台(服务端渲染)+ 安全中间件
│   ├── feed/                   #   广场动态
│   ├── notifications/          #   推送设备 / 通知偏好 / 通道抽象 / 内部回调
│   ├── feedback/               #   意见反馈
│   ├── telemetry/              #   客户端错误上报
│   └── .env.example            #   环境变量模板(.env 不入库)
│
├── imserver/                   # 自建 IM(C++20)
│   ├── src/{net,service,store,auth,util}   # 帧编解码 / 业务 / 存储 / 鉴权 / 工具
│   └── tests/                  #   unit + DB + WS/HTTP 集成 + fixtures/ws/(跨栈帧契约)
│
├── web/                        # 网页端(Vue 3 + TS,PC 浏览器)
│   ├── src/{api,stores,im,components,layouts,features,styles}
│   └── tests/                  #   unit / component(vitest + MSW)、e2e(Playwright)
│
├── perf/                       # 压测与回归(run.py / baseline.json / report.py)
├── deploy/                     # 部署模板、可观测栈、运维脚本(备份 / 看门狗 / 演练)
├── scripts/                    # 契约与版本号检查(check_app_models / sync_version)
├── docs/                       # 见「文档索引」
├── .github/workflows/          # 六条 CI 轨
└── CLAUDE.md                   # 工程约束与契约的单一事实来源
```

---

## 6. 快速开始

### 前置要求

| 依赖 | 版本 | 说明 |
|---|---|---|
| Python | 3.11+ | 后端 |
| MySQL | 8.0+ | 业务库(聊天需另建 `chatapp_im`) |
| Redis | 7.x | 验证码 / 限流 / 缓存 / broker,**跑测试与接口前必须先启动** |
| Flutter | 3.47.x | 客户端 |
| imserver | 随仓库构建 | 自建 C++ IM(WS :9100 / HTTP :9101),聊天功能依赖它 |

### 后端

```bash
# 1. 建库与账号(先把脚本里的 <YOUR_DB_PASSWORD> 换成自己的口令)
mysql -u root -p < chatapp/db_setup.sql

# 2. 环境变量
cd chatapp
cp .env.example .env
#    至少填 SECRET_KEY / DB_PASSWORD / IM_SELF_SECRET / IM_SELF_INTERNAL_SECRET / IM_MEDIA_PREFIX
#    SECRET_KEY 可用: python -c "import secrets;print(secrets.token_urlsafe(50))"

# 3. 依赖(生产与 CI 一律用锁定文件)
pip install -r requirements.lock

# 4. Redis
docker compose -f docker-compose.dev.yml up -d

# 5. 迁移与管理员
python manage.py migrate
python manage.py createsuperuser

# 6. 启动
python manage.py runserver          # http://127.0.0.1:8000
```

需要真实收发消息时,另起 Celery worker(Windows 仅支持 `solo` 池):

```bash
python -m celery -A config worker -l info --pool=solo
```

开发期常用命令:

```bash
python manage.py test                          # 全量测试(前置:Redis 在跑)
python manage.py test accounts                 # 单 app
python manage.py seed_fake_users --count 20    # 造数(幂等)
python manage.py im_send --from u2 --to u3 --text "你好"   # 代发消息(--notice 发灰条)
python manage.py dev_reset_pair --a u8 --b u9              # 重演配对(不清聊天记录)
```

> 开发期 `SMS_DEV_MODE=1`,验证码固定 `123456`,不接短信服务商;`AUTO_APPROVE=1` 时上传照片自动过审。
> 生产环境二者必须关闭,准入由 `accounts.PhoneAllowlist`(运营入口 `/ops/allowlist/`)收口。

### 客户端

```bash
cd app
flutter pub get

flutter run --dart-define=API_BASE=http://127.0.0.1:8000/api/v1          # 桌面 / 浏览器
flutter run -d emulator-5554 --dart-define=API_BASE=http://10.0.2.2:8000/api/v1   # Android 模拟器
```

签名包(需自备 keystore,`app/android/key.properties` 不入库):

```bash
flutter build apk --release \
  --dart-define=API_BASE=https://your-domain/api/v1 \
  --dart-define=ERROR_REPORTING=true
```

`ERROR_REPORTING=true` 必须携带,否则线上崩溃与白屏不会进入上报链路(Web 侧对应 `VITE_ERROR_REPORTING=1`)。

### 网页端

```bash
cd web
npm ci
npm run dev        # 代理到 :8000
npm run build      # 产物 web/dist
```

---

## 7. 测试与门禁

测试形态的取舍是「**真实装配 + 假外部世界**」:UI 测试运行真实的 Riverpod provider 树与真实路由,
只把网络与 IM 替换为可控替身,因此测到的是生产装配而不是 mock 的装配。

| 层 | 工具与形态 | 门禁 |
|---|---|---|
| 后端 | `manage.py test`,791 个用例;IM 副作用一律 mock(`im.tasks.*.delay`),并发正确性用唯一约束 + `CheckConstraint` 覆盖 | 全量绿 + 查询预算 + 注释覆盖 + 接口文档双向比对 + schema 字段级比对 |
| 客户端 | `flutter test`;`test/support/` 提供脚本化假网络、假 IM 客户端与 `pumpApp` 组合入口 | `flutter analyze` 零告警 + 全绿 |
| 网页端 | vitest + MSW(组件与 store 真实);Playwright 端到端跑构建产物 | `vue-tsc` 零错误 + `eslint --max-warnings 0` + 覆盖率门槛 70/60/70/70 |
| 长连接 | imserver unit / DB / WS / HTTP 四套;跨栈帧 fixture 三端共享 | 三轨 CI 各自校验同一份 fixture |
| 端到端 | 冒烟场景进 CI(真 MySQL + Redis + Django + preview);全量场景需 imserver + Celery,本地执行 | 失败上传 Playwright 报告 |

关键业务不依赖人工点击:配对并发、限流窗口、验证码锁定、封禁分级、单设备登录的三条退出路径、
已读回执的乱序防护、游标分页的翻页一致性,都有对应用例。

---

## 8. 部署、容量与运维

线上形态为单机多进程(容量实测即在该配置上完成):

```
用户 → nginx(443/80,TLS 终止 + 静态直出 + 反代)
        ├→ gunicorn 127.0.0.1:8000 (gthread)
        │    └→ Django ── MySQL 8(chatapp)/ Redis 7(DB0 缓存、DB1 broker)── Celery
        └→ imserver 127.0.0.1:9100 WS / 9101 HTTP
             ├→ MySQL 8(chatapp_im)
             └→ Redis 7(DB2)
```

nginx 的三条硬要求与两个易错点:

1. **深链回退**:`try_files $uri $uri/ /index.html;` —— vue-router 使用 history 模式,缺了它刷新与直接访问深链都会 404;
2. **反代 `/api/v1/`、`/im/ws`、`/media/`**:网页端与接口同源,因此不需要 CORS;
3. **`index.html` 不缓存**,带内容哈希的 js/css 反而应长缓存。

> 易错点:① `/media/` 直出需逐站点配置,漏配表现为照片 404;
> ② 面板生成的 `proxy_cache` 键不含 `Authorization` 且忽略 `Vary`,会造成跨用户缓存泄漏 ——
> 要么关闭页面缓存,要么把 `Authorization` 纳入 `proxy_cache_key`。

**更新流程**:`git fetch` 确认落点 SHA → 记回滚点 → `git reset --hard <sha>` → 装依赖 → `migrate` →
`collectstatic` → 重启 web 与 worker → 生产冒烟。IM 侧按 `docs/ops/imserver.md` 执行镜像替换与 `readyz` 校验。
容量、告警、故障处置与恢复步骤分别见 `docs/ops/capacity-and-reliability.md` 与 `docs/ops/runbook.md`。

---

## 9. 文档索引

| 文档 | 内容 |
|---|---|
| [`docs/api/`](docs/api/README.md) | 对外交付级接口文档:13 份分册 / 51 个操作 + `openapi.yml` 机器可读契约 |
| [`docs/ops/`](docs/ops/) | 运维与容量:imserver 协议、runbook、容量与可靠性、压测与基线报告、推送契约 |
| [`docs/pitfalls/`](docs/pitfalls/README.md) | 踩坑手册,按 IM / 前端 / 后端 / 测试 / 网页端 / 模拟器分册 |
| [`docs/milestones.md`](docs/milestones.md) | 里程碑时间线(每次交付的改动、PR 号与上线 SHA) |
| [`docs/superpowers/`](docs/superpowers/README.md) | 设计 spec 与实施计划:工作面 1 份,已交付 85 份归档于 `archive/` |
| [`docs/backlog/2026-11-03-todo.md`](docs/backlog/2026-11-03-todo.md) | 待办总表:A–E 五批已闭环,剩余未闭环项见 §7 |
| [`docs/reviews/`](docs/reviews/2026-11-03-fullstack-review.md) · [`docs/security/`](docs/security/) | 全栈工程审查与三轮安全审计报告 |
| [`docs/standards/python.md`](docs/standards/python.md) | Python 注释规范(由 `CommentCoverageTests` 强制) |
| [`CLAUDE.md`](CLAUDE.md) | 工程约束、契约与纪律的单一事实来源 |

---

## 10. 许可

以 [MIT](LICENSE) 许可开源。仓库在开源前做过全历史脱敏:服务器地址、口令、个人路径与商业化规划文档
在工作区与全部提交中被统一替换或移除,脚本见 [`tools/sanitize.py`](tools/sanitize.py),规则可复核。
基于本项目部署时,务必自行更换 `SECRET_KEY`、数据库口令与 IM 密钥,并关闭
`DEBUG` / `SMS_DEV_MODE` / `AUTO_APPROVE` 三个开发期开关。

**已知取舍**:照片存储使用本地磁盘(生产建议对象存储 + CDN);无深色模式(v1 列为非目标,避免半成品);
iOS 仅工程层面就绪;App 端推送客户端未接入(后端链路与通道抽象已就绪,待推送服务商凭据);
备份的异地副本依赖内网设备,尚无对象存储预算。

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
- **Contracts as build gates** — human-readable API docs (13 volumes, 51 operations) are cross-checked against
  the URLconf, the OpenAPI document is generated from `@extend_schema` annotations and diffed in CI, field-level
  consistency is asserted against client types on both Web and App, and WebSocket frame fixtures are shared by
  all three runtimes so a frame change breaks all three CI tracks at once.
- **Session semantics that survive reordering** — read receipts are single-writer with `GREATEST` semantics,
  so late-arriving frames cannot move a read pointer backwards; clients are monotonic by construction.
- **Cursor pagination and reverse-join exclusions** — opaque keyset cursors keep deep pages independent of depth,
  `NOT EXISTS` replaces growing `IN` lists, and query-count budgets plus index assertions turn regressions into
  CI failures.
- **Observability and capacity as measured artifacts** — Prometheus with multi-process aggregation, 17 alert rules
  routed to email, reproducible load scenarios in `perf/`, and capacity reports that state their measurement
  caveats (a 476 rps figure applies only to a DB-free endpoint; authenticated endpoints measure 28–52 rps on 2C2G).
- **Delivery and recovery discipline** — six CI tracks, release only from the merged `origin/master` SHA with a
  recorded rollback point, three independent backup layers, and a restore drill that was actually executed.

Testing follows the same principle: UI tests run the **real provider tree and real router** against scripted
network and fake IM adapters, so they exercise production wiring rather than mocks of it. The repository was
sanitized across its entire commit history before being open-sourced ([`tools/sanitize.py`](tools/sanitize.py)).

Licensed under [MIT](LICENSE).
