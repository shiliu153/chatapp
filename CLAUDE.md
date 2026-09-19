# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概况

交友软件(dating app)全栈项目,技术栈:

- **前端**: Flutter(`app/`,包名 `chatapp_app`,Flutter 3.47.2)
- **后端**: Django 5.2 LTS + DRF(`chatapp/`,MySQL 8 + Redis + Celery)
- **聊天**: 腾讯云 IM SDK(消息走腾讯云 IM,业务数据存 Django)
- **部署**:阿里云轻量 2C2G + 宝塔全托管(`http://<SERVER_IP>`,测试期未备案)

用户以中文交流,回复请使用中文。用户是 **Flutter/Django 新手**,偏好教学式、分步、带"为什么"的讲解。

## 文档导航(按需读取)

本文件只放核心内容。**写代码 / 排障前,先看 [docs/pitfalls/README.md](docs/pitfalls/README.md) 按主题选踩坑文档**(IM → im.md;前端 → frontend.md;后端 → backend.md;模拟器/打包含 → android-emulator.md;测试 → testing.md)。部署与运维 → [docs/deploy-runbook.md](docs/deploy-runbook.md)。设计/计划 → `docs/superpowers/{specs,plans}/`(进度以文件内 checkbox 为准)。

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

**下一步(M4 续)**:按 [上线执行流程表](docs/superpowers/plans/2026-09-18-launch-execution.md)(方案 A 双轨并行)推进——免费版 3~4 个月上架,ICP 证并行办理后开付费;预算/资质细节见 [上线总纲 spec](docs/superpowers/specs/2026-09-18-launch-compliance-budget-design.md)。

## UI 设计规则(2026-09-15 起,常驻,强制)

**所有 App 端 UI 开发(改版/新页面/新组件/新动效)一律遵循「心跳」设计规则**:`docs/superpowers/specs/2026-09-15-ui-design-language-design.md`(v1,已获用户批准)。动手前先读它,要点:

- 色板/渐变/字阶/圆角/间距/动效时长全走 token,**禁止新代码出现裸 hex、裸字号、裸间距**(页面改造时顺手按文档 §2.3 对照表清理旧硬编码)
- 主色 #FF2C55 + 心跳渐变(粉→橙)只出现在引导视线处(主按钮/选中/未读/配对/在线光),其余走三级中性色阶
- 字体:全局 Space Grotesk(拉丁/数字)+ 中文系统 fallback;图标统一 Material `*_rounded` 变体
- 动效三档(微交互/结构/情感),尊重 reduced-motion;不做纯装饰动画
- 旧视觉专项(微信式聊天/抖音式消息页/微博式广场)与「心跳」冲突处一律作废,以「心跳」为准;页面改造分批立项(① 底座+底栏 2026-09-18、② 发现 2026-09-19、③ 消息/聊天 2026-09-19 均已交付),顺序:①底座+底栏 → ②发现 → ③消息/聊天 → ④我的/资料 → ⑤广场 → ⑥二级页

## 目录结构

| 路径 | 内容 | 说明 |
|---|---|---|
| `app/` | Flutter 应用 | `lib/core/`(网络/错误/凭证)、`lib/im/`(IM 抽象层)、`lib/router.dart`(go_router 路由表)、`lib/features/{auth,onboarding,discovery,chat,profile,settings,shell,square,presence,legal}`;测试是"真实 provider + 假网络 + 假 IM":`test/support/scripted_adapter.dart` + `test/support/harness.dart` 的 `pumpApp` + `test/support/fake_im_client.dart` |
| `chatapp/` | Django 项目(`manage.py` 所在层) | `config/` 项目包 + 业务 app:`accounts users discovery im moderation ops feed notifications`;敏感配置读 `chatapp/.env`(gitignored,模板见 `.env.example`) |
| `flutter/` | **Flutter SDK 源码**(自带独立 .git) | 这是 SDK,不是应用代码,**切勿修改、勿提交**;命令用 `flutter/bin/flutter.bat` |
| `docs/superpowers/` | 设计 spec 与实施计划 | 计划的执行进度以文件内 checkbox 为准 |
| `docs/pitfalls/` | 踩坑手册(按主题分册) | 写代码/排障前按需读取 |
| `docs/deploy-runbook.md` | 服务器部署与运维手册 | 更新六步 / 常见操作 / 上线待办 |
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

**出签名包**(keystore `C:\Users\you\chatapp-release.jks`,口令在 `app/android/key.properties`;两个文件都不入库,务必备份):
```bash
cd app && ../flutter/bin/flutter.bat build apk --release --dart-define=API_BASE=http://<SERVER_IP>/api/v1
```
产物 `app/build/app/outputs/flutter-apk/app-release.apk`。

**服务器**:`ssh root@<SERVER_IP>`(免密);更新流程、看日志、排障一律先看 `docs/deploy-runbook.md`。

## 核心契约与纪律

- **错误契约**:成功 2xx + 资源 JSON;失败一律 `{"code": <HTTP状态码>, "message": "<中文>", "request_id": ...}`;业务码=前 3 位 HTTP + 2 位序号(`config/error_codes.py`)
- **鉴权**:Bearer JWT(access 30min / refresh 30d,刷新即轮换、旧进黑名单);JWT `user_id` claim 是**字符串**;`GET /users/me` 响应 `id` 是 **profile 表主键**,账号 ID 看 `user_id`
- **响应路径禁止任何第三方网络调用**(requests/腾讯 REST/短信商);跨系统副作用一律走 Celery 任务;`transaction.on_commit(fn, robust=True)` 的语义是「DB 提交后」
- **IM 副作用唯一入口 `im/tasks.py`**(任务参数一律 user_id,任务内查库;任务体内不查 request);`im/client.py` 对外永不抛异常;`.env` **禁用 `CELERY_` 前缀键**(用 `BROKER_URL`)
- **跨栈约定**:IM 账号 = `u{user_id}`(`accounts/models.py::im_user_id`);`system_notice` 相关常量两边别单改
- **单设备登录**:一个账号同时只允许一台设备在线;被顶设备收 **401 + `40101`**(三条退出路径互为兜底,细节见 pitfalls)
- **封禁两级**:`banned_light` 只禁滑卡;`banned_heavy` 全域 403——全局权限类自动覆盖新接口,白名单仅 `GET /users/me`、`GET /users/tags`
- **在线状态是公开信息**(不依赖配对);「在线」= 120 秒内有认证请求(45s 心跳)
- **前端**:401 只走 `AuthInterceptor` 刷新通道;错误统一 `ApiException`;写操作后检查相关 provider 失效
- **测试纪律**:后端全量绿(前置 Redis)+ `flutter analyze` 零告警;IM 一律 mock(`im.tasks.*.delay`);每步全绿再进下一步

## 后端接口

- 鉴权:`Authorization: Bearer <access>`(JWT);开发期验证码固定 `123456`(`SMS_DEV_MODE=1`)

| 接口 | 说明 |
|---|---|
| `POST /auth/sms/send` | 发验证码;同号 60 秒重发间隔(42901,带 Retry-After);IP 限流;入队失败回滚并 503(50301) |
| `POST /auth/sms/verify` | 校验并登录(号码没注册过自动建号)→ `{access, refresh, is_new_user, user_id}`;连错 5 次锁 15 分钟(42902);60 秒幂等重放窗口 |
| `POST /auth/token/refresh` | 刷新 access(响应同时给新 refresh) |
| `GET/PATCH /users/me` | 我的资料(昵称/性别/生日/城市/简介/`tag_ids`);未满 18 岁 400;`id`=profile 主键 |
| `GET /users/tags` | 标签池(12 个,数据迁移写入) |
| `POST /users/me/photos`、`DELETE /users/me/photos/{id}` | 照片(multipart 字段 `file`;最多 6 张、≤5MB);`AUTO_APPROVE=1` 上传即过审 |
| `GET/PATCH /users/me/preference` | 想找的人:目标性别(可空=不限)/ 年龄区间 / 城市 |
| `POST /im/user_sig` | 取 IM userSig;`banned_heavy` 403 |
| `GET /discovery/candidates` | 候选卡(默认 10、上限 20);排除自己/划过/已配对/资料未完善;**只推有已过审照片的人** |
| `POST /discovery/swipe` | `{target_user_id, action: like\|pass}`;幂等;互喜 → `{"matched": true}` + 双方灰条;限流 300/小时 |
| `GET /matches` | 配对列表(分页);预热 userId→昵称头像缓存 |
| `/posts` 系列、`POST /reports`、`GET/POST/DELETE /blocks`、`GET /presence` | 广场 / 举报 / 拉黑 / 在线状态,细节见各 spec 与 pitfalls |

资料「完善」判定:昵称/性别/生日/城市/简介非空 + ≥1 张过审照片 → `status=complete`(否则 `incomplete`,`missing_fields` 列出缺项);`banned_light` / `banned_heavy` 为封禁状态。
