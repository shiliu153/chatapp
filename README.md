# chat_app · 交友应用全栈项目

> 一个从零到可上线的交友 App:Flutter 客户端 + Django REST 后端,聊天走腾讯云 IM,
> 后端全栈自建(鉴权 / 滑卡配对 / 广场 / 举报拉黑 / 运营审核台 / 在线状态)。
> 全程按 **spec → plan → 实现 → 验收** 的节奏推进,每个阶段都有可回溯的设计文档与实施计划。

[![Backend CI](https://github.com/yourname/chatapp/actions/workflows/backend.yml/badge.svg?branch=master)](../../actions/workflows/backend.yml)
[![App CI](https://github.com/yourname/chatapp/actions/workflows/app.yml/badge.svg?branch=master)](../../actions/workflows/app.yml)
[![Backend Tests](https://img.shields.io/badge/backend%20tests-337%20passed-brightgreen)](#测试策略)
[![Flutter Tests](https://img.shields.io/badge/flutter%20tests-247%20passed-brightgreen)](#测试策略)
[![Flutter Analyze](https://img.shields.io/badge/flutter%20analyze-0%20issues-brightgreen)](#测试策略)
[![API Docs](https://img.shields.io/badge/API%20docs-32%20endpoints-blue)](docs/api/README.md)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

<sub>测试徽章数字为交付时的实测值:后端 `Ran 337 tests ... OK` · Flutter `All tests passed! (+247)` · `flutter analyze` No issues found</sub>

**中文** · [English Abstract](#english-abstract)

---

## 目录

- [项目概览](#项目概览)
- [功能一览](#功能一览)
- [技术栈与选型理由](#技术栈与选型理由)
- [系统架构](#系统架构)
- [快速开始](#快速开始)
  - [后端(Django)](#后端django)
  - [前端(Flutter)](#前端flutter)
- [测试策略](#测试策略)
- [接口文档](#接口文档)
- [UI 设计语言:心跳](#ui-设计语言心跳)
- [目录结构](#目录结构)
- [开发历程](#开发历程)
- [工程约束:几条刻意定下的硬规则](#工程约束几条刻意定下的硬规则)
- [部署](#部署)
- [开源说明与后续规划](#开源说明与后续规划)
- [English Abstract](#english-abstract)

---

## 项目概览

这是一个**双端齐全、业务流程闭环**的交友类应用,不是课程作业式的 Demo:从手机号验证码登录、
资料完善、滑卡发现、互相喜欢配对,到基于腾讯云 IM 的实时聊天、朋友圈式的广场动态,
再到面向运营侧的举报处理与封禁审核台,链路都跑通过、并在真实服务器上部署验证过。

| 维度 | 规模 |
|---|---|
| 后端 | Django 5.2 LTS + DRF,8 个业务 app,约 **8.0k 行 Python** |
| 前端 | Flutter 3.47,11 个 feature 模块,约 **8.8k 行 Dart** |
| 测试 | **337** 个后端用例 + **247** 个 Flutter 用例(63 个测试文件),测试代码约 **8.5k 行** |
| 接口 | **32** 个 REST 接口,配 **10 册**对外交付级接口文档 |
| 文档 | 设计 spec + 实施计划 + 踩坑手册共 **50+ 篇** |

**为什么值得一看**:除了功能本身,这个项目里比较少见的是
**「约束先于代码」**——错误契约、IM 副作用的唯一出入口、单设备登录、封禁分级、
以及「改接口必须同一次改动内改文档」的 CI 级门禁,都是先写成规则再落到代码和测试里的。

---

## 功能一览

### 账号与认证
- **手机号 + 短信验证码**登录,未注册自动建号;开发期验证码固定 `123456`(`SMS_DEV_MODE=1`)
- **JWT 双令牌**:access 30 分钟 / refresh 30 天,**刷新即轮换**,旧 refresh 立即进黑名单
- **单设备登录**:同一账号只允许一台设备在线,被顶设备收到 `401 + 40101`,客户端清凭证回登录页
- 发送频率限制(同号 60 秒)、连错锁定(5 次锁 15 分钟)、60 秒幂等重放窗口

### 资料与偏好
- 昵称 / 性别 / 生日 / 城市 / 简介 + 12 个兴趣标签;未满 18 岁直接 `400`
- 照片上传(最多 6 张、≤5MB),带审核状态;资料「完善度」由后端判定并返回缺项
- 择偶偏好:目标性别(可空=不限)/ 年龄区间 / 城市

### 发现与配对
- 候选卡按偏好过滤,自动排除自己 / 划过 / 已配对 / 资料未完善者,**只推有已过审照片的人**
- 滑卡动作幂等;**互相喜欢 → 配对成功**,事务提交后给双方各发一条系统消息(聊天页渲染为居中灰条)
- 滑卡限流 300 次/小时;配对列表分页并预热昵称头像缓存

### 聊天(腾讯云 IM)
- 消息链路走腾讯云 IM,业务数据存 Django;后端签发 userSig
- 会话列表四态(骨架 / 空态 / 错误重试 / 正常)、最近联系人横滑条、系统通知置顶
- 聊天页:气泡、时间条(间隔 > 5 分钟插入)、表情面板、发图、长按菜单、失败重发
- 昵称与头像变更同步到 IM(照片过审后异步刷头像)

### 广场 / 在线状态 / 合规
- 广场动态流:发布、点赞、评论
- **在线状态是公开信息**(不依赖配对):120 秒内有认证请求即视为在线(客户端 45 秒心跳)
- 举报与拉黑;两级封禁:`banned_light` 只禁滑卡,`banned_heavy` 全域 `403`(全局权限类自动覆盖新接口)
- **运营审核台**:举报队列、照片审核、封禁操作(服务端渲染页面,浏览器直接登录使用)
- 合规:用户协议 / 隐私政策弹窗、年龄门槛

---

## 技术栈与选型理由

| 层 | 选型 | 为什么是它 |
|---|---|---|
| 客户端 | **Flutter 3.47** | 一套代码出双端;自定义 UI 密度高("心跳"设计语言),Flutter 的绘制控制力比 WebView 方案更合适 |
| 状态管理 | **Riverpod** | 编译期安全、无需 BuildContext、provider 之间可组合;测试时能直接覆写依赖(见测试策略) |
| 路由 | **go_router** | 声明式路由表,深链与重定向(未登录→登录页)集中在一处可读 |
| 网络 | **dio** + 自定义 Interceptor | 401 统一走刷新通道,是单设备登录能落地的前提 |
| 后端 | **Django 5.2 LTS + DRF** | LTS 保证长期维护;自带 admin/ORM/迁移,合规侧(审核台)可以直接借用 admin 的鉴权体系 |
| 数据库 | **MySQL 8** | 生产常见选择;需要唯一约束 + CheckConstraint 来保证配对幂等与并发正确性 |
| 缓存 / 队列 | **Redis 7** + **Celery** | 验证码、限流走 Redis;所有跨系统副作用走 Celery,保证响应路径零第三方网络调用 |
| 聊天 | **腾讯云 IM** | 自建长连接的成本远高于接入成熟 SDK;但**业务数据仍全部留在自己的库**里,IM 只做消息通道 |
| 部署 | 阿里云轻量 + 宝塔面板 + gunicorn + nginx | 2C2G 小机器全托管;容量实测见下方[部署](#部署)一节 |

---

## 系统架构

```
┌──────────────────────────────────────────────────────────────┐
│  Flutter App (app/)                                          │
│  features/{auth,onboarding,discovery,chat,square,profile,…}   │
│  Riverpod providers ── dio ── AuthInterceptor(401 刷新通道)   │
└───────────────┬──────────────────────────┬───────────────────┘
                │ HTTPS /api/v1            │ 长连接(消息)
                ▼                          ▼
┌───────────────────────────────┐   ┌──────────────────────────┐
│  Django + DRF (chatapp/)      │   │  腾讯云 IM               │
│  config/  统一错误契约 · 鉴权  │   │  userSig 由后端签发       │
│  accounts users discovery     │   │  账号 = u{user_id}        │
│  im moderation ops feed …     │   └──────────────────────────┘
│                               │              ▲
│  响应路径禁止第三方网络调用    │              │ Celery 任务(唯一出入口)
└───┬───────────┬───────────────┘──────────────┘
    │           │
    ▼           ▼
┌────────┐  ┌────────┐
│ MySQL8 │  │ Redis7 │  ← 验证码 / 限流 / 缓存 / Celery broker
└────────┘  └────────┘
```

**三条贯穿全栈的设计约束**(细节见[工程约束](#工程约束几条刻意定下的硬规则)):

1. **响应路径零第三方调用** —— 请求处理过程中不出现 `requests` 调用外部服务;
   所有跨系统副作用(IM 建号、发消息、刷头像、发系统通知)一律通过 `transaction.on_commit`
   投递到 Celery 任务。好处是接口响应时间不受第三方抖动影响,失败可重试。
2. **IM 副作用唯一出入口 `im/tasks.py`** —— 任务参数只传 `user_id`,任务内部自己查库,
   任务体里不碰 request 对象;`im/client.py` 对外永不抛异常。
3. **错误契约唯一形状** —— 失败一律 `{"code", "message", "request_id"}`,
   业务码前 3 位等于 HTTP 状态码、后 2 位为序号(`config/error_codes.py`)。

---

## 快速开始

### 前置要求

| 依赖 | 版本 | 说明 |
|---|---|---|
| Python | 3.11+ | 后端 |
| MySQL | 8.0+ | 业务库 |
| Redis | 7.x | **跑测试和接口前必须先起**,否则验证码/限流用例会失败 |
| Flutter | 3.47.x | 客户端 |
| 腾讯云 IM | 体验版即可 | 需要一个 SDKAppID;聊天功能依赖它 |

### 后端(Django)

```bash
# 1. 建库与账号(先把脚本里的 <YOUR_DB_PASSWORD> 换成你自己的口令)
mysql -u root -p < chatapp/db_setup.sql

# 2. 配置环境变量
cd chatapp
cp .env.example .env
#    至少填: SECRET_KEY / DB_PASSWORD / IM_SDKAPPID / IM_SECRETKEY
#    SECRET_KEY 可用: python -c "import secrets;print(secrets.token_urlsafe(50))"

# 3. 装依赖(建议用虚拟环境)
pip install -r requirements.txt

# 4. 起 Redis(仓库自带 compose 文件)
docker compose -f docker-compose.dev.yml up -d

# 5. 迁移 + 建管理员
python manage.py migrate
python manage.py createsuperuser

# 6. 启动
python manage.py runserver          # http://127.0.0.1:8000
```

需要 IM 真实收发消息时,再起一个 Celery worker(Windows 只能 `solo` 池):

```bash
python -m celery -A config worker -l info --pool=solo
```

**开发期常用命令**:

```bash
python manage.py test                          # 全量测试(前置:Redis 在跑)
python manage.py test accounts                 # 只跑某个 app
python manage.py seed_fake_users --count 20    # 造测试用户(幂等)
python manage.py im_send --from u2 --to u3 --text "你好"    # 代发消息(--notice 发灰条)
python manage.py dev_reset_pair --a u8 --b u9               # 重演配对(不清聊天记录)
```

> 开发期 `SMS_DEV_MODE=1`,验证码固定 **`123456`**,不需要接真实短信服务商。
> `AUTO_APPROVE=1` 时上传的照片自动过审,方便本地联调。

### 前端(Flutter)

```bash
cd app
flutter pub get

# 浏览器 / 桌面调试(后端在本机)
flutter run --dart-define=API_BASE=http://127.0.0.1:8000/api/v1

# Android 模拟器(10.0.2.2 是模拟器里指向宿主机的地址)
flutter run -d emulator-5554 --dart-define=API_BASE=http://10.0.2.2:8000/api/v1
```

出签名包(需要自备 keystore,`app/android/key.properties` **不入库**):

```bash
flutter build apk --release --dart-define=API_BASE=https://your-domain/api/v1
# 产物: app/build/app/outputs/flutter-apk/app-release.apk
```

---

## 测试策略

**后端**:`python manage.py test` —— **337 个用例全绿**(需要 Redis 在跑)。
关键业务不靠人工点:配对并发(唯一约束 + CheckConstraint)、限流窗口、
验证码锁定、封禁分级、单设备登录的三条退出路径,都有对应用例。
所有 IM 副作用一律 mock(`im.tasks.*.delay`),测试不依赖腾讯云。

**前端**:`flutter test` —— **247 个用例全绿**,分布在 63 个测试文件里。
测试形态是 **「真实 provider + 假网络 + 假 IM」**:

| 替身 | 文件 | 作用 |
|---|---|---|
| 假网络 | `test/support/scripted_adapter.dart` | 按脚本返回响应,可注入延迟/错误 |
| 假 IM | `test/support/fake_im_client.dart` | 记录调用流水(`init:` / `login:` / `send:`),不发真实消息 |
| 组合入口 | `test/support/harness.dart` 的 `pumpApp` | 一次调用就把 App 挂起来,provider 依赖被覆写 |

也就是说 UI 测试跑的是**真实的 Riverpod provider 树和真实的路由**,只把外部世界换成假的——
这样测出来的行为才和线上一致,而不是测了一堆 mock。

**质量门禁**:`flutter analyze` 必须零告警;后端全量测试必须绿。

---

## 接口文档

[`docs/api/`](docs/api/README.md) 是**对外交付级**的接口文档,结构参照腾讯云 API 文档:
每个接口含功能说明、请求/响应参数表、请求与响应示例(取自真实响应)、可能出现的错误码。

| 分册 | 内容 |
|---|---|
| [conventions.md](docs/api/conventions.md) | Base URL、请求约定、鉴权、响应结构、分页、时间格式、限流 |
| [errors.md](docs/api/errors.md) | 错误码总表、HTTP 语义、封禁行为 |
| [auth.md](docs/api/auth.md) | 账号与鉴权 |
| [users.md](docs/api/users.md) | 资料 / 照片 / 择偶偏好 / 标签 / 他人资料 / 在线状态 |
| [discovery.md](docs/api/discovery.md) | 发现与配对 |
| [moderation.md](docs/api/moderation.md) | 举报与拉黑 |
| [feed.md](docs/api/feed.md) | 广场动态 |
| [im.md](docs/api/im.md) | IM 会话凭证 |
| [health.md](docs/api/health.md) | 运维探针 |

**文档不会过期**:测试里有一个 `ApiDocsCoverageTests`,双向比对「实际注册的路由」与
「文档里列出的接口」——**增删改任何一个接口却忘了改文档,测试直接红**。

---

## UI 设计语言:心跳

客户端 UI 不是随手堆的,有一份成文的、强制的设计规则
([完整文档](docs/superpowers/specs/2026-09-15-ui-design-language-design.md)),核心是三条铁律:

1. **一屏一个高音** —— 品牌粉 `#FF2C55` 与"心跳渐变"(粉 → 橙)只出现在引导视线处
   (主按钮 / 选中态 / 未读角标 / 配对时刻 / 在线光),其余全部走三级中性色阶。
   「不单调」靠让颜色出现在该出现的位置,不靠到处加颜色。
2. **动效服务反馈与情感,不做装饰** —— 每个动效要么回答"我的操作生效了吗",
   要么放大一个情感时刻;两者之外不做,并尊重系统的"减弱动态效果"。
3. **一切走 token** —— 色板 / 渐变 / 字阶 / 圆角 / 间距 / 动效时长全部从 token 取值,
   新代码禁止出现裸 hex、裸字号、裸间距。

字体为 **Space Grotesk**(拉丁与数字)+ 中文系统字体回退,字体文件与 OFL 许可已随仓库提供;
图标统一使用 Material 的 `*_rounded` 变体。

---

## 目录结构

```
chat_app/
├── app/                        # Flutter 客户端
│   ├── lib/
│   │   ├── core/               #   网络 / 错误映射 / 凭证存储
│   │   ├── im/                 #   IM 抽象层(可被测试替身替换)
│   │   ├── router.dart         #   go_router 路由表
│   │   └── features/           #   auth onboarding discovery chat
│   │                           #   square profile moderation presence settings shell legal
│   ├── test/                   #   63 个测试文件 + support/(假网络、假 IM、harness)
│   └── assets/fonts/           #   Space Grotesk + OFL 许可
│
├── chatapp/                    # Django 后端
│   ├── config/                 #   项目包:settings / 统一错误契约 / 业务码 / 限流
│   ├── accounts/               #   自定义 User(以手机号为账号)+ JWT
│   ├── users/                  #   资料 / 照片 / 标签 / 择偶偏好 / 在线状态
│   ├── discovery/              #   候选卡 / 滑卡 / 配对
│   ├── im/                     #   userSig 签发 / REST 客户端 / 异步任务(唯一出入口)
│   ├── moderation/             #   举报 / 拉黑 / 封禁
│   ├── ops/                    #   运营审核台(服务端渲染)
│   ├── feed/                   #   广场动态
│   ├── notifications/          #   系统通知
│   ├── db_setup.sql            #   本地建库脚本
│   └── .env.example            #   环境变量模板(.env 不入库)
│
├── docs/
│   ├── api/                    #   对外交付级接口文档(10 册 / 32 接口)
│   ├── pitfalls/               #   踩坑手册(按主题分册)
│   └── superpowers/
│       ├── specs/              #   设计文档(先定规则再写代码)
│       └── plans/              #   实施计划(带 checkbox,进度以文件为准)
│
├── tools/sanitize.py           #   开源前的隐私脱敏脚本(工作区与 git 历史同源规则)
├── CLAUDE.md                   #   给 AI 协作者的项目上下文与硬性纪律
└── LICENSE
```

---

## 开发历程

项目按里程碑推进,**每个里程碑都先有一份设计 spec,再有一份带 checkbox 的实施计划**,
交付后把实际踩到的坑沉淀进踩坑手册。进度以 `docs/superpowers/{specs,plans}/` 里的文件为准。

| 阶段 | 内容 |
|---|---|
| **M0** | 地基:Django 项目骨架 + 自定义 User + Flutter 工程 + 双端 `/health` 打通 |
| **M1** | 后端全量(认证 / 资料 / 照片 / 偏好)+ IM 接入(userSig 签发、REST 客户端) |
| **M2** | 前端全量:登录 → 引导 → 卡片 → 配对 → IM 聊天,主链路闭环 |
| **M3** | 合规:审核台 / 举报拉黑 / 两级封禁 / 协议弹窗 / 签名 APK |
| **后续七次追加** | 运营审核台 UI · 封禁系统消息 + 消息页改版 · 微信式聊天与资料页(IM 昵称同步) · 单设备登录与造数 · 举报处理通知 · 广场动态流 · 自建在线状态 |
| **UI 整改** | 「心跳」设计语言 v1 立项,分批改造:① 底座 + 底栏 → ② 发现页 → ③ 消息 / 聊天(均已交付) |
| **M4** | 真机部署:宝塔全托管跑通,双模拟器手测通过;容量实测与调优 |
| **文档体系** | 接口文档十册 + 双向门禁;踩坑手册按主题分册 |

---

## 工程约束:几条刻意定下的硬规则

这些规则写在 [`CLAUDE.md`](CLAUDE.md) 里,是项目能保持一致的真正原因,也是我认为最值得看的部分。

| 规则 | 为什么 |
|---|---|
| **响应路径禁止任何第三方网络调用** | 接口耗时不受 IM / 短信商抖动影响;副作用失败可重试、可观测 |
| **跨系统副作用唯一入口 `im/tasks.py`** | 任务只收 `user_id`、内部自己查库,不在任务里碰 request;`im/client.py` 对外永不抛异常 |
| **`.env` 禁用 `CELERY_` 前缀键**(用 `BROKER_URL`) | 避免与 Celery 自身配置命名空间冲突导致的静默覆盖 |
| **错误契约唯一形状** | 客户端只需实现一套错误处理;`request_id` 贯穿日志便于排查 |
| **单设备登录三条退出路径互为兜底** | 被顶设备可能在任何时刻发请求,靠单一机制必然漏 |
| **封禁分级 + 全局权限类** | 新增接口自动继承封禁语义,不用逐个记得加判断 |
| **改接口必须同一次改动内改文档** | 由 `ApiDocsCoverageTests` 强制,而不是靠自觉 |
| **IM 副作用一律 mock** | 测试不依赖外部服务,本地随时可跑全量 |
| **每步全绿再进下一步** | 后端全量绿 + `flutter analyze` 零告警才算完成 |

---

## 部署

线上形态(小规模单机,够用且便宜):

```
用户 → nginx(443/80,静态直出 + 反代)
        └→ gunicorn (127.0.0.1:8000, gthread)
             └→ Django ── MySQL 8 (本机)
                       └─ Redis 7 (DB0 缓存 / DB1 队列) ── Celery worker
```

容量实测(阿里云轻量 2C2G,含公网 RTT):

| 接口 | 延迟平稳区 | 饱和吞吐 |
|---|---|---|
| `GET /readyz`(最轻) | 并发 ≤ 40 | ~200 req/s |
| `GET /users/me`(登录态实读) | 并发 ≤ 10–20 | ~53 req/s |

折算混合流量约可支撑 **300–500 同时在线**。聊天的消息链路走腾讯云 IM 直连,
不占本机资源;**真正吃 CPU 的是刷卡片和广场**。当时的结论是"瓶颈已经从 worker 数
转为 CPU 核数"——再加线程无用,要提容量得升配或降单请求开销。

> 具体服务器地址、面板端口与运维命令属于部署私有信息,已从本开源仓库移除。
> 更新流程本身很简单:`git pull` → 装依赖 → `migrate` → `collectstatic` → 重启 web 与 worker 两条进程。

---

## 开源说明与后续规划

### 隐私处理

本仓库在开源前做过一次**全历史清洗**,不是只改当前文件:

- 服务器 IP、个人域名、数据库口令、个人目录路径、SSH 私钥路径等字面量
  在工作区**与全部 296 个提交**里统一替换为占位符(`<SERVER_IP>` / `example.com` / `C:/Users/you` …);
- 服务器私有的运维手册、以及含商业化与资质规划的文档已从仓库移出;
- 提交邮箱统一为 GitHub noreply 地址;
- 清洗脚本保留在 [`tools/sanitize.py`](tools/sanitize.py),规则可复核、可复现。

**如果你要基于本项目部署,务必自行更换**:`SECRET_KEY`、数据库口令、腾讯云 IM 密钥,
并关闭 `DEBUG` / `SMS_DEV_MODE` / `AUTO_APPROVE` 这些开发期开关。

### 已知取舍

- **无深色模式**:v1 明确列为非目标,不做双主题预埋(避免半成品)。
- **照片存储用本地磁盘**:生产环境应换成对象存储 + CDN。
- **内容安全与短信未接真实服务商**:当前用 `AUTO_APPROVE` / `SMS_DEV_MODE` 开关走开发路径。
- **iOS 仅在工程层面就绪**:未做真机签名与商店适配,验证均在 Android 上完成。

### 可能继续做的方向

- [ ] 深色模式(按 v1 的设计规则扩展 token,而不是另起一套)
- [ ] 照片对象存储 + CDN,替换本地磁盘
- [ ] 接入真实短信服务商与内容安全审核
- [ ] 广场动态的评论楼中楼与 @ 提醒
- [ ] 客户端接入推送(离线消息)

### 许可与协作

本项目以 [MIT](LICENSE) 许可开源,可自由学习与二次开发。
Issue 与 PR 都欢迎;提交前请确认后端测试全绿、`flutter analyze` 零告警。

---

## English Abstract

**chat_app** is a full-stack dating application built as a complete, deployable product rather
than a toy demo: a **Flutter 3.47** client and a **Django 5.2 + DRF** backend, with real-time
messaging delegated to **Tencent Cloud IM** while all business data stays in **MySQL 8**
(cache and async jobs on **Redis 7 + Celery**).

The feature set covers the full loop — phone/SMS authentication with rotating JWT pairs and
**single-device login**, profile and photo management, swipe-based discovery with **mutual-like
matching**, 1-on-1 chat, a social feed, reporting/blocking, a two-tier ban system, a
server-rendered **operations console** for moderation, and a self-built **presence** service.
It is documented as **32 REST endpoints across 10 API reference volumes**.

What distinguishes the project is its emphasis on **constraints before code**. A few rules are
enforced across the whole stack and backed by tests:

- **No third-party network calls on the response path** — every cross-system side effect goes
  through Celery tasks dispatched via `transaction.on_commit`.
- **A single gateway for IM side effects** (`im/tasks.py`), keeping tasks request-free and
  `im/client.py` exception-free.
- **One error envelope** for every non-2xx response, with business codes derived from HTTP
  status codes and a `request_id` for tracing.
- **API documentation that cannot rot** — a `ApiDocsCoverageTests` test cross-checks registered
  routes against the docs in both directions, so forgetting to update the docs fails the build.
- **UI as a written design language** ("Heartbeat"): a token-only palette/type/spacing system
  where the brand pink and gradient are rationed to one focal point per screen.

Testing follows the same philosophy: **~8.5k lines of tests** (337 backend cases, 247 Flutter cases
across 63 test files) where UI tests run the **real Riverpod provider tree and real router** against
fake network and fake IM adapters — so the tests exercise production wiring, not mocks of it.

The repository was sanitized before being open-sourced: server addresses, credentials, personal
paths and business-planning documents were replaced or removed across the **entire commit
history** by a reproducible script ([`tools/sanitize.py`](tools/sanitize.py)).

Licensed under [MIT](LICENSE).
