# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概况

交友软件(dating app)全栈项目,技术栈:

- **前端**: Flutter(`app/`,包名 `chatapp_app`,Flutter 3.47.2)
- **后端**: Django 5.2 LTS + DRF(`chatapp/`,MySQL 8 + Redis + Celery)
- **聊天**: 腾讯云 IM 与自建 C++ IM 双后端(`IM_BACKEND` 开关;自建见 `imserver/`)
- **部署**:阿里云轻量 2C2G + 宝塔全托管(`http://<SERVER_IP>`,测试期未备案)

用户以中文交流,回复请使用中文。用户是 **Flutter/Django 新手**,偏好教学式、分步、带"为什么"的讲解。

## 文档导航(按需读取)

本文件只放核心内容。**写代码 / 排障前,先看 [docs/pitfalls/README.md](docs/pitfalls/README.md) 按主题选踩坑文档**(IM → im.md;前端 → frontend.md;后端 → backend.md;模拟器/打包含 → android-emulator.md;测试 → testing.md;网页端 → web.md)。部署与运维 → [README.md](README.md)「部署」一节。设计/计划 → `docs/superpowers/{specs,plans}/`(进度以文件内 checkbox 为准)。接口文档(对外交付级)→ [docs/api/README.md](docs/api/README.md)。

## 里程碑

M0–M3 与后续七次追加均已交付(各有 spec+plan,细节在 `docs/superpowers/` 与 git log);当前处于 M4。

| 阶段 | 一句话 |
|---|---|
| M0–M2 | 地基 / 后端全量 / 前端全量(登录→卡片→配对→IM 聊天) |
| M3 | 合规:审核台 / 举报拉黑 / 重封禁 403 / 协议弹窗 / 签名 APK |
| 后 M3 ①–③ | ops 审核台 / 封禁系统消息+消息页改版 / 微信式聊天+资料页(IM 昵称同步) |
| 后 M3 ④–⑦ | 单设备登录+造数 / 举报处理通知 / 广场页(动态流)/ 在线状态(自建 presence) |
| 2026-09-15 | 「心跳」UI 设计规则 v1(常驻强制,见下节) |
| **M4 第一步** | **服务器跑通**(宝塔全托管,IP:80 测试,双模拟器手测通过) |
| 2026-09-18 | UI 整改批次①「底座+底栏」交付(Space Grotesk/主题 token/8 组件/悬浮胶囊底栏;220 测试绿) |
| 2026-09-19 | UI 整改批次②「发现页」交付(页壳/卡面/圆钮/配对情感时刻/涟漪空态;233 测试绿) |
| 2026-09-19 | UI 整改批次③「消息/聊天」交付(消息页四态/横滑条/通知行/会话行;聊天页顶栏 62/气泡/输入栏/双气泡空态/骨架/错误重试;提炼 AppErrorView 与 AppAvatar 首字占位;247 测试绿) |
| 2026-09-21 | 接口文档体系交付(`docs/api/` 十册 · 32 接口 · 腾讯云风格;`ApiDocsCoverageTests` 双向门禁强制「改接口必改文档」) |
| 2026-10-05 | 网页端(PC Web)立项:实测否决 Flutter Web → 改 Vue 3;T1–T8 交付(壳层/鉴权/资料/发现配对/聊天/广场/设置) |
| 2026-10-12 | 网页端收尾 T9–T10:覆盖率门槛(85.6/81.0/81.2/87.4)、Playwright 端到端 8 条、Web CI、web 踩坑分册、部署核对单;期间修两个真 bug(新用户不进引导页 / `account_import` 清空 IM 昵称头像) |
| 2026-10-12 | UI 整改批次④「我的 + 他人资料页」交付(我的页身份卡+完成度环/行数 8→5;资料页照片头图+透明顶栏+相册 R12;**首次落地 §6.2 Hero 转场**——tag 按来源自身 id 派生经路由 `extra` 传递,接入广场卡/详情作者/详情评论/聊天顶栏四处;聊天顶栏补头像 32 修订附录 B.2;资料页接入在线状态;规则文档升 v1.3 附录 C;278 测试绿) |
| 2026-10-12 | UI 整改批次⑤「广场」交付(页壳大标题+涟漪空态+骨架+渐变 FAB/动态卡圆头像+九宫格 3 列+点赞脉冲/详情页自绘顶栏+44 评论栏/我的动态;**落地 §6.2 第二处 Hero「动态卡→动态详情」**——SDK 禁 Hero 嵌套 + 扫描只一次 → 状态切换双保 + `extra` 带 seed 直出真卡;删孤儿 `OnlineDot`;规则文档升 v1.4 附录 D;296 测试绿) |
| 2026-10-12 | UI 整改批次⑥「二级页」交付(**表单控件规范一次定死**:14 个 core 组件 + 2 个 feature 组件;10 页 = 登录/启动/引导/设置/黑名单/编辑资料/想找的人/发动态/协议/封禁;`AlertDialog`→`AppDialog`、`SnackBar`→`AppToast` 全量统一;抽共享 `AppSubPageBar` 取代两份私有顶栏副本;规则文档升 v1.5 附录 E;329 测试绿) |
| 2026-10-13 | 上线合规轨 T-17「账号注销入口」交付(`DELETE /users/me` = 手机号二次确认 + 立即硬删除全部数据 + 释放手机号;IM 侧新增 `account_delete` 与删号任务;App/Web 双端入口;隐私政策补注销路径、双端协议版本升 2;后端 360 / App 336 / Web 308 测试绿;PR #6 squash 合并 `f686bc2`;用户模拟器 + Web 手测通过)。同批顺带修既有偶发:`seed_fake_users` 会造出未满 18 岁账号(生日取「age 年前的随机月/日」,今年生日未过时 `calculate_age` 算成 age-1;概率约 2.2%/轮,曾把 CI 卡红) |
| 2026-10-20 | P1-1「喜欢我的人」交付(`GET /discovery/likes` + `/count`,口径与候选池共用 `likes_received_queryset`;App 发现页入口+列表页,Web `/likes` + store;回喜欢复用 `swipe`;接口 32→34,后端 392 / App 347 / Web 315 测试绿;PR #8 squash 合并 `b606f3e`) |
| 2026-10-20 | P1-2「设置页补齐」交付(新 `feedback` app + `POST /feedback` + ops 意见反馈队列;App/Web 设置页三段式 + 意见反馈页 + 通知设置只读骨架 + 关于页;版本号 App 常量守卫 / Web Vite 注入;接口 34→35,后端 409 / App 355 / Web 320 测试绿) |
| 2026-10-20 | P1-3「关系出口」交付(`DELETE /matches/{user_id}` = `Match` 软删除 + `unmatch_blacklist` 双向 IM 拉黑 + 滑卡防复活;App/Web 聊天页「⋯」+ 资料页入口 + 被解除后横幅/输入禁用;2 分钟内撤回消息(SDK 原生,双方置灰);接口 35→36,后端 420 / App 375 / Web 336 测试绿。**已读回执挂起**:腾讯 IM 旗舰版专享,当前体验版做不了) |
| 2026-10-20 | 广场评论「楼中楼」交付(`PostComment` 自引用 `parent` + `reply_to`,服务层把「回复的回复」归一到顶级评论;列表内嵌前 2 条回复 + `GET …/replies` 展开 + `DELETE …/comments/{id}` 删楼;回复即 @,IM 灰条提醒被回复者(`post_replied` 任务);App 楼层/回复态/删除 + Web 组件同步;接口 36→38,后端 440 / App 380 / Web 340 测试绿;PR #12 squash 合并 `8c428c3`;用户模拟器 + Web 手测通过) |
| 2026-10-21 | 自建 IM 交付(C++20 `imserver/`:WS 首帧 JWT 鉴权 + 会话级 seq + 幂等 + 离线补拉 + 已读/撤回/拉黑 + 内部 HMAC API;Django `IM_BACKEND` 双跑与按账号灰度;App/Web 双实现与图片入口隐藏;`GET /app/config` 最小版本拦截;接口 38→39,后端 450 / App 385 / Web 341 测试绿) |
| 2026-10-22 | 自建 IM **上服务器**:镜像 `imserver:ea8a91d` 容器化(`network_mode: host`,127.0.0.1:9100/9101),建 `chatapp_im` 库并迁移 v1;Nginx `/im/ws`+`/im/api/` 反代;Django 同步到 `ea8a91d`(git bundle,含 P1 功能与 3 个迁移);灰度 `7,8` 端到端过(鉴权/收发/ack/历史/已读/撤回/离线补拉/未读),非灰度账号仍走腾讯;部署细节见 `docs/ops/imserver.md` 与 rollout 核对单) |
| 2026-10-22 | 自建 IM **500 连接压测**:稳态 50 msg/s 经 nginx ack p99 93ms、RSS 22MB(门槛 200ms/300MB);压测暴露并修复两处服务端问题——`im_user` 每消息两次 `INSERT ... ON DUPLICATE KEY UPDATE` 的间隙锁(改进程内缓存 + `SELECT 1` 优先)、冷启动新会话并发死锁(1213/1205 重试 3 次),复测 1000 条突发 0 失败;新增 `IM_MAX_CONN_PER_IP`/`IM_AUTH_RATE`/`IM_AUTH_BURST` 与压测脚本 `imserver/scripts/bench_ws.py`) |

**下一步**:自建 IM 已上服务器并完成测试号灰度(灰度/回退见 `docs/superpowers/plans/2026-10-20-self-hosted-im-rollout.md`);全量门槛=图片二期 + 历史迁移/产品签字 + 500 连接压测 + 最小版本拦截。P1-4 推送待真机验极光 key(P1-4b 聊天推送待备案域名 + HTTPS);已读回执待 IM 升旗舰版。上线合规轨按 `2026-09-18-launch-execution.md` 并行推进 S0/S1(主体与备案由用户线下办理,Claude 侧可执行项:T-06 软著材料、T-10 隐私政策页部署、T-12 安全评估报告、T-18 备份策略、T-19 PIPIA/未成年人保护方案)。

## UI 设计规则(2026-09-15 起,常驻,强制)

**所有 App 端 UI 开发(改版/新页面/新组件/新动效)一律遵循「心跳」设计规则**:`docs/superpowers/specs/2026-09-15-ui-design-language-design.md`(v1.5,已获用户批准)。动手前先读它,要点:

- 色板/渐变/字阶/圆角/间距/动效时长全走 token,**禁止新代码出现裸 hex、裸字号、裸间距**(页面改造时顺手按文档 §2.3 对照表清理旧硬编码)
- 主色 #FF2C55 + 心跳渐变(粉→橙)只出现在引导视线处(主按钮/选中/未读/配对/在线光),其余走三级中性色阶
- 字体:全局 Space Grotesk(拉丁/数字)+ 中文系统 fallback;图标统一 Material `*_rounded` 变体
- 动效三档(微交互/结构/情感),尊重 reduced-motion;不做纯装饰动画
- 旧视觉专项(微信式聊天/抖音式消息页/微博式广场)与「心跳」冲突处一律作废,以「心跳」为准;页面改造分批立项(① 底座+底栏 2026-09-18、② 发现 2026-09-19、③ 消息/聊天 2026-09-19 均已交付),顺序:①底座+底栏 → ②发现 → ③消息/聊天 → ④我的/资料 → ⑤广场 → ⑥二级页

## 目录结构

| 路径 | 内容 | 说明 |
|---|---|---|
| `app/` | Flutter 应用 | `lib/core/`(网络/错误/凭证)、`lib/im/`(IM 抽象层)、`lib/router.dart`(go_router 路由表)、`lib/features/{auth,onboarding,discovery,chat,profile,settings,shell,square,presence,legal}`;测试是"真实 provider + 假网络 + 假 IM":`test/support/scripted_adapter.dart` + `test/support/harness.dart` 的 `pumpApp` + `test/support/fake_im_client.dart` |
| `chatapp/` | Django 项目(`manage.py` 所在层) | `config/` 项目包 + 业务 app:`accounts users discovery im moderation ops feed notifications feedback`;敏感配置读 `chatapp/.env`(gitignored,模板见 `.env.example`) |
| `flutter/` | **Flutter SDK 源码**(自带独立 .git) | 这是 SDK,不是应用代码,**切勿修改、勿提交**;命令用 `flutter/bin/flutter.bat` |
| `web/` | 网页端(Vue 3 SPA) | `src/{api,stores,im,components,layouts,features}`;开发 `npm run dev`(代理到 :8000),构建 `npm run build`;**只服务 PC 浏览器**,移动端按 UA 进引导页 |
| `imserver/` | 自建 IM(C++20) | WS :9100 + HTTP :9101;MySQL `chatapp_im` + Redis DB2;测试 `docker compose -f imserver/docker-compose.test.yml run --rm test bash /src/scripts/test_http.sh` |
| `docs/superpowers/` | 设计 spec 与实施计划 | 计划的执行进度以文件内 checkbox 为准 |
| `docs/pitfalls/` | 踩坑手册(按主题分册) | 写代码/排障前按需读取 |
| `.remember/` | Claude 会话记忆日志(内部机制) | 勿改动、勿提交 |

根目录是 git 仓库;`master` 为主线,功能开发走短生命周期分支后合回。

## 常用命令

**后端**(cwd = `chatapp/`,Python 用 anaconda 环境 `Django`):
```bash
python manage.py test              # 全量(前置:Redis 在跑,见下)
python manage.py test accounts     # 单 app
python manage.py runserver         # 开发服务器 :8000
python manage.py makemigrations && python manage.py migrate
python manage.py im_send --from u2 --to u3 --text "你好"   # 手测:代发消息(--notice 发灰条)
python manage.py dev_reset_pair --a u8 --b u9              # 手测:清滑卡/配对重演(不清聊天记录)
python manage.py seed_fake_users --count 20                # 造数(幂等;直调 IM 同步,不必等 worker)
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
cd app && ../flutter/bin/flutter.bat build apk --release --dart-define=API_BASE=http://<SERVER_IP>/api/v1
```
产物 `app/build/app/outputs/flutter-apk/app-release.apk`。

**服务器**:`ssh root@<SERVER_IP>`(免密);部署形态与更新流程见 [README.md](README.md)「部署」。服务器私有的运维手册(面板口令/路径/端口)不入库,本地保留。

## 核心契约与纪律

- **错误契约**:成功 2xx + 资源 JSON;失败一律 `{"code": <HTTP状态码>, "message": "<中文>", "request_id": ...}`;业务码=前 3 位 HTTP + 2 位序号(`config/error_codes.py`)
- **鉴权**:Bearer JWT(access 30min / refresh 30d,刷新即轮换、旧进黑名单);JWT `user_id` claim 是**字符串**;`GET /users/me` 响应 `id` 是 **profile 表主键**,账号 ID 看 `user_id`
- **响应路径禁止任何第三方网络调用**(requests/腾讯 REST/短信商);跨系统副作用一律走 Celery 任务;`transaction.on_commit(fn, robust=True)` 的语义是「DB 提交后」
- **IM 副作用唯一入口 `im/tasks.py`**(任务参数一律 user_id,任务内查库;任务体内不查 request);`im/client.py` 与 `im/self_client.py` 对外永不抛异常;`.env` **禁用 `CELERY_` 前缀键**(用 `BROKER_URL`)。唯一例外:`im/tasks.py::delete_account` 的参数是 `im_user_id` 字符串 —— 它在用户行删除后入队,任务内查库必然拿到 `None`,详见 `docs/pitfalls/backend.md`「账号注销」
- **自建 IM**:`IM_BACKEND=tencent|self`;`im/client.py` 按账号灰度分发到 `im/self_client.py`;灰度名单只能放隔离测试号(跨后端消息不通);`imserver/` 的 WS/HTTP 端口、JWT/HMAC 密钥与 Django `.env` 必须一致
- **跨栈约定**:IM 账号 = `u{user_id}`(`accounts/models.py::im_user_id`);`system_notice` 相关常量两边别单改
- **单设备登录**:一个账号同时只允许一台设备在线;被顶设备收 **401 + `40101`**(三条退出路径互为兜底,细节见 pitfalls)
- **封禁两级**:`banned_light` 只禁滑卡;`banned_heavy` 全域 403——全局权限类自动覆盖新接口,白名单仅 `GET /users/me`、`GET /users/tags`
- **在线状态是公开信息**(不依赖配对);「在线」= 120 秒内有认证请求(45s 心跳)
- **前端**:401 只走 `AuthInterceptor` 刷新通道;错误统一 `ApiException`;写操作后检查相关 provider 失效
- **网页端**:401 只走 `api/http.ts` 的刷新通道(并发去重);错误统一 `ApiError`;页面只碰 store、不直接调 `http`
- **「心跳」token 双份维护**:改任何视觉 token 或字体,**必须在同一次改动内同时改** `app/lib/core/theme/*.dart` 与 `web/src/styles/tokens.css`(`web/public/fonts/*` 与 `app/assets/fonts/*` 保持一致);`web/tests/unit/tokens.spec.ts` 与 `fonts.spec.ts` 会双向比对,漏改即红
- **测试纪律**:后端全量绿(前置 Redis)+ `flutter analyze` 零告警;IM 一律 mock(`im.tasks.*.delay`);每步全绿再进下一步
- **网页端测试纪律**:`vue-tsc` 零错误 + `eslint --max-warnings 0` 零告警 + vitest 全绿(覆盖率门槛 70/60/70/70);`npm run e2e` 需后端 + Redis + Celery 都在跑,不进 CI
- **接口文档**:`docs/api/` 是接口的对外交付文档;新增/修改/删除任何 `/api/v1` 接口,**同一次改动内**必须同步更新对应分册;`python manage.py test` 会跑 `ApiDocsCoverageTests` 双向比对,漏写即红。模板与维护规则见 `docs/api/README.md`
- **注释规范**:`docs/standards/python.md` 是 Python 注释的单一事实来源;新增/修改任何 `.py` 文件,**同一次改动内**必须补齐模块 docstring 与函数/类 docstring(`test_*` 用例、`setUp` 等生命周期钩子、`Meta` 声明式内部类、函数内闭包豁免),**公开函数带参数必须写 `Args:` 小节**;`python manage.py test` 会跑 `CommentCoverageTests` 比对,漏写即红。本地快速自查:`cd chatapp && python config/comment_coverage.py`(秒级,不依赖 Django),`--warnings` 看口语词提示、`--structure` 看 `Args` 结构提示(均不拦截)

## 后端接口

- 鉴权:`Authorization: Bearer <access>`(JWT);开发期验证码固定 `123456`(`SMS_DEV_MODE=1`)

| 接口 | 说明 |
|---|---|
| `POST /auth/sms/send` | 发验证码;同号 60 秒重发间隔(42901,带 Retry-After);IP 限流;入队失败回滚并 503(50301) |
| `POST /auth/sms/verify` | 校验并登录(号码没注册过自动建号)→ `{access, refresh, is_new_user, user_id}`;连错 5 次锁 15 分钟(42902);60 秒幂等重放窗口 |
| `POST /auth/token/refresh` | 刷新 access(响应同时给新 refresh) |
| `GET/PATCH/DELETE /users/me` | 我的资料(昵称/性别/生日/城市/简介/`tag_ids`);未满 18 岁 400;`id`=profile 主键。**DELETE = 注销账号**:body 带 `phone` 二次确认,立即硬删除全部数据 + 释放手机号(同号可重注册为全新账号);重封禁 403 |
| `GET /users/tags` | 标签池(12 个,数据迁移写入) |
| `POST /users/me/photos`、`DELETE /users/me/photos/{id}` | 照片(multipart 字段 `file`;最多 6 张、≤5MB);`AUTO_APPROVE=1` 上传即过审 |
| `GET/PATCH /users/me/preference` | 想找的人:目标性别(可空=不限)/ 年龄区间 / 城市 |
| `POST /im/user_sig` | 取 IM 登录凭证(腾讯 `user_sig` / 自建 `token` 双分支);`banned_heavy` 403 |
| `GET /app/config` | 公开;最低版本配置(启动时拦截旧版本) |
| `GET /discovery/candidates` | 候选卡(默认 10、上限 20);排除自己/划过/已配对/资料未完善;**只推有已过审照片的人** |
| `POST /discovery/swipe` | `{target_user_id, action: like\|pass}`;幂等;互喜 → `{"matched": true}` + 双方灰条;限流 300/小时 |
| `GET /discovery/likes` | 喜欢我的人(分页);口径与候选池一致,排除我已划过/双向拉黑/资料不全/无过审照片 |
| `GET /discovery/likes/count` | 喜欢我的人数(入口角标);与列表同口径 |
| `GET /matches` | 配对列表(分页);预热 userId→昵称头像缓存 |
| `DELETE /matches/{user_id}` | 解除配对:幂等 204;软删除 + 双向 IM 拉黑,不可恢复 |
| `POST /feedback` | 意见反馈(10–500 字 + 可选联系方式;限流 5/小时) |
| `/posts` 系列、`POST /reports`、`GET/POST/DELETE /blocks`、`GET /presence` | 广场 / 举报 / 拉黑 / 在线状态,细节见各 spec 与 pitfalls(评论支持两级楼中楼与回复提醒) |

资料「完善」判定:昵称/性别/生日/城市/简介非空 + ≥1 张过审照片 → `status=complete`(否则 `incomplete`,`missing_fields` 列出缺项);`banned_light` / `banned_heavy` 为封禁状态。
