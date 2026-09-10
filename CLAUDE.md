# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概况

交友软件(dating app)全栈项目,技术栈:

- **前端**: Flutter(`app/`,包名 `chatapp_app`)
- **后端**: Django 5.2 LTS + DRF(`chatapp/`,MySQL)
- **聊天**: 腾讯云 IM SDK(消息走腾讯云 IM,业务数据存 Django)

**当前进度:M0 地基已完成**(Django 骨架 + MySQL 迁移 + `/api/v1/health` 前后端握手 + IM 凭据验证)。
设计与计划文档在 `docs/superpowers/`(spec: `specs/2026-09-09-dating-app-mvp-design.md`;M0 计划: `plans/2026-09-09-m0-foundation.md`)。下一步是 M1(后端业务全量:账号/资料/滑卡配对/IM)。

用户以中文交流,回复请使用中文。用户是 **Flutter/Django 新手**,偏好教学式、分步、带"为什么"的讲解。

## 目录结构

| 路径 | 内容 | 说明 |
|---|---|---|
| `app/` | Flutter 应用(Flutter 3.47.2) | `lib/core/api_client.dart` 是网络层起点;测试用 `test/fake_adapter.dart` 离线假适配器 |
| `chatapp/` | Django 项目(`manage.py` 所在层) | `config/` 项目包 + 5 个业务 app:`accounts users discovery im moderation`;敏感配置读 `chatapp/.env`(gitignored,模板见 `.env.example`) |
| `flutter/` | **Flutter SDK 源码**(自带独立 .git) | 这是 SDK,不是应用代码,**切勿修改、勿提交**;命令用 `flutter/bin/flutter.bat` |
| `docs/superpowers/` | 设计 spec 与实施计划 | 计划的执行进度以文件内 checkbox 为准 |
| `.remember/` | Claude 会话记忆日志(内部机制) | 勿改动、勿提交 |

根目录是 git 仓库;`master` 为主线,功能开发走短生命周期分支后合回。

## 常用命令

**后端**(Python 用 anaconda 环境 `Django`,Python 3.10;cwd = `chatapp/`):
```bash
python manage.py test              # 全量测试(测试库 test_chatapp_dev,授权在 db_setup.sql)
python manage.py test accounts     # 单 app 测试
python manage.py runserver         # 开发服务器 :8000
python manage.py makemigrations && python manage.py migrate
```

**前端**(cwd = `app/`):
```bash
../flutter/bin/flutter.bat analyze   # 必须零告警
../flutter/bin/flutter.bat test
../flutter/bin/flutter.bat run -d chrome            # 或 -d windows
../flutter/bin/flutter.bat run -d web-server --web-port 5173   # 无头验证用
```

**MySQL**:本机 MySQL 8.0,库 `chatapp_dev`,用户 `chatapp`(口令在 `.env`)。建库/授权脚本 `chatapp/db_setup.sql`(可重复执行)。

## 国内镜像(Android 构建,已实测通过)

Google 源在国内不可直连,以下配置已就位(2026-09-10 `flutter build apk --debug` 全链路验证成功):

- Gradle 发行版:`app/android/gradle/wrapper/gradle-wrapper.properties` → 腾讯云镜像
- Maven 依赖:`app/android/settings.gradle.kts` 与 `build.gradle.kts` 中阿里云镜像优先(google/public/gradle-plugin 三个仓库),官方源兜底
- Flutter 引擎工件:用户级环境变量 `FLUTTER_STORAGE_BASE_URL=https://storage.flutter-io.cn`(**勿删**;新开终端/IDE 才生效)
- pub 无需镜像(直连 pub.dev 正常);若 pub 变慢可临时用 `PUB_HOSTED_URL=https://pub.flutter-io.cn`,注意它会把镜像地址写进 `pubspec.lock`

## 腾讯云 IM 集成要点(已实测)

- 凭据:`IM_SDKAPPID=1600161711`(公开,App 端也要用),密钥只在 `chatapp/.env`,**永不入代码/提交**。管理员账号 `administrator` 默认存在。
- **userSig 生成是最大的坑**:腾讯用自家的 base64 变体,不是标准/URL-safe base64。正确流程:构建 JSON(ver/identifier/sdkappid/expire/time,sig 用**标准** base64 的 HMAC-SHA256)→ `json.dumps` → `zlib.compress` → 标准 base64 后替换 `+`→`*`、`/`→`-`、`=`→`_`。字符串会以 `*` `-` `_` 出现且不 strip 填充。2026-09-10 已用 REST `im_open_login_svc/account_check` 实测通过。
- REST API 调用格式:`https://console.tim.qq.com/v4/{service}/{command}?sdkappid=&identifier=&usersig=&random=&contenttype=json`(usersig 需 URL 编码)。
- Flutter 端 IM SDK 包:`tim_plus_flutter`(M2 引入)。
- 详细设计(配对灰条消息、会话列表数据源、审核合规)见 spec 文档,写 IM 相关代码前先读它。
