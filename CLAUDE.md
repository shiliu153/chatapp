# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概况

交友软件(dating app)全栈项目,技术栈:

- **前端**: Flutter(`app/`,包名 `chatapp_app`,Flutter 3.47.2)
- **后端**: Django 5.2 LTS + DRF(`chatapp/`,MySQL 8 + Redis + Celery)
- **聊天**: 自建 C++ IM(`imserver/`,唯一后端;腾讯云 IM 分支已于 2026-11-08 删除)
- **部署**: 阿里云轻量 2C2G + 宝塔全托管(`https://chat.shiliu153.cn`,HTTPS 2026-10-28 上线)

用户以中文交流,回复请使用中文。用户是 **Flutter/Django 新手**,偏好教学式、分步、带"为什么"的讲解。

## 文档导航(按需读取,别在本文堆细节)

| 想知道 | 去哪 |
|---|---|
| **全部文档清单(唯一入口)** | [docs/README.md](docs/README.md) —— 由 `scripts/docs_index.py` 扫描生成,**禁止手改**;本表只留「按任务去哪」,不再维护第二份清单 |
| **现在该做什么** | [docs/backlog/2026-11-03-todo.md](docs/backlog/2026-11-03-todo.md)(待办总表;A–E 已全部闭环,剩余未闭环项见 §7) |
| 已交付了什么、哪天、哪个 PR | [docs/milestones.md](docs/milestones.md)(完整时间线) |
| 进行中 / 未启动的设计与计划 | [docs/superpowers/README.md](docs/superpowers/README.md)(工作面)+ [archive/INDEX.md](docs/superpowers/archive/INDEX.md)(归档清单,生成物) |
| 写代码 / 排障前 | [docs/pitfalls/README.md](docs/pitfalls/README.md) 按主题选:IM → im.md;前端 → frontend.md;后端 → backend.md;模拟器/打包 → android-emulator.md;测试 → testing.md;网页端 → web.md |
| **规范与命令手册**(怎么写代码 / 怎么写文档 / 怎么跑起来) | [docs/standards/README.md](docs/standards/README.md):[python.md](docs/standards/python.md) 注释规范、[writing.md](docs/standards/writing.md) 写作规范、[dev-commands.md](docs/standards/dev-commands.md) 命令手册 |
| 某条事实谁说了算 | [docs/standards/sources-of-truth.md](docs/standards/sources-of-truth.md)(口径地图) |
| 接口(对外交付级) | [docs/api/README.md](docs/api/README.md) |
| 部署与运维 | [docs/ops/runbook.md](docs/ops/runbook.md)(部署形态与更新流程见 §10;服务器细节 → [imserver.md](docs/ops/imserver.md)) |
| **发版(版本号 / tag / Release)** | [docs/ops/release.md](docs/ops/release.md)(强制清单 + 职责边界表;发版记录 owner 是 [docs/releases.yml](docs/releases.yml),CI 门禁读它) |
| 容量 / 观测 / 削峰的数字与口径 | [docs/ops/capacity-and-reliability.md](docs/ops/capacity-and-reliability.md) |
| 安全审计与整改 | [docs/security/README.md](docs/security/README.md)(轮次以目录为准,本表不写数字) |

## 里程碑

M0–M3 与后续七次追加均已交付;当前处于 **M4(运营)**。完整时间线见 [docs/milestones.md](docs/milestones.md),这里只留骨架。

> **项目定位(2026-11-04 用户决定):个人项目,不对外发行。** 不上架应用商店、不开放自助注册(手机号白名单收口)、不做合规轨(备案材料 / 软著 / 安全评估 / PIPIA 已否决);backlog 批次 B「上线阻断」整批关闭,**C/D/E 三批已于 2026-11-05 全部交付**。各类历史文档里的「上线阻断项 / 上线前必须做」口径一律作废,以 [backlog §4.2](docs/backlog/2026-11-03-todo.md) 为准;**安全基线不因此降级**。

| 阶段 | 一句话 |
|---|---|
| M0–M3 | 地基 / 后端全量 / 前端全量 / 合规(审核台 / 举报拉黑 / 重封禁 / 签名 APK) |
| 后 M3 ①–⑦ + M4 | ops 审核台 / 微信式聊天 / 单设备登录 / 广场 / 在线状态;M4 服务器跑通(宝塔全托管) |
| 2026-09~10 | 「心跳」UI 六批整改 / 网页端 Vue 3 / 接口文档体系 / 自建 IM 全量切换 / P1 功能群 |
| 2026-10-28~11-03 | 安全审计整改 + 令牌硬化 + HTTPS 上线 + 可观测性与容量工程 + 压测基线 |
| 2026-11-08~11 | 多端在线 / 输入中 / 批次 M–Q / 批次 R–W(随 1.0.13 上线) |
| 2026-11-12~14 | CI 流程门禁整改 P0/P1/P2 / worker 全断定位 + 巡检上服务器 / 文档与脚本治理 6 节 |

**当前风险最高的两项**(与代码质量无关,优先于任何性能项):① **固定验证码 `123456` + 手机号白名单** —— 白名单(`SMS_PHONE_WHITELIST` + 库表 `accounts.PhoneAllowlist`,运营在 `/ops/allowlist/` 维护)是**长期准入机制**,名单本身就是安全边界(一个号泄露 = 该账号被接管);日常运维见 [runbook §6](docs/ops/runbook.md);② **备份** —— 每天三层(03:20 自建双库全量 / 03:30 宝塔原生 / 04:10 树莓派拉走)+ **恢复演练已真跑通过**,剩余风险是「服务器与树莓派同时没了」(无对象存储预算);详见 [runbook §5](docs/ops/runbook.md)。

## UI 设计规则(2026-09-15 起,常驻,强制)

**所有 App 端 UI 开发(改版/新页面/新组件/新动效)一律遵循「心跳」设计规则**:`docs/superpowers/specs/2026-09-15-ui-design-language-design.md`(v1.5,已获用户批准)。动手前先读它,要点:

- 色板/渐变/字阶/圆角/间距/动效时长全走 token,**禁止新代码出现裸 hex、裸字号、裸间距**(页面改造时顺手按文档 §2.3 对照表清理旧硬编码)
- 主色 #FF2C55 + 心跳渐变(粉→橙)只出现在引导视线处(主按钮/选中/未读/配对/在线光),其余走三级中性色阶
- 字体:全局 Space Grotesk(拉丁/数字)+ 中文系统 fallback;图标统一 Material `*_rounded` 变体
- 动效三档(微交互/结构/情感),尊重 reduced-motion;不做纯装饰动画
- 旧视觉专项(微信式聊天/抖音式消息页/微博式广场)与「心跳」冲突处一律作废,以「心跳」为准

## 目录结构

| 路径 | 内容 | 说明 |
|---|---|---|
| `app/` | Flutter 应用 | `lib/core/`(网络/错误/凭证)、`lib/im/`(IM 抽象层)、`lib/router.dart`(go_router 路由表)、`lib/features/{auth,onboarding,discovery,chat,profile,settings,shell,square,presence,legal}`;测试是"真实 provider + 假网络 + 假 IM":`test/support/scripted_adapter.dart` + `test/support/harness.dart` 的 `pumpApp` + `test/support/fake_im_client.dart` |
| `chatapp/` | Django 项目(`manage.py` 所在层) | `config/` 项目包 + 业务 app:`accounts users discovery im moderation ops feed notifications feedback telemetry`;敏感配置读 `chatapp/.env`(gitignored,模板见 `.env.example`) |
| `flutter/` | **Flutter SDK 源码**(自带独立 .git) | 这是 SDK,不是应用代码,**切勿修改、勿提交**;命令用 `flutter/bin/flutter.bat` |
| `web/` | 网页端(Vue 3 SPA) | `src/{api,stores,im,components,layouts,features}`;开发 `npm run dev`(代理到 :8000),构建 `npm run build`;**只服务 PC 浏览器**,移动端按 UA 进引导页 |
| `imserver/` | 自建 IM(C++20) | WS :9100 + HTTP :9101;MySQL `chatapp_im` + Redis DB2;测试 `docker compose -f imserver/docker-compose.test.yml run --rm test bash /src/scripts/test_http.sh` |
| `docs/superpowers/` | 设计 spec 与实施计划 | 只放进行中/未启动的(`specs/`、`plans/`),已交付的进 `archive/`;索引见该目录 README |
| `docs/backlog/` | 待办总表 | 当前工作面 = 最新那份 |
| `docs/pitfalls/` | 踩坑手册(按主题分册) | 写代码/排障前按需读取 |
| `.remember/` | Claude 会话记忆日志(内部机制) | 勿改动、勿提交 |

根目录是 git 仓库;`main` 为主线(2026-11-11 由 `master` 改名),功能开发走短生命周期分支后合回。**部署只认 `origin/main` 的 SHA**(见下「核心契约与纪律」的发布流程)。

## 常用命令

**已搬到 [docs/standards/dev-commands.md](docs/standards/dev-commands.md)**:后端(`manage.py` 全量/单 app、造数、手测、回填命令)、Redis + Celery、前端(`flutter analyze` / `test` / `run`)、网页端(`npm run dev` / `test:run` / `e2e`)、出签名包、服务器入口。本节只留两条前置:**跑测试与接口前 Redis 必须起着**(cwd = `chatapp/`,`docker compose -f docker-compose.dev.yml up -d`);**改了 Celery 任务代码必须重启 worker**。

## 核心契约与纪律

- **错误契约**:成功 2xx + 资源 JSON;失败一律 `{"code": <HTTP状态码>, "message": "<中文>", "request_id": ...}`;业务码=前 3 位 HTTP + 2 位序号(`config/error_codes.py`)
- **鉴权**:Bearer JWT(access 30min / refresh 30d,刷新即轮换、旧进黑名单);JWT `user_id` claim 是**字符串**;`GET /users/me` 响应 `id` 是 **profile 表主键**,账号 ID 看 `user_id`
- **响应路径禁止任何第三方网络调用**(短信商/任何外部 REST);跨系统副作用一律走 Celery 任务;`transaction.on_commit(fn, robust=True)` 的语义是「DB 提交后」
- **IM 副作用唯一入口 `im/tasks.py`**(任务参数一律 user_id,任务内查库;任务体内不查 request);`im/client.py` 与 `im/self_client.py` 对外永不抛异常;`.env` **禁用 `CELERY_` 前缀键**(用 `BROKER_URL`)。唯一例外:`im/tasks.py::delete_account` 的参数是 `im_user_id` 字符串 —— 它在用户行删除后入队,任务内查库必然拿到 `None`,详见 `docs/pitfalls/backend.md`「账号注销」
- **自建 IM(唯一后端)**:`im/client.py` 是语义层(消息类型/灰条文案/系统通知身份),传输统一转调 `im/self_client.py` 的 HMAC 内部 API;没有 `IM_BACKEND` 开关、没有灰度名单,**回退方式 = 回退 imserver 镜像/后端 SHA**(不再有「切回腾讯」);`imserver/` 的 WS/HTTP 端口、JWT/HMAC 密钥与 Django `.env` 必须一致;**图片消息与语音消息**要求 `IM_MEDIA_PREFIX` = Django 的 `MEDIA_BASE_URL + /media/chat/`(必填,缺失 imserver 起不来;不一致则发图/发语音 42201);语音上传还要求服务器装 `ffmpeg`/`ffprobe`(缺失时 503+`50302`)
- **IM 会话版本与聊天权限(2026-10-28 起)**:IM token 带 `sv`,imserver 与 `im_user.session_version` 比对,不一致 40101(批次 K 起 `sv` 是**该端**版本、token 多一个 `ct`,按 `(uid, client_type)` 比对,见「多端在线」),**WS 握手与 `/im/api/*` 两个入口同口径**;登录时把 `session_version` 同步到 imserver,同步失败 503。发送要求 `im_pair` 存在(未配对 40302),目标必须已存在(不再为任意 uid 建行),单账号 `IM_SEND_PER_MINUTE` 配额。**上线新版本后必须跑一次 `python manage.py im_sync_pairs` 回填现有配对**,否则老用户发不出消息
- **imserver 入口防护(2026-10-28 起)**:监听默认只允许回环,写成非回环地址必须显式 `IM_ALLOW_PUBLIC_BIND=1`,否则启动失败;`X-Real-IP` 只在对端命中 `IM_TRUSTED_PROXIES`(默认 `127.0.0.1,::1`,支持 CIDR)时才采信;`Origin` 未配 `IM_ALLOWED_ORIGINS` 时按同源兜底(不是全放行)
- **图片上传**:资料图/广场图/聊天图统一走 `config/images.py`(仅 jpg/png/webp、≤2000 万像素、长边 4096、`exif_transpose` 后重编码剥离 EXIF/GPS);聊天媒体签名生产缺 `IM_MEDIA_SIGN_SECRET` 直接启动失败,TTL 默认 3600
- **存储配额(2026-10-28 起)**:四类媒体(资料图/广场图/聊天图/语音)按库内 `bytes` 求和,单账号上限 `USER_STORAGE_QUOTA_MB`(默认 200),超限上传 **413 + `41301`**;检查必须在落盘前;删除与 30 天过期自动回收,不做计数列;上线必须跑一次 `media_bytes_backfill`
- **运营后台安全**:`/admin/`、`/ops/` 受 `ops.middleware.StaffSecurityMiddleware` 保护 —— `OPS_ALLOWED_IPS` 非空时只放白名单;`OPS_OTP_REQUIRED=1`(生产默认)时运营账号必须绑定 TOTP(`/ops/otp/`);登录失败 5 次锁 15 分钟(账号+IP)。生产 `AUTO_APPROVE` 默认 0,新资料图进 `/ops/photos/` 待审队列
- **跨栈约定**:IM 账号 = `u{user_id}`(`accounts/models.py::im_user_id`);`system_notice` 相关常量两边别单改
- **已读回执(2026-11-04)**:事实来源是 `im_conversation_state.read_seq`,语义是「**我**读到哪」;对端视角叫 `peer_read_seq`(`GET /im/api/conversations` 的字段)。判定永远是「**我方**消息 `seq <= peer_read_seq` = 已读」,`unread`(我没读的条数)是另一条链路,不可互推。服务端在 `read` 帧落库后**回读实库**再向对端推下行 `read` 帧(`GREATEST` 语义,乱序旧帧不会把已读推回去),客户端只增不减;`read` 帧有 2/s 限流,超限静默丢弃。协议与排查见 `docs/ops/imserver.md` §15
- **多端在线(2026-11-08 起,批次 K)**:一个账号可同时在线 **1 个 App + 1 个网页**,**同类端互顶**;被顶设备收 **401 + `40101`**。会话版本从 `User` 单列下沉到 `accounts.DeviceSession(user, client_type, version)`(`unique(user, client_type)`),JWT 与 IM token 都带 `ct` claim;**判端只在签发时看请求头 `X-Client`(缺省 `app`),鉴权一律看令牌里的 `ct`**;IM 踢人按端(`kick_user(..., client_type=...)`),`client_type=None` 才是「踢全部」(封禁 / 注销);一键全端下线用 `POST /auth/logout/all`。设计与取舍见 `docs/superpowers/archive/specs/2026-11-08-multi-device-session-design.md`,踩坑见 `docs/pitfalls/backend.md`「多端会话」。
- **封禁两级**:`banned_light` 只禁滑卡;`banned_heavy` 全域 403——全局权限类自动覆盖新接口,白名单仅 `GET /users/me`、`GET /users/tags`
- **在线状态是公开信息**(不依赖配对);「在线」= 120 秒内有认证请求(45s 心跳)
- **前端**:401 只走 `AuthInterceptor` 刷新通道;错误统一 `ApiException`;写操作后检查相关 provider 失效
- **网页端**:401 只走 `api/http.ts` 的刷新通道(并发去重);错误统一 `ApiError`;页面只碰 store、不直接调 `http`
- **「心跳」token 双份维护**:改任何视觉 token 或字体,**必须在同一次改动内同时改** `app/lib/core/theme/*.dart` 与 `web/src/styles/tokens.css`(`web/public/fonts/*` 与 `app/assets/fonts/*` 保持一致);`web/tests/unit/tokens.spec.ts` 与 `fonts.spec.ts` 会双向比对,漏改即红
- **跨栈 IM 协议帧(2026-11-05 起,E-2)**:`imserver/tests/fixtures/ws/*.json` 是三端(App / Web / imserver)唯一的线上帧契约源。改任何 WS 帧格式必须**同一次改动内**同时改:fixture + imserver(`src/net/frames.h` 的构造 / `ws_server.cpp`)+ App(`self_im_client.dart` 与 `app/test/im/protocol_fixture_test.dart`)+ Web(`web/src/im/self/*` 与 `web/tests/unit/im-protocol-fixture.spec.ts`);三条 CI 轨(`imserver.yml`/`app.yml`/`web.yml`)各自会红。契约与改法见 `imserver/tests/fixtures/ws/README.md`
- **测试纪律**:后端全量绿(前置 Redis)+ `flutter analyze` 零告警;IM 一律 mock(`im.tasks.*.delay`);每步全绿再进下一步
- **发布流程(2026-11-03 起,强制)**:分支提交 → `git push` → **开 PR** → **CI 全绿** → squash 合并 → **只部署 `origin/main` 的 SHA**。禁止把未合并的本地提交直接 bundle/scp 上线;部署前先 `git fetch` 确认要落的 commit 就是合并后的那个,并先记下回滚点(旧 SHA / 旧镜像 tag / `.env` 备份)。CI 跑在 Ubuntu + MySQL 8 + Redis 上,与本地 Windows 不同;顺序错了会变成「CI 红时生产已在跑未验证代码」
- **网页端测试纪律**:`vue-tsc` 零错误 + `eslint --max-warnings 0` 零告警 + vitest 全绿(覆盖率门槛 70/60/70/70);**端到端冒烟进 CI**(`web-e2e.yml`:真 MySQL + Redis + Django + preview,跑 `npm run e2e:smoke`);全量 8 条仍需后端 + Redis + Celery + imserver,本地 `npm run e2e`(E-3)
- **发版版本号必须双端同改**:`app/pubspec.yaml` + `app/lib/core/app_info.dart` + `web/package.json`(连带 App 关于页与 Web 关于页测试的期望)。**事实来源只有 `app/pubspec.yaml`**:改完跑 `python scripts/sync_version.py --check`(CI 的 `contract.yml` 会拦),`--write` 自动写回另外两处。`MIN_APP_VERSION` 同时卡网页端——只升 App 会让整站被「需要更新后才能继续使用」挡住(2026-10-28 实测,见 `docs/pitfalls/web.md` #23);改完 Web 必须 `npm run build` 并部署 `dist`
- **版本更新必须同步更新远端 Release(2026-11-05 起,强制)**:升版本号 = 三件事同时做 —— ① 三处版本号一致;② 打附注 tag `v<版本>` 并推送,指向**部署用的那个合并 SHA**;③ 建/更新远端 GitHub Release(title `v<版本> — <主题>`、notes 写新增/变更/修复/运维注意、附件挂 `chatapp-<版本>.apk`)。**不是「下次补」**。发版后必须在 [`docs/releases.yml`](docs/releases.yml) 记一条(版本 / 日期 / tag / Release / 上线 SHA / APK),再跑 `python scripts/releases.py --render` 渲染 [`docs/ops/release.md`](docs/ops/release.md) §5;`python scripts/sync_version.py --check` 校验记录缺失即红、`releases.py --check` 校验渲染物过期即红(均 `contract.yml` 拦截)。清单、命令与 notes 规范见该文档 §3–§4
- **Release 用本机 GitHub 凭据发布(2026-11-07 起,强制)**:本机有 **GitHub MCP**(`mcp-github`,remote server,49 个 repo/issues/PR 工具)与它用的同一个 classic PAT(`repo` 权限,`~/.dsh/github-mcp-token.txt`)。Release **必须**用 `python scripts/create_release.py --title "v<版本> — <主题>" --notes-file <notes> --apk app/build/app/outputs/flutter-apk/app-release.apk --asset-name chatapp-<版本>.apk` 创建/更新(幂等:已有同 tag 就 PATCH、同名附件先删后传),**禁止再写「本机无 `gh`/token,Release 待建」**。注意 MCP 工具集本身**没有** `create_release`(只有 get/list release),所以走脚本里的 REST 通道;脚本读的就是 MCP 那个 token 文件。建完把链接回填 `docs/releases.yml` 对应记录(再 `releases.py --render`)
- **App 改动必须在安卓模拟器上验收(2026-11-07 起,强制)**:本机有常驻 **Android 模拟器**(`emulator-5554`,AVD `Pixel_7`,Android 17;`adb` 在 `%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe`)。涉及 App UI 的批次**必须**装到模拟器上逐页手测并截图留证(登录 → 目标页 → 关键交互),**不得以「本机无模拟器」为由跳过**;装包前若签名冲突先 `adb uninstall com.chatapp.chatapp_app`。手测发现的问题按「真机回归记录」写进计划执行记录
- **接口文档**:`docs/api/` 是接口的对外交付文档;新增/修改/删除任何 `/api/v1` 接口,**同一次改动内**必须同步更新对应分册;`python manage.py test` 会跑 `ApiDocsCoverageTests` 双向比对,漏写即红。模板与维护规则见 `docs/api/README.md`
- **OpenAPI 生成物(D-5)**:`docs/api/openapi.yml` 是**机器可读契约**,由 `cd chatapp && python manage.py spectacular --file ../docs/api/openapi.yml --validate` 从视图上的 `@extend_schema` 生成,**禁止手改**;改了对外字段(改名/增删/改类型)必须在同一次改动内重新生成并提交,CI 会重新生成后 `git diff --exit-code` 比对。`config/tests.py::OpenApiSchemaTests` 校验「schema 操作集合 == URLconf 操作集合」,`config/test_schema_contract.py` 做**字段级双向门禁**(`docs/api/*.md` 的参数表 ↔ schema 字段,漏写/多写即红)。派生门禁:Web `npm run gen:api` → `web/src/api/schema.d.ts`(`web.yml` 比对生成物,`web/src/api/contract.ts` 做手写类型的字段名编译期断言);App 由 `scripts/check_app_models.py` 扫 `models.dart` 的 `json['...']` 键比对契约(`contract.yml`)
- **注释规范**:`docs/standards/python.md` 是 Python 注释的单一事实来源;新增/修改任何 `.py` 文件,**同一次改动内**必须补齐模块 docstring 与函数/类 docstring(`test_*` 用例、`setUp` 等生命周期钩子、`Meta` 声明式内部类、函数内闭包豁免),**公开函数带参数必须写 `Args:` 小节**;`python manage.py test` 会跑 `CommentCoverageTests` 比对,漏写即红。本地快速自查:`cd chatapp && python config/comment_coverage.py`(秒级,不依赖 Django),`--warnings` 看口语词提示、`--structure` 看 `Args` 结构提示(均不拦截)

## 后端接口

**接口的 owner 是 [docs/api/](docs/api/README.md)**:分册 + `openapi.yml`(机器可读契约),份数与操作数以生成物为准;新增/改接口必须同一次改动内改对应分册(`ApiDocsCoverageTests` 双向比对),「接口一览」表与契约的操作集合**逐一相等**由 `python scripts/docs_index.py --check` 判定。本文件**不再维护第二份接口清单**(2026-11-14 治理第 6 节删掉原来 36 行的手写表);跨接口的强制约束仍在上面的「核心契约与纪律」,发版 / 部署动作见 [docs/ops/release.md](docs/ops/release.md)。

## 下一步

**所有待办统一在 [docs/backlog/2026-11-03-todo.md](docs/backlog/2026-11-03-todo.md)**:按批次(A 止血 → B 准入收敛「已关闭」→ C 产品闭环 → D 规模架构 → E 工程纪律)排好序,每条都带证据、验收口径和「开新对话提示词」。**当前进度(2026-11-05):A–E 五批全部闭环,本表已无待办;剩余未闭环项是备份异地(无对象存储预算)、树莓派容量、TOTP 重绑确认与 Loki 常驻,列在 backlog §7。消息推送已明确不做(2026-11-05),不要再把它当待办重新提出。不要在本文件里另起一份待办清单。**
