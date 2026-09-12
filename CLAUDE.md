# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概况

交友软件(dating app)全栈项目,技术栈:

- **前端**: Flutter(`app/`,包名 `chatapp_app`)
- **后端**: Django 5.2 LTS + DRF(`chatapp/`,MySQL)
- **聊天**: 腾讯云 IM SDK(消息走腾讯云 IM,业务数据存 Django)

**当前进度:M3 已完成**(M0 地基 + M1 后端全量 + M2a 前端登录/引导 + M2b 发现卡片流 + M2c IM 接入 + M3 合规收尾:moderation 三模型与 Django admin 审核台、举报/拉黑全链路(含 IM 黑名单同步与踢下线)、重封禁全域 403、首启协议弹窗与协议全文、Android 签名 APK;后端 153 测试、前端 115 测试全绿,analyze 零告警)。核心链路(登录/互滑/聊天/资料卡/举报/拉黑)已双端手测;协议、照片审核、封禁页等细节项待后续补验。

**M3 后追加:运营审核台 `/ops/`**(独立 Django app `ops`,is_staff 登录;举报处理 / 照片审核(含 reviewed_by/at 审计)/ 用户封禁解封 / 操作日志;后端测试 180 全绿。设计: `specs/2026-09-11-moderation-console-design.md`;计划: `plans/2026-09-11-ops-console.md`)。**再追加:封禁系统消息 + 消息页改版**(封禁/解封以「系统通知」身份发 IM 消息说明原因与影响,重封先发后踢;App 底部「会话」改称「消息」并重构为抖音式版式;后端 190 / 前端 120 测试全绿。设计: `specs/2026-09-11-ban-notice-message-page-design.md`;计划: `plans/2026-09-11-ban-notice-message-page.md`)。**三追加:微信式改版 + IM 昵称同步**(聊天页改微信版式:方头像/品牌粉气泡/时间分组/长按复制删除/表情面板/＋面板发图片/失败重发;我的页与别人的资料页改微信行版式,ID 行 + ··· 菜单 + 相册大图;IM 昵称同步修掉「拉黑后会话名降级成裸 id」;后端 199 / 前端 141 测试全绿。设计: `specs/2026-09-12-chat-profile-wechat-design.md`;计划: `plans/2026-09-12-chat-profile-wechat.md`)。
设计与计划文档在 `docs/superpowers/`(spec: `specs/2026-09-09-dating-app-mvp-design.md`;M0: `plans/2026-09-09-m0-foundation.md`;M1a: `plans/2026-09-10-m1a-auth-profile.md`;M1b: `plans/2026-09-10-m1b-im-discovery.md`;M2a: `plans/2026-09-10-m2a-auth-onboarding.md`;M2b: `plans/2026-09-10-m2b-discovery-matching.md`;M2c: `plans/2026-09-10-m2c-im-chat.md`;M3 设计: `specs/2026-09-11-m3-compliance-design.md`;M3: `plans/2026-09-11-m3-compliance.md`)。**下一步 M4**(上线:服务器 + 域名部署;短信/内容安全/COS 接真;商店上架;iOS 打包决策;ICP 备案为并行事项)。

用户以中文交流,回复请使用中文。用户是 **Flutter/Django 新手**,偏好教学式、分步、带"为什么"的讲解。

## 目录结构

| 路径 | 内容 | 说明 |
|---|---|---|
| `app/` | Flutter 应用(Flutter 3.47.2) | `lib/core/`(网络/错误/凭证)、`lib/im/`(IM 抽象层)、`lib/router.dart`(go_router 路由表)、`lib/features/{auth,onboarding,discovery,chat,profile,settings,shell}`;测试是"真实 provider + 假网络 + 假 IM":`test/support/scripted_adapter.dart` + `test/support/harness.dart` 的 `pumpApp` + `test/support/fake_im_client.dart` |
| `chatapp/` | Django 项目(`manage.py` 所在层) | `config/` 项目包 + 6 个业务 app:`accounts users discovery im moderation ops`;敏感配置读 `chatapp/.env`(gitignored,模板见 `.env.example`) |
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
python manage.py im_send --from u2 --to u3 --text "你好"   # 手测:代发消息(--notice 发灰条)
python manage.py dev_reset_pair --a u8 --b u9              # 手测:清两人的滑卡/配对,重演配对流程
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

⚠️ **本地 MySQL 连接延迟(M3 实测)**:Django 默认每请求新建连接(dev server 一请求一线程,连不上池),而本机 MySQL 的 TLS 握手要 ~250ms → **所有接口 ~280ms**。已默认 `DB_SSL_DISABLED=1`(settings 里按 env 注入 `ssl_disabled=True`),接口降到 ~30ms。**远程库/生产要把 `DB_SSL_DISABLED` 置 0 或改连接池**;若哪天接口又变慢,先量「建连 vs 查询」。

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
- **代码位置**:userSig 生成在 `chatapp/im/signature.py`(含 `decode_user_sig` 调试解码);REST 调用在 `chatapp/im/client.py`(`import_account` / `send_custom_elem` / `send_match_notice` / `send_text`,**对外永不抛异常**,失败返回 False 只记日志)。
- **userSig 生成是最大的坑**:腾讯用自家的 base64 变体,不是标准/URL-safe base64。正确流程:构建 JSON(ver/identifier/sdkappid/expire/time,sig 用**标准** base64 的 HMAC-SHA256)→ `json.dumps` → `zlib.compress` → 标准 base64 后替换 `+`→`*`、`/`→`-`、`=`→`_`。字符串会以 `*` `-` `_` 出现且不 strip 填充。2026-09-10 由 `im/client.py` 实测通过。
- REST API 调用格式:`https://console.tim.qq.com/v4/{service}/{command}?sdkappid=&identifier=&usersig=&random=&contenttype=json`(usersig 需 URL 编码)。
- ⚠️ **`openim/sendmsg` 的 `identifier` 必须是管理员**(`administrator`),发送方靠 body 的 `From_Account` 指定;错用发送方身份会报 `60010 set the identifier field ... to the admin account`。2026-09-10 实测修正。
- ⚠️ **`im_open_login_svc/account_check` 别用来验签**:本应用下它对任何参数组合都返回 `70402 Invalid parameters`(与签名无关,同一签名调 `account_import` 返回 0)。验签一律用 `account_import`。
- **配对灰条消息**:配对成功时 `send_match_notice(a, b)` 给**双方各发一条** `TIMCustomElem`,`MsgContent.Data` = `{"type":"match_notice"}`,`Desc` = "你们已互相喜欢,开始聊天吧"(M2 端拦截该类型渲染成居中灰条,会话随之创建)。⚠️ 2026-09-10 起**改在后台线程发**(`discovery/services.py::_notify_async`):同步发两条各 ~0.45s,「配对成功」弹窗被拖慢近 1 秒;后端测试 patch `discovery.services._notify_async`(别 patch `im_client.send_match_notice`,那是线程里的真实路径)。
- 账号导入:注册成功后经 `transaction.on_commit` 调 `account_import(u{id})`,失败只记日志不阻塞注册。
- **Flutter 端 IM SDK 包是 `tencent_cloud_chat_sdk`(9.0.x,2026-06 发布)**:spec 早期写的 `tim_plus_flutter` 在 pub.dev 上**不存在**,已更正。只用它底层 API,不引 `tencent_cloud_chat_uikit`。支持 Android(x86_64 库有,模拟器能跑)/iOS/Web/Windows/macOS,Android minSdk 19。
- **手测代发消息**(不用第二台设备):`python manage.py im_send --from uX --to uY --text "你好"` 或 `--notice`(发灰条事件);走 REST,账号须已导入。
- **系统通知账号**:`system_notice`(昵称「系统通知」)是封禁/解封消息的发送方;新环境(含生产)跑一次 `python manage.py im_setup_system_account`(幂等,已存在 7015 视为成功;开发库 2026-09-11 已建)。账号缺失时封禁动作照常,只是消息发送失败记日志。
- **昵称同步**:改昵称后后端把新昵称同步到 IM(`im/client.py::set_profile_nick` → **`profile/portrait_set`**;⚠️ 接口名写成 `profile_set_field` 之类的错名会返回 60008「request format error」)。存量补一次 `python manage.py im_sync_nicknames`(幂等)。会话列表 `showName` 与聊天页标题兜底都靠它——拉黑后被拉黑方仍能显示真名而不是裸 id(2026-09-12 修)。
- **封禁/解封系统消息**:custom 消息 `type=ban_notice`(带 `level: light|heavy`)/`ban_lifted`,Desc 为完整中文说明;统一挂在 `moderation/services.py::log_ban_change` 的后台线程(admin 与 /ops/ 同源自动覆盖)。重封禁走 `_send_notice_then_kick`:同线程**先发消息再踢下线**。重封禁用户被封期间进不了消息页,消息留档、解封后可见。
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
- **provider 全局缓存**:`AsyncNotifierProvider` 默认常驻,页面 A 读过、页面 B 写了同一个列表 → B 必须 `ref.invalidate(该 provider)`(M3 手测:拉黑后黑名单页仍显示空)。写操作(拉黑/解除/改资料…)后检查一下相关 provider 要不要失效
- **widget 测试里别裸 `await` 走 dio 的 provider**(如 `container.read(xxxProvider.future)`):假时钟不推进 dio 内部定时器,测试直接卡死。要么让调用发生在 widget 树里(靠 `pumpAndSettle` 推进),要么直接 override provider 成目标状态
- **含无限动画的页面别 `pumpAndSettle`**(启动页转圈、倒计时):会超时。协议弹窗用例用有限次 `pump` 推进(见 `test/features/legal/agreement_gate_test.dart`)
- `SystemNavigator` 在 `package:flutter/services.dart`,material 不导出

## 发现卡片流(M2b 已实测)

- **代码位置**:`lib/features/discovery/`(`discovery_repository.dart` 纯 IO、`discovery_controller.dart` 卡组状态、`widgets/{profile_card,swipe_deck,match_overlay}.dart`);手势动画全自绘,**没引第三方卡组包**
- **卡组行为**:拖过屏宽 25% 判滑出(不到弹回);`decide` 先移卡(乐观)、失败放回队首并 SnackBar;剩 ≤3 张且非整批拉取时自动续拉;拉空 → 空态 + 「刷新」
- **⚠️ 续拉必须去重**:`/discovery/candidates` 只排除「已划过」的人,**卡组里还没划的人会被再发回来**;直接追加会出现同一人的重复卡(划完一张还剩一张,后端幂等不报错,极难发现 —— 2026-09-10 手测揪出)。追加前按 `userId` 过滤卡组已有的
- **⚠️ Riverpod 3 会给 build 失败的 provider 自动重试**(200ms 起指数退避,`ProviderContainer.defaultRetry`)——页面上已有手动「重试」按钮时,在 provider 上 `retry: (count, error) => null` 关掉,否则错误界面会一闪而过、测试断言不稳
- **⚠️ `GestureDetector` 默认 `deferToChild`**:卡片照片区没有任何命中目标,按在照片上会拖不动 —— 顶层卡的拖拽手势必须 `behavior: HitTestBehavior.opaque`
- **⚠️ 测试里网络图片必须自兜底**(`Image.network(errorBuilder:)` / `CircleAvatar(onBackgroundImageError:)`):widget 测试的假网络对所有图片请求返回 400,不兜底会直接报错
- **测试断言请求**:自动续拉的 GET 可能排在滑卡 POST 后面,别用 `adapter.log.last`,用 `lastWhere((r) => r.method == 'POST')`
- 手测配对动效需要 **两个资料完善且有已过审照片**的账号互滑(单账号只能看到「卡片飞出」)

## IM 聊天(M2c 已实测)

- **代码位置**:`lib/im/`(抽象层:`im_client.dart` 领域模型+接口、`tencent_im_client.dart` **全项目唯一 import SDK 的文件**、`im_repository.dart` userSig/matches、`im_manager.dart` 登录生命周期);UI 在 `lib/features/chat/`(`chats_page.dart` 会话列表、`chat_page.dart` 聊天页、`chat_controller.dart`/`conversations_controller.dart`/`match_cache.dart`)
- **测试策略**:SDK 是原生插件,`flutter test` 跑不了 → 测试注入 `test/support/fake_im_client.dart`(`pumpApp` 默认已注入,可传 `imClient:` 自定义);真实客户端永远只在手测/真机上跑
- **登录生命周期**:唯一触发点是 `SessionController` —— 登录成功/启动鉴权成功 → `imStatusProvider.notifier.login()`(fire-and-forget,不阻塞进主界面);`TokenStore.clear()` → `_forceLogout()` → `logout()`(防串号)。`ImManager` 内部把登录/登出**排成队列**(SDK 要求登出回调结束前不能再 login);`onUserSigExpired` 事件会自动重拉签名重登
- **数据流**:`ConversationsController`/`ChatController` 都 `watch(imStatusProvider)`,登录后订阅 `ImClient.events`(新消息/会话变化→刷新);`match_cache.dart` 把 `GET /matches` 缓成 `imUserId→昵称/头像`,watch session,登出自动清
- **⚠️ `flutter test` 里**别**裸 `await` 走 dio 的调用**(widget 测试的假时钟不推进 dio 内部定时器,测试会**死锁**,连超时都不触发 —— 2026-09-10 踩坑,一个用例挂了 7 分钟)。要么让调用发生在 widget 树里(靠 `pumpAndSettle` 推进),要么把 provider 直接 override 成目标状态(见 `chat_page_test.dart` 的 `_LoggedInImManager`)
- **⚠️ 构造 SDK 消息对象只能用 `V2TimMessage.fromJson({...})`**:默认构造函数内部调 `TIMManager.getServerTime()` → 加载 `dart_native_imsdk.dll` → VM 测试直接崩;`fromJson` 是纯 Dart。JSON 键名与必填字段见 `test/im/tencent_im_client_test.dart`
- **SDK 细节**:单聊 conversationID 前缀 `c2c_`;`sendMessage` 的 `id` 参数已废弃但 **web 分支只认它**,要 `id`+`message` 都传;清未读用 `cleanConversationUnreadMessageCount`(废弃的 `markC2CMessageAsRead` 别用;`cleanTimestamp` 传最后一条消息的秒级时间戳、`cleanSequence` 传它的 seq,2026-09-10 模拟器实测 1→0 成功);`ChatMessage.timestamp` 统一毫秒(SDK 是秒,映射时 ×1000)
- **日志噪音**:登录后 `E/imsdk ... community group not open |error_code:11000|` 是无害的(SDK 顺带拉群列表,本应用不用群),别当故障排查
- 手测:`python manage.py im_send --from uB --to uA --text "..."`,模拟器登录 A;灰条用 `--notice`;重演配对用 `dev_reset_pair --a u8 --b u9`(清滑卡+配对,不清 IM 聊天记录)。切换账号前记得 IM 登出已自动挂在退出通道上
- **消息页(原「会话」页,2026-09-11 改版)**:底部 tab 与页头已改称「消息」;抖音式版式 = 最近联系人横滑条(取会话前 10,不含系统通知)+ 「系统通知」置顶行(蓝底铃铛 + 官方标)+ 会话行(48 头像 / 加粗昵称 / 预览灰 / 红角标 `#FF2C55`)。页面 keys:`chats.strip` / `chats.stripItem:{peerId}` / `chats.systemNotice` / `chats.tile:{peerId}`
- **⚠️ ListTile trailing 里别用带 `alignment` 的 Container**:有界约束下它会撑满整格宽,ListTile 直接断言崩溃(实现角标时踩过);用 `Center(widthFactor: 1)` 或 SizedBox 包裹
- **系统通知显示名**:`displayNameFor` 特判 `system_notice` → 「系统通知」;`systemNoticePeerId` 常量在 `im_client.dart`(与后端 `im/client.py::SYSTEM_NOTICE_IDENTIFIER` 是跨栈契约,两边都别单改);`ChatMessageKind.banNotice` 覆盖 ban_notice/ban_lifted 两种,渲染与 match_notice 同款灰条,文案取 Desc
- **聊天页(2026-09-12 微信式改版)**:方头像+气泡、时间条(`chat_items.dart::buildChatItems` 纯函数,间隔>5 分钟插一条,格式 `formatChatTimestamp`)、长按菜单(复制/删除本机,`showMenu` 定位必须用气泡自己的 context——`Builder` 包一层,`ListView.builder` 的 itemBuilder context 是 sliver)、表情面板、＋面板发图、失败重发(不发 SnackBar 不撤消息,失败气泡旁红叹号 `chat.retry` 可点重发)。keys:`chat.time` / `chat.menu.copy|delete` / `chat.emoji.button|panel` / `chat.more.button|image` / `chat.retry` / `chat.image`
- **图片消息**:`ChatMessageKind.image` + `localPath`(发送中本机文件)/`imageUrl`(缩略)/`imageLargeUrl`(全屏);`ImClient.sendImage/deleteMessage`;该 SDK **无原生重发 API**,`resend` 是 `ImClient` 里的默认实现(用原内容重发),所以实现类必须 `extends ImClient` 而不是 `implements`(implements 不继承具体方法)
- ⚠️ **`V2TimImageElem.fromJson` 会读 `CommonUtils.appFileDir`**:VM 测试里构造图片消息前要 mock path_provider 通道 + `CommonUtils.init()`(见 `test/im/tencent_im_client_test.dart` 的 setUpAll);真机由 initSDK 初始化,无需处理
- **标题降级链**:matchCache → IM 会话名(昵称同步后有效)→ 裸 id;聊天页 `chat_page.dart::_imNameOf` 从 `conversationsProvider` 取 `showName`

## 合规与审核(M3 已实测)

- **封禁两级**:`banned_light` 只禁滑卡(检查在 `discovery/views.py`);`banned_heavy` = 全域 403 —— 由全局权限类 `moderation/permissions.py::IsNotHeavyBanned`(挂在 `DEFAULT_PERMISSION_CLASSES`)拦截,白名单只有 `GET /users/me`(前端要读封禁原因)和 `GET /users/tags`。**新增业务接口自动被覆盖**,不用逐个加检查
- **admin 审核台**(`/admin/`,运营账号用 `createsuperuser` 建,登录字段是手机号):
  - 照片审核:users → 照片;列表有缩略图预览,勾选后选「通过所选照片/驳回所选照片」;动作会自动重算用户的资料完善状态(驳回可能让人掉回未完善)
  - 举报队列:moderation → 举报;把状态改成「已处理」时自动补处理人/时间;从举报点进被举报人 Profile 可直接封禁
  - 封禁:users → 资料;改 `status` + 填 `ban_reason` 保存 → 自动写 `BanLog`(谁/何时/什么动作/原因);**重封禁会后台调 IM 踢下线**(已有 userSig 否则最长 7 天还能聊)
  - moderation → 拉黑/封禁日志是**只读对账页**(拉黑必须走 App 接口才会同步 IM,手工加会漏)
- **拉黑链路**:`POST/GET /blocks`、`DELETE /blocks/{id}`;双向不可见由 `moderation.services.blocked_user_ids` 统一过滤(候选、`GET /matches`、`GET /users/{id}` 404 全靠它);IM 黑名单后台线程同步(**实测管理员 identifier 对 `sns/black_list_*` 与 `im_open_login_svc/kick` 均成立**);拉黑方本机会话由 App 端 `deleteConversation` 删除
- **⚠️ 前端写操作后要失效相关缓存**:黑名单列表 provider 是全局缓存的,拉黑成功后必须 `ref.invalidate(blockedUsersProvider)`(M3 手测 bug:拉黑后黑名单页仍显示空)。以后加类似的「列表类」provider 写操作都要照此处理
- **举报**:`POST /reports`,同一个人已有待处理举报 → 幂等返回已有记录(201 新建 / 200 已有);限流 20/天
- **协议**:`app/lib/features/legal/legal_texts.dart` 存两份文本 + `legalVersion`;启动页检查本地 `legal.agreed_version`,未同意弹不可关的弹窗(不同意退出 App)。**改文案要把 legalVersion +1**,弹窗会重新出现一次;测试脚手架 `pumpApp` 默认「已同意」,协议用例传 `{'legal.agreed_version': 0}`
- **封禁页**:`home_shell` 检测 `profile.status == 'banned_heavy'` → 整屏封禁页(原因 + 「封禁期间所有功能暂停使用」+ 退出登录)
- **封禁/解封自动发系统消息**:轻封说明限制范围(只禁滑卡)、重封说明全停用、解封通知恢复;由 `log_ban_change` 统一触发(admin 与 /ops/ 自动覆盖,见「腾讯云 IM 集成要点」的系统通知账号条)
- **签名打包**:keystore 在 `C:\Users\you\chatapp-release.jks`(口令见 `app/android/key.properties`,**两个文件都不入库,务必备份**);出包:
  ```bash
  cd app && ../flutter/bin/flutter.bat build apk --release --dart-define=API_BASE=http://10.0.2.2:8000/api/v1
  ```
  产物 `app/build/app/outputs/flutter-apk/app-release.apk`;装模拟器用 `adb -s <设备> install -r ...`(同设备覆盖 debug 包会因签名冲突失败,需先卸载)

## 运营审核台 /ops/(M3 后新增)

- 独立 Django app `ops`:服务端模板 + HTMX 局部刷新;静态资源 vendored 在 `ops/static/ops/vendor/`(Pico.css/htmx),**不依赖 CDN,生产需 collectstatic**
- 登录复用 Django 账号体系,**判据 `is_staff`**;建运营账号 = 建一个 is_staff 用户(手机号+密码)。登录页会直接拒非 staff;已登录非 staff 访问任何 ops 页面 → 403
- 写操作与 admin 同源:`log_ban_change`(封禁审计+踢 IM)、`users/services.py::review_photos`(照片审核+资料状态重算+`reviewed_by/at` 审计)
- 解封会 `refresh_status()` 重算 complete/incomplete(admin 是手改状态下拉,别混用)
- 照片任何状态都可再审(已通过可「撤回并驳回」,用于事后处置);「已跳过」= 照片已被用户删除的陈旧页面
- 测试纪律:任何触发 IM 的路径 mock `moderation.services._dispatch_async`

## 后端测试注意事项

- **测 on_commit**:`notify_match` / 注册导入都走 `transaction.on_commit`,测试里必须 `with self.captureOnCommitCallbacks(execute=True):` 包住请求,否则断言永远不触发。
- **凡是会触发 IM 调用的用例都要 mock**:漏 mock 会真打腾讯云(用例仍会绿,因为业务函数吞异常 —— 靠跑测试时日志里有没有 `IM ... 返回错误` 来发现),且变慢、依赖网络。
- 限流用例要 `cache.clear()`:限流计数存在 Django 缓存(LocMem)里,跨用例残留会导致偶发 429。
