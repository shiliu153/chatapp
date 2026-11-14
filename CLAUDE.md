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
| **现在该做什么** | [docs/backlog/2026-11-03-todo.md](docs/backlog/2026-11-03-todo.md)(待办总表,按批次排好;A–E 已全部闭环,剩余未闭环项见 §7) |
| 已交付了什么、哪天、哪个 PR | [docs/milestones.md](docs/milestones.md)(完整时间线) |
| 进行中 / 未启动的设计与计划 | [docs/superpowers/README.md](docs/superpowers/README.md)(当前工作面 4 组 + 归档 105 份的索引) |
| 写代码 / 排障前 | [docs/pitfalls/README.md](docs/pitfalls/README.md) 按主题选:IM → im.md;前端 → frontend.md;后端 → backend.md;模拟器/打包 → android-emulator.md;测试 → testing.md;网页端 → web.md |
| 接口(对外交付级) | [docs/api/README.md](docs/api/README.md) |
| 部署与运维 | [README.md](README.md)「部署」;服务器细节 → [docs/ops/imserver.md](docs/ops/imserver.md)、[docs/ops/runbook.md](docs/ops/runbook.md) |
| **发版(版本号 / tag / Release)** | [docs/ops/release.md](docs/ops/release.md)(强制清单 + 发版记录表,CI 门禁读它) |
| 容量 / 观测 / 削峰的数字与口径 | [docs/ops/capacity-and-reliability.md](docs/ops/capacity-and-reliability.md) |
| 安全审计与整改 | [docs/security/](docs/security/)(三轮报告) |
| 工程审查结论 | [docs/reviews/2026-11-03-fullstack-review.md](docs/reviews/2026-11-03-fullstack-review.md) |
| Python 注释规范 | [docs/standards/python.md](docs/standards/python.md) |

## 里程碑

M0–M3 与后续七次追加均已交付;当前处于 **M4(运营)**。

> **项目定位(2026-11-04 用户决定):个人项目,不对外发行。** 不上架应用商店、不开放自助注册(手机号白名单收口)、不做合规轨(备案材料 / 软著 / 安全评估 / PIPIA 已否决);backlog 批次 B「上线阻断」整批关闭,**C/D/E 三批已于 2026-11-05 全部交付**。各类历史文档里的「上线阻断项 / 上线前必须做」口径一律作废,以 [backlog §4.2](docs/backlog/2026-11-03-todo.md) 为准;**安全基线不因此降级**。

**完整时间线见 [docs/milestones.md](docs/milestones.md)**,这里只留骨架:

| 阶段 | 一句话 |
|---|---|
| M0–M2 | 地基 / 后端全量 / 前端全量(登录→卡片→配对→IM 聊天) |
| M3 | 合规:审核台 / 举报拉黑 / 重封禁 403 / 协议弹窗 / 签名 APK |
| 后 M3 ①–⑦ | ops 审核台 / 封禁消息+消息页 / 微信式聊天+资料页 / 单设备登录+造数 / 举报通知 / 广场 / 在线状态 |
| M4 第一步 | 服务器跑通(宝塔全托管) |
| 2026-09~10 | 「心跳」UI 六批整改 / 网页端 Vue 3 / 接口文档体系 / 自建 IM 全量切换 / P1 功能群 / 聊天图片·语音·搜索 |
| 2026-10-28~11-03 | 三轮安全审计整改 + 令牌硬化 + HTTPS 上线 + 可观测性与容量工程 + 压测基线 |
| 2026-11-08~09 | 第四轮安全审计整改上线(纯服务端)+ 第六轮功能开发 **K** 多端在线(1 App + 1 Web)/ **L** 输入中状态 + 引用回复(均已于 2026-11-09 随 **1.0.11** 上线) |
| 2026-11-09 | 第六轮功能开发 **M–Q** 五批全部合并进 `master`(未发版):**M** 登录设备(列表 + 单端下线)/ **N** 会话管理三件套(置顶·免打扰·删除)/ **O** 滑卡增强(30 秒撤销 + 每日喜欢额度)/ **P** 使用报告(`GET /stats/me`)/ **Q** 聊天文字敏感词(本地词库 + AC)。15 个 PR,末次合并 `72589f9`;设计与取舍见 [批次 M–Q spec](docs/superpowers/archive/specs/2026-11-09-batch-m-q-design.md) |
| 2026-11-10~11 | 第七轮功能开发 **R–W** 六批全部合并进 `master` 并 **2026-11-11 随 1.0.13 上线**:**W** 发版自动化(`scripts/release_prep.py` 一条命令 + golden 截图进 CI)/ **R** 资料语音自我介绍 / **S** 发现页筛选 + 每日精选 / **U** 广场点赞列表 + 收藏 / **V** 运营数据看板 / **T** 聊天体验打磨(多选删除·草稿·图片全屏·语音进度倍速)。14 个 PR,末次合并 `74c1cef`,上线 SHA `e7456f6`;设计与取舍见 [批次 R–W spec](docs/superpowers/archive/specs/2026-11-09-batch-r-w-design.md),上线实况见 [release.md §6.8](docs/ops/release.md) |
| 2026-11-13 | **worker 全断定位 + 巡检上服务器**(不升版本、不动业务代码):① 根因是宿主 **Sangfor aTrust** 的 WFP 过滤器把 **WSL 的直连 TCP 整体拦掉**(UDP DNS 仍通),连带 mihomo 连不上机场节点、模型网关 443 不可达 → 「派了单永远不动 + assignment 卡 6 小时」而面板全 `ready`;修法 `networkingMode=mirrored`(`docs/ops/superagent.md` §12.0);② 新增 **`scripts/superagent-health`**(systemd timer 每 15 分钟/开机补跑):查出网 / 入队三连 / 僵尸 assignment,异常发告警(同种 6h 一次),僵尸可人工作废;③ 派单守门补「WSL 出网」判据;④ `l4_intake` 判红口径改结论红集合(`cancelled`/`startup_failure` 等不再当绿);⑤ failover 支持经 HTTP 代理 CONNECT;⑥ 修掉 L4 首轮 6 处归档断链。7 个 PR;详见 [milestones](docs/milestones.md) 与 superagent.md §12.0 / §4.2 / §15 |
| 2026-11-12 | **CI 流程门禁整改 P0/P1/P2**(不升版本、不动业务代码):把「CI 绿才合并、只部署合并后 SHA」从**纪律**换成**机制** —— `contract`/`backend`/`web` 设为默认分支必需检查 + 三条轨去 `paths` 改「重活按改动面跑」(`scripts/ci-scope.sh`,无关时 `skipped`,判定失败 fail-closed)、部署闸门 `scripts/deploy_gate.py`、默认分支健康检查 `main-health.yml`、0-check 不再放行、覆盖率门槛真跑、CI 装 `requirements.lock`、`accounts.E001` 进流水线、gh-guard 补 REST 绕过口、dependabot + Actions pin 21 处。8 个 PR;设计与**未收尾台账**见 [ci-flow-gates spec](docs/superpowers/archive/specs/2026-11-12-ci-flow-gates-design.md),运维口径见 [superagent.md §8.1](docs/ops/superagent.md) |

**当前风险最高的两项**(与代码质量无关,优先于任何性能项):① **固定验证码 `123456` + 手机号白名单** —— 2026-11-03 已确定**本项目不接入短信商**,白名单(`SMS_PHONE_WHITELIST`)是**长期准入机制**而非过渡方案:名单外一律 `403 + 40301`,名单内仍是固定码,因此「名单里有哪些号」本身就是安全边界(一个号泄露 = 该账号被接管)。名单存在数据库 `accounts.PhoneAllowlist`,运营在 **`/ops/allowlist/`** 加号/停用(**立刻生效,不用重启**);`.env` 的 `SMS_PHONE_WHITELIST` 降级为兜底种子(库里没这条记录时按它放行,库里显式停用的优先被拒),库与种子都空 = 不限制。日常运维见 `docs/ops/runbook.md` §6;② **备份** —— 每天 03:20 自建双库全量(应用库 + IM 库 + 媒体 + 配置,保留 14 天,`deploy/ops/chatapp-backup.sh`),另有宝塔 03:30 的原生备份作为独立第二份,树莓派每天 04:10 主动拉走(`deploy/ops/pull-backup-pi.sh`),三项都进 22:00 服务器日报;**恢复演练已真跑通过**。剩余风险:防得住「服务器磁盘/整机没了」,防不住「服务器和树莓派同时没了」(无对象存储预算)。详见 backlog 的 B-1/B-1c 与 A-3、`docs/ops/runbook.md` §5。

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

根目录是 git 仓库;`main` 为主线(2026-11-11 由 `master` 改名),功能开发走短生命周期分支后合回。**部署只认 `origin/main` 的 SHA**(见下「发布流程」)。

## 常用命令

**后端**(cwd = `chatapp/`,Python 用 anaconda 环境 `Django`):
```bash
python manage.py test              # 全量(前置:Redis 在跑,见下)
python manage.py test accounts     # 单 app
python manage.py runserver         # 开发服务器 :8000
python manage.py makemigrations && python manage.py migrate
python manage.py im_send --from u2 --to u3 --text "你好"   # 手测:代发消息(--notice 发灰条;需先有配对)
python manage.py im_sync_pairs --dry-run                  # 回填现有配对到 imserver(H4 上线必跑)
python manage.py dev_reset_pair --a u8 --b u9              # 手测:清滑卡/配对重演(不清聊天记录)
python manage.py seed_fake_users --count 20                # 造数(幂等;直调 IM 同步,不必等 worker)
python manage.py refresh_shuffle_keys [--dry-run]          # 轮换候选池随机键(建议每天低峰)
python manage.py media_bytes_backfill [--dry-run]          # 回填照片/动态图字节数(M7 上线必跑)
python manage.py media_cleanup [--apply]                   # 清资料图/广场图孤儿文件(默认 dry-run)
python manage.py media_disk_report [--fail-over]           # 媒体磁盘报表;超告警线退出码 1
python manage.py perf_tokens --count 50 --out ../perf/results/headers.jsonl  # 压测:签多账号令牌(写场景用;文件含活令牌,跑完删)
python manage.py allowlist_seed_import [--dry-run]         # 把 .env 的准入名单种子导进库(幂等;不重新启用已停用的号)
```

**Redis / Celery**(cwd = `chatapp/`;验证码、限流、异步 IM 副作用都靠它们):
```bash
docker compose -f docker-compose.dev.yml up -d             # Redis 容器(redis:7, 6379);跑测试/接口前必须起
python -m celery -A config worker -l info --pool=solo      # IM 副作用 worker(Windows 只能 solo);改了任务代码必须重启它
```

**前端**(cwd = `app/`):
```bash
../flutter/bin/flutter.bat analyze   # 必须零告警
../flutter/bin/flutter.bat test
../flutter/bin/flutter.bat run -d emulator-5554 --dart-define=API_BASE=http://10.0.2.2:8000/api/v1
```

**网页端**(cwd = `web/`;端到端需要后端 + Redis + Celery 都在跑):
```bash
npm run dev          # 开发(代理到 :8000)
npm run test:run     # 单元/组件测试(vitest)
npm run test:coverage # 带覆盖率门槛(70/60/70/70)
npm run e2e          # 端到端(Playwright;自建 build + preview)
npm run type-check && npm run lint   # 必须零错误 / 零告警
```

**出签名包**(keystore `C:\Users\you\chatapp-release.jks`,口令在 `app/android/key.properties`;两个文件都不入库,务必备份):
```bash
cd app && ../flutter/bin/flutter.bat build apk --release --dart-define=API_BASE=https://chat.shiliu153.cn/api/v1 --dart-define=ERROR_REPORTING=true
```
产物 `app/build/app/outputs/flutter-apk/app-release.apk`。`--dart-define=ERROR_REPORTING=true` **必须带**(否则线上崩溃与白屏不会上报,见 backlog A-4);Web 侧对应 `web/.env.production` 的 `VITE_ERROR_REPORTING=1`。**发版必须同时**:`pubspec.yaml` 的 `version:` + `lib/core/app_info.dart` 的 `appVersion` + 关于页测试期望三处一起改,再上传到 `/www/wwwroot/chatapp-web/chatapp-<版本>.apk` 并更新 `.env` 的 `MIN_APP_VERSION`/`LATEST_APP_VERSION`/`APP_DOWNLOAD_URL`。**完整发版清单(含 tag 与远端 Release)见 [docs/ops/release.md](docs/ops/release.md)。**

**服务器**:`ssh root@<SERVER_IP>`(免密);部署形态与更新流程见 [README.md](README.md)「部署」。服务器私有的运维手册(面板口令/路径/端口)不入库,本地保留。

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
- **版本更新必须同步更新远端 Release(2026-11-05 起,强制)**:升版本号 = 三件事同时做 —— ① 三处版本号一致;② 打附注 tag `v<版本>` 并推送,指向**部署用的那个合并 SHA**;③ 建/更新远端 GitHub Release(title `v<版本> — <主题>`、notes 写新增/变更/修复/运维注意、附件挂 `chatapp-<版本>.apk`)。**不是「下次补」**。发版后必须在 [`docs/ops/release.md`](docs/ops/release.md) §5 记录表加一行(版本 / 日期 / tag / Release / 上线 SHA / APK),`python scripts/sync_version.py --check` 会校验这一行缺失即红(`contract.yml` 拦截)。清单、命令与 notes 规范见该文档 §3–§4
- **Release 用本机 GitHub 凭据发布(2026-11-07 起,强制)**:本机有 **GitHub MCP**(`mcp-github`,remote server,49 个 repo/issues/PR 工具)与它用的同一个 classic PAT(`repo` 权限,`~/.dsh/github-mcp-token.txt`)。Release **必须**用 `python scripts/create_release.py --title "v<版本> — <主题>" --notes-file <notes> --apk app/build/app/outputs/flutter-apk/app-release.apk --asset-name chatapp-<版本>.apk` 创建/更新(幂等:已有同 tag 就 PATCH、同名附件先删后传),**禁止再写「本机无 `gh`/token,Release 待建」**。注意 MCP 工具集本身**没有** `create_release`(只有 get/list release),所以走脚本里的 REST 通道;脚本读的就是 MCP 那个 token 文件。建完把链接回填 §5
- **App 改动必须在安卓模拟器上验收(2026-11-07 起,强制)**:本机有常驻 **Android 模拟器**(`emulator-5554`,AVD `Pixel_7`,Android 17;`adb` 在 `%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe`)。涉及 App UI 的批次**必须**装到模拟器上逐页手测并截图留证(登录 → 目标页 → 关键交互),**不得以「本机无模拟器」为由跳过**;装包前若签名冲突先 `adb uninstall com.chatapp.chatapp_app`。手测发现的问题按「真机回归记录」写进计划执行记录
- **接口文档**:`docs/api/` 是接口的对外交付文档;新增/修改/删除任何 `/api/v1` 接口,**同一次改动内**必须同步更新对应分册;`python manage.py test` 会跑 `ApiDocsCoverageTests` 双向比对,漏写即红。模板与维护规则见 `docs/api/README.md`
- **OpenAPI 生成物(D-5)**:`docs/api/openapi.yml` 是**机器可读契约**,由 `cd chatapp && python manage.py spectacular --file ../docs/api/openapi.yml --validate` 从视图上的 `@extend_schema` 生成,**禁止手改**;改了对外字段(改名/增删/改类型)必须在同一次改动内重新生成并提交,CI 会重新生成后 `git diff --exit-code` 比对。`config/tests.py::OpenApiSchemaTests` 校验「schema 操作集合 == URLconf 操作集合」,`config/test_schema_contract.py` 做**字段级双向门禁**(`docs/api/*.md` 的参数表 ↔ schema 字段,漏写/多写即红)。派生门禁:Web `npm run gen:api` → `web/src/api/schema.d.ts`(`web.yml` 比对生成物,`web/src/api/contract.ts` 做手写类型的字段名编译期断言);App 由 `scripts/check_app_models.py` 扫 `models.dart` 的 `json['...']` 键比对契约(`contract.yml`)
- **注释规范**:`docs/standards/python.md` 是 Python 注释的单一事实来源;新增/修改任何 `.py` 文件,**同一次改动内**必须补齐模块 docstring 与函数/类 docstring(`test_*` 用例、`setUp` 等生命周期钩子、`Meta` 声明式内部类、函数内闭包豁免),**公开函数带参数必须写 `Args:` 小节**;`python manage.py test` 会跑 `CommentCoverageTests` 比对,漏写即红。本地快速自查:`cd chatapp && python config/comment_coverage.py`(秒级,不依赖 Django),`--warnings` 看口语词提示、`--structure` 看 `Args` 结构提示(均不拦截)

## 后端接口

- 鉴权:`Authorization: Bearer <access>`(JWT);开发期验证码固定 `123456`(`SMS_DEV_MODE=1`)

| 接口 | 说明 |
|---|---|
| `POST /auth/sms/send` | 发验证码;同号 60 秒重发间隔(42901,带 Retry-After);IP 限流;入队失败回滚并 503(50301);**名单外号码 403(40301),不落码不入队**(名单在 `accounts.PhoneAllowlist`,运营在 `/ops/allowlist/` 维护、改完立刻生效;`.env` 的 `SMS_PHONE_WHITELIST` 是兜底种子;库与种子都空=不限制) |
| `POST /auth/sms/verify` | 校验并登录(号码没注册过自动建号)→ `{access, refresh, is_new_user, user_id}`;带 `X-Client: web` 时 refresh 改为 HttpOnly Cookie、响应体不含 refresh;连错 5 次锁 15 分钟(42902);60 秒幂等重放窗口;**staff/superuser 一律 403(运营账号走 `/ops/`,封闭测试可用 `SMS_ALLOW_STAFF_LOGIN=1` 放开)** |
| `POST /auth/token/refresh` | 刷新 access(响应同时给新 refresh);refresh 可放请求体或 Cookie;轮换后 60 秒宽限内允许并发标签页复用 |
| `POST /auth/logout` | 注销:拉黑 refresh + 清 Cookie;幂等 204;按 IP 60 次/小时;带 `Origin` 时校验同源 |
| `POST /auth/logout/all` | **退出所有设备**(需鉴权):两端会话版本各 +1 → 两端 access/refresh 全失效,并**经 Celery** 踢掉全部在线 IM 会话;204 + 清 Cookie;按 IP 60 次/小时 |
| `GET/PATCH/DELETE /users/me` | 我的资料(昵称/性别/生日/城市/简介/`tag_ids`);未满 18 岁 400;`id`=profile 主键。**DELETE = 注销账号**:body 带 `phone` 二次确认,立即硬删除全部数据 + 释放手机号(同号可重注册为全新账号);重封禁 403 |
| `GET /users/tags` | 标签池(12 个,数据迁移写入) |
| `POST /users/me/photos`、`DELETE /users/me/photos/{id}` | 照片(multipart 字段 `file`;最多 6 张、≤5MB、jpg/png/webp);生产 `AUTO_APPROVE=0` 时新照片为 `pending`,需 ops 审核 |
| `GET/PATCH /users/me/preference` | 想找的人:目标性别(可空=不限)/ 年龄区间 / 城市 |
| `POST /im/user_sig` | 取 IM 登录凭证(自建 `token`,响应含 `ws_url`/`http_url`);`banned_heavy` 403 |
| `POST /im/images` | 上传聊天图片(自建 IM 发图前置;jpg/png/webp ≤5MB、长边 ≤4096,服务端出 240px 缩略图;30 次/小时);响应里的 `url/thumb_url` 是**限时签名地址** |
| `POST /im/voices` | 上传聊天语音(自建 IM 发语音前置;m4a/aac/webm/ogg ≤5MB、时长 1–60 秒,ffmpeg 统一转 m4a/AAC;60 次/小时);响应 `url` 为**限时签名地址**;缺 ffmpeg 时 503+`50302` |
| `GET /im/images/auth` | nginx `auth_request` 子请求验签(读 `X-Original-URI`,204/403);不是给客户端调的 |
| `GET /app/config` | 公开;最低版本配置(启动时拦截旧版本) |
| `GET /discovery/candidates` | 候选卡(默认 10、上限 20);排除自己/划过/已配对/资料未完善;**只推有已过审照片的人** |
| `POST /discovery/swipe` | `{target_user_id, action: like\|pass}`;幂等;互喜 → `{"matched": true}` + 双方灰条;限流 300/小时 |
| `GET /discovery/likes` | 喜欢我的人(分页);口径与候选池一致,排除我已划过/双向拉黑/资料不全/无过审照片 |
| `GET /discovery/likes/count` | 喜欢我的人数(入口角标);与列表同口径 |
| `GET /discovery/visits` | 谁看过我(分页,120/小时);打开他人资料页即记一次,同一人 30 分钟内只刷新时间;**只为「资料完善 + 有过审照片」的访问者落库**;口径同「喜欢我的人」 |
| `GET /discovery/visits/count` | 访客人数(入口角标,240/小时);与列表同口径 |
| `GET /matches` | 配对列表(分页);预热 userId→昵称头像缓存 |
| `DELETE /matches/{user_id}` | 解除配对:幂等 204;软删除 + 双向 IM 拉黑,不可恢复 |
| `POST /feedback` | 意见反馈(10–500 字 + 可选联系方式;限流 5/小时) |
| `POST /client-errors` | 前端未捕获异常上报(**匿名可调**,120 次/小时/IP);只写 JSON 日志 `chatapp.client_error` + `client_errors_total{platform}`,不落库 |
| `POST/DELETE /push/devices`、`GET/PATCH /push/preferences` | 推送设备上报/解绑(registration_id 全局唯一、同账号只留最新一台)与四类通知开关(`likes/matches/messages/system`);通道 `PUSH_PROVIDER=off|log|jpush`。**本项目不做离线推送(2026-11-05 决定,见 backlog §4)**:通道固定 `off`,接口与代码保留但不产生外部调用,App 不集成推送 SDK |
| `POST /internal/push/new-message` | **不是给客户端调的**:imserver 在「消息落库 + 目标不在线」时回调它(HMAC 共享密钥 + 时间戳窗口 + 按 `msg_id` 幂等),再由 Celery 发推送;不在 `/api/v1` 下,契约见 `docs/ops/push.md`。**推送通道固定 `off`,该回调当前只累加 `push_skipped_total{reason="provider_off"}`** |
| `/posts` 系列、`POST /reports`、`GET/POST/DELETE /blocks`、`GET /presence` | 广场 / 举报 / 拉黑 / 在线状态,细节见 `docs/api/` 与 pitfalls(评论支持两级楼中楼与回复提醒) |

资料「完善」判定:昵称/性别/生日/城市/简介非空 + ≥1 张过审照片 → `status=complete`(否则 `incomplete`,`missing_fields` 列出缺项);`banned_light` / `banned_heavy` 为封禁状态。

## 下一步

**所有待办统一在 [docs/backlog/2026-11-03-todo.md](docs/backlog/2026-11-03-todo.md)**:按批次(A 止血 → B 准入收敛「已关闭」→ C 产品闭环 → D 规模架构 → E 工程纪律)排好序,每条都带证据、验收口径和「开新对话提示词」。**当前进度(2026-11-05):A–E 五批全部闭环,本表已无待办;剩余未闭环项是备份异地(无对象存储预算)、树莓派容量、TOTP 重绑确认与 Loki 常驻,列在 backlog §7。消息推送已明确不做(2026-11-05),不要再把它当待办重新提出。不要在本文件里另起一份待办清单。**
