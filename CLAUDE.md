# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概况

交友软件(dating app)全栈项目,技术栈:

- **前端**: Flutter(`app/`,包名 `chatapp_app`)
- **后端**: Django 5.2 LTS + DRF(`chatapp/`,MySQL)
- **聊天**: 腾讯云 IM SDK(消息走腾讯云 IM,业务数据存 Django)

**当前进度:M2a 已完成**(M0 地基 + M1 后端全量 + M2a 前端:依赖与 core(401 静默刷新拦截器)、会话状态/启动鉴权、验证码登录页、三 Tab 主框架、3 步资料引导(昵称/性别/生日/城市/简介/标签/照片)、我的资料+编辑、偏好设置、退出登录;前端 37 测试全绿 + analyze 零告警,后端 91 测试回归通过,模拟器联调通过)。
设计与计划文档在 `docs/superpowers/`(spec: `specs/2026-09-09-dating-app-mvp-design.md`;M0: `plans/2026-09-09-m0-foundation.md`;M1a: `plans/2026-09-10-m1a-auth-profile.md`;M1b: `plans/2026-09-10-m1b-im-discovery.md`;M2a: `plans/2026-09-10-m2a-auth-onboarding.md`,checkbox 全勾)。**下一步 M2b**(发现卡片流 → 配对动效,M2c:IM SDK → 会话列表 → 聊天页灰条;接口约定见 M2a 计划末尾的「留给 M2b / M2c 的接口约定」表)。

用户以中文交流,回复请使用中文。用户是 **Flutter/Django 新手**,偏好教学式、分步、带"为什么"的讲解。

## 目录结构

| 路径 | 内容 | 说明 |
|---|---|---|
| `app/` | Flutter 应用(Flutter 3.47.2) | `lib/core/`(网络/错误/凭证)、`lib/router.dart`(go_router 路由表)、`lib/features/{auth,onboarding,discovery,chat,profile,settings,shell}`;测试是"真实 provider + 假网络":`test/support/scripted_adapter.dart` + `test/support/harness.dart` 的 `pumpApp` |
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
../flutter/bin/flutter.bat test test/core          # 单目录跑
../flutter/bin/flutter.bat run -d chrome            # 或 -d windows
../flutter/bin/flutter.bat run -d web-server --web-port 5173   # 无头验证用
```

**MySQL**:本机 MySQL 8.0,库 `chatapp_dev`,用户 `chatapp`(口令在 `.env`)。建库/授权脚本 `chatapp/db_setup.sql`(可重复执行)。

## 后端接口(M1a 已实现)

- 鉴权:`Authorization: Bearer <access>`(JWT);access 30 分钟 / refresh 30 天,刷新即轮换且旧的进黑名单(先用先失效)
- **成功**:HTTP 2xx + 资源 JSON;**失败**:一律 `{"code": <HTTP状态码>, "message": "<中文提示>"}`(全局异常处理器 `chatapp/config/exceptions.py`)
- JWT 的 `user_id` claim 是**字符串**(SimpleJWT 行为),前端与自家 id 比对时记得转 int

| 接口 | 说明 |
|---|---|
| `POST /auth/sms/send` | 发验证码;开发期固定 `123456`(开关 `SMS_DEV_MODE`),同号 60 秒重发间隔,IP 限流 20/小时 |
| `POST /auth/sms/verify` | 校验并登录(号码没注册过则自动建号)→ `{access, refresh, is_new_user, user_id}`;连错 5 次锁 15 分钟 |
| `POST /auth/token/refresh` | 刷新 access(响应里同时给新 refresh) |
| `GET/PATCH /users/me` | 我的资料;PATCH 可改 昵称/性别/生日/城市/简介/`tag_ids`,未满 18 岁生日直接 400 |
| `GET /users/tags` | 标签池(12 个,由数据迁移 `users/0002_seed_tags.py` 写入) |
| `POST /users/me/photos`、`DELETE /users/me/photos/{id}` | 照片(multipart 字段名 `file`;最多 6 张、≤5MB);开发期 `AUTO_APPROVE=1` 上传即过审 |
| `GET/PATCH /users/me/preference` | 想找的人:目标性别(可空=不限)/年龄区间/城市 |
| `POST /im/user_sig` | 取 IM 登录用 userSig → `{user_sig, sdkappid, im_user_id, expire}`;`banned_heavy` 403 |
| `GET /discovery/candidates` | 候选卡片(默认 10、上限 20);排除自己/划过/已配对/资料未完善;**只推有已过审照片的人** |
| `POST /discovery/swipe` | `{target_user_id, action: like\|pass}`;幂等;互喜 → `{"matched": true}` 并给双方发 IM 灰条;按用户限流 300/小时 |
| `GET /matches` | 配对列表(`user_id/im_user_id/nickname/avatar_url/matched_at`),M2 用来预热"userId→昵称头像"本地缓存 |

资料「完善」判定:昵称/性别/生日/城市/简介非空 + ≥1 张过审照片 → `status=complete`,否则 `incomplete`(接口返回的 `missing_fields` 会列出缺项);`banned_light` / `banned_heavy` 状态预留封禁用(M1b/M3)。

⚠️ **Git Bash 里 curl 发中文会 400**:`curl -d '{"昵称":...}'` 按本地 GBK 码页发出,服务端 UTF-8 解析失败(不是后端 bug)。冒烟测试用纯 ASCII,或把 JSON 写成 UTF-8 文件后 `--data-binary @file`。

## 国内镜像(Android 构建,已实测通过)

Google 源在国内不可直连,以下配置已就位(2026-09-10 `flutter build apk --debug` 全链路验证成功):

- Gradle 发行版:`app/android/gradle/wrapper/gradle-wrapper.properties` → 腾讯云镜像
- Maven 依赖:`app/android/settings.gradle.kts` 与 `build.gradle.kts` 中阿里云镜像优先(google/public/gradle-plugin 三个仓库),官方源兜底
- Flutter 引擎工件:用户级环境变量 `FLUTTER_STORAGE_BASE_URL=https://storage.flutter-io.cn`(**勿删**;新开终端/IDE 才生效)
- pub 无需镜像(直连 pub.dev 正常);若 pub 变慢可临时用 `PUB_HOSTED_URL=https://pub.flutter-io.cn`,注意它会把镜像地址写进 `pubspec.lock`

## Android 模拟器测试

- 模拟器设备:`emulator-5554`(sdk gphone16k x86_64,Android 17 / API 37)
- 运行:`../flutter/bin/flutter.bat run -d emulator-5554 --dart-define=API_BASE=http://10.0.2.2:8000/api/v1`(模拟器里 `10.0.2.2` = 宿主机回环;`.env` 的 ALLOWED_HOSTS 已含它)
- 截图验证:`"$LOCALAPPDATA/Android/Sdk/platform-tools/adb.exe" -s emulator-5554 exec-out screencap -p > shot.png`
- 模拟器相册默认是空的:要测照片上传,先 `adb push 本地图.png /sdcard/Pictures/x.png` 并触发媒体扫描(`adb shell am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file:///sdcard/Pictures/x.png`),或改用 `-d windows` 走文件选择
- ⚠️ **只保留一个 runserver 进程**:Windows 下多个 runserver 可同时绑定 8000,旧进程会拿旧配置抢答(踩过:旧 ALLOWED_HOSTS 导致 400)。排查:`netstat -ano | grep :8000`,再用 `Get-CimInstance Win32_Process` 看 PID 的启动时间和命令行

## 腾讯云 IM 集成要点(已实测)

- 凭据:`IM_SDKAPPID=1600161711`(公开,App 端也要用),密钥只在 `chatapp/.env`,**永不入代码/提交**。管理员账号 `administrator` 默认存在。
- **代码位置**:userSig 生成在 `chatapp/im/signature.py`(含 `decode_user_sig` 调试解码);REST 调用在 `chatapp/im/client.py`(`import_account` / `send_custom_elem` / `send_match_notice`,**对外永不抛异常**,失败返回 False 只记日志)。
- **userSig 生成是最大的坑**:腾讯用自家的 base64 变体,不是标准/URL-safe base64。正确流程:构建 JSON(ver/identifier/sdkappid/expire/time,sig 用**标准** base64 的 HMAC-SHA256)→ `json.dumps` → `zlib.compress` → 标准 base64 后替换 `+`→`*`、`/`→`-`、`=`→`_`。字符串会以 `*` `-` `_` 出现且不 strip 填充。2026-09-10 由 `im/client.py` 实测通过。
- REST API 调用格式:`https://console.tim.qq.com/v4/{service}/{command}?sdkappid=&identifier=&usersig=&random=&contenttype=json`(usersig 需 URL 编码)。
- ⚠️ **`openim/sendmsg` 的 `identifier` 必须是管理员**(`administrator`),发送方靠 body 的 `From_Account` 指定;错用发送方身份会报 `60010 set the identifier field ... to the admin account`。2026-09-10 实测修正。
- ⚠️ **`im_open_login_svc/account_check` 别用来验签**:本应用下它对任何参数组合都返回 `70402 Invalid parameters`(与签名无关,同一签名调 `account_import` 返回 0)。验签一律用 `account_import`。
- **配对灰条消息**:配对成功时 `send_match_notice(a, b)` 给**双方各发一条** `TIMCustomElem`,`MsgContent.Data` = `{"type":"match_notice"}`,`Desc` = "你们已互相喜欢,开始聊天吧"(M2 端拦截该类型渲染成居中灰条,会话随之创建)。
- 账号导入:注册成功后经 `transaction.on_commit` 调 `account_import(u{id})`,失败只记日志不阻塞注册。
- Flutter 端 IM SDK 包:`tim_plus_flutter`(M2c 引入)。
- 详细设计(配对灰条消息、会话列表数据源、审核合规)见 spec 文档,写 IM 相关代码前先读它。

## 前端约定与踩坑(M2a 已实测)

- **分层**:repository(纯 IO,JSON → 模型)→ Riverpod controller(会话/资料状态)→ widget;路由表在 `lib/router.dart`,按 `SessionState`(sealed)重定向:splash → 登录页 → 主框架
- **鉴权**:`AuthInterceptor` 自动带 Bearer;401 → 用**裸 Dio** 静默刷新一次 → 重放原请求;刷新也失败就 `TokenStore.clear()`,它的通知让 `SessionController` 把人踢回登录页 —— 这是"会话过期"的唯一传播通道,别在页面里各自处理 401
- **错误**:所有接口错误统一抛 `ApiException`(message 就是后端的中文提示);页面用 SnackBar 展示,网络错误有兜底文案
- **接口地址**:`--dart-define=API_BASE=...`;桌面/Web 默认 `http://127.0.0.1:8000/api/v1`,模拟器用 `http://10.0.2.2:8000/api/v1`
- **测试纪律**:widget 测试用 `test/support/harness.dart` 的 `pumpApp`(假网络按 `"METHOD path"` 铺响应,没铺的路由返回 404 提示你);有倒计时/轮询的页面别用 `pumpAndSettle`(永不 settle),测试尾部 `await tester.pumpWidget(const SizedBox())` 卸载页面取消 Timer
- **Riverpod 3.4 注意**:`AsyncValue.valueOrNull` 已移除,用 `.value`(可空);测试辅助函数别叫 `fail`(与 flutter_test 自带 `fail()` 撞名)
- ⚠️ Windows 上 `pub add` 插件后提示 "requires symlink support"(需开发者模式)——**Android/Web 构建不受影响**;桌面 `-d windows` 需要开启系统开发者模式
- ⚠️ **`app/android/gradle.properties` 里的 `kotlin.incremental=false` 勿删**:pub 缓存在 C 盘、工程在 D 盘,Kotlin 增量编译缓存算跨盘相对路径会崩(`Could not close incremental caches ... different roots`),关掉增量编译是官方 workaround
- 照片上传走 `readAsBytes` + `MultipartFile.fromBytes`(Web 上 `XFile.path` 是 blob URL,不能用 `fromFile`);单张 ≤5MB 前端先拦

## 后端测试注意事项

- **测 on_commit**:`notify_match` / 注册导入都走 `transaction.on_commit`,测试里必须 `with self.captureOnCommitCallbacks(execute=True):` 包住请求,否则断言永远不触发。
- **凡是会触发 IM 调用的用例都要 mock**:漏 mock 会真打腾讯云(用例仍会绿,因为业务函数吞异常 —— 靠跑测试时日志里有没有 `IM ... 返回错误` 来发现),且变慢、依赖网络。
- 限流用例要 `cache.clear()`:限流计数存在 Django 缓存(LocMem)里,跨用例残留会导致偶发 429。
