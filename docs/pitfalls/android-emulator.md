# 踩坑手册 · 模拟器与 Android 构建

> 索引见 [README.md](README.md)。打服务器包见 `CLAUDE.md`「常用命令」;部署形态见 [项目 README](../../README.md)「部署」。

## 国内镜像(已配置,勿删)

Google 源在国内不可直连,以下已就位(2026-09-10 `flutter build apk --debug` 全链路验证):

- Gradle 发行版:`app/android/gradle/wrapper/gradle-wrapper.properties` → 腾讯云镜像
- Maven 依赖:`app/android/settings.gradle.kts` 与 `build.gradle.kts` 阿里云镜像优先(google/public/gradle-plugin),官方源兜底
- Flutter 引擎工件:用户级环境变量 `FLUTTER_STORAGE_BASE_URL=https://storage.flutter-io.cn`(**勿删**;新开终端/IDE 才生效)
- pub 无需镜像(直连 pub.dev 正常);若变慢可临时 `PUB_HOSTED_URL=https://pub.flutter-io.cn`(会把镜像地址写进 `pubspec.lock`,注意)

## 模拟器日常

- 设备:`emulator-5554`(sdk gphone16k x86_64,Android 17 / API 37);双端手测时两台(如 5554 / 5556)。
- 运行:`(cd app && ../flutter/bin/flutter.bat run -d emulator-5554 --dart-define=API_BASE=http://10.0.2.2:8000/api/v1)`(模拟器里 `10.0.2.2` = 宿主机回环;`.env` ALLOWED_HOSTS 已含)。
- 截图:`"$LOCALAPPDATA/Android/Sdk/platform-tools/adb.exe" -s emulator-5554 exec-out screencap -p > shot.png`
- 拉起 App:`adb shell am start -n com.chatapp.chatapp_app/com.chatapp.chatapp_app.MainActivity`
- 装包:`adb -s <设备> install -r <apk>`(同设备覆盖 **debug** 包会因签名冲突失败,需先卸载)。
- 连服务器手测:`--dart-define=API_BASE=http://<SERVER_IP>/api/v1`(外部 IP 直连,不需要 10.0.2.2)。

## 踩过的坑

- ⚠️ **`monkey -p chatapp_app` 会静默失败**:applicationId 是 `com.chatapp.chatapp_app`,不是 Flutter 包名 `chatapp_app`;用 `am start`。
- ⚠️ **只保留一个 runserver 进程**:Windows 下多个 runserver 可同时绑定 8000,旧进程会拿旧配置抢答(踩过:旧 ALLOWED_HOSTS 导致 400)。排查:`netstat -ano | grep :8000` + `Get-CimInstance Win32_Process` 看 PID 启动时间和命令行。
- ⚠️ **覆盖安装后行为仍像旧代码 → 怀疑装到了旧产物**(2026-09-13 踩过):现象=新功能完全不生效但后端日志显示请求正常。排查:`adb shell dumpsys package com.chatapp.chatapp_app | grep lastUpdateTime` 对照安装时刻;**处理=干净重打 `flutter build apk` 再 `install -r`**。诊断手段:临时 `debugPrint` + release 包直接 `adb logcat -d | grep "\[标签"`(release 里 debugPrint 仍输出)。
- ⚠️ **模拟器长跑数小时后 IM 长连接劣化**(2026-09-12 实测,腾讯 SDK 时代;自建 imserver 下 45s 心跳已解决,保留作历史参考):消息最长隔 ~2 分钟才到、记录加载慢、偶发「网络不给力」;`adb logcat -d | grep -c ERR_CONNECTION_RESET` 每 ~2 分钟一次(SDK 心跳 120s 踩线跑不过链路重置)。判据:同机裸 TCP 空闲不断、后端接口全 15~60ms、宿主直连腾讯正常 → 模拟器侧劣化。处理:**冷启动重启(`-no-snapshot-load`)即恢复**——⚠️ 动模拟器前先和用户确认。
- ⚠️ **模拟器相册默认是空的**:测照片上传先 `adb push 本地图.png /sdcard/Pictures/x.png` 并触发媒体扫描(`adb shell am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file:///sdcard/Pictures/x.png`),或改用 `-d windows` 走文件选择。
- ⚠️ 模拟器访问宿主机一律 **`10.0.2.2`**(不是 127.0.0.1——那指向模拟器自己)。
- ⚠️ **Android 明文 HTTP 下「接口全通、语音播不了」**(2026-11-09 批次 R 实测,排查花了半小时):
  现象=资料语音点播放 → 图标短暂变暂停 → 2 秒后「播放失败,点击重试」,同机登录/列表/上传却全部正常(上传还 201)。
  根因=`targetSdk ≥ 28` 时原生播放器(`audioplayers` 走 ExoPlayer)**禁止 `http://`**,而 Dart 的 `dart:io HttpClient`
  (Dio 走这条)直接用 socket,**不受** Android network security config 约束 —— 于是 API 全通、媒体加载失败。
  `flutter` 的 `Image.network` 也走 dart:io,所以只有**原生解码**的媒体(语音/视频)会中招。
  生产是 `https://chat.shiliu153.cn`,线上不暴露;只有模拟器/内网 `http://10.0.2.2:8000` 这类环境才踩。
  修法=在 `app/android/app/src/debug/AndroidManifest.xml` 加 `<application android:usesCleartextTraffic="true" />`,
  **只放开 debug**(`profile`/`release` 构建仍禁明文)。看到「播放失败」先查这个,别先怀疑播放器封装或 URL 拼接。
- ⚠️ **`adb shell input tap` 用「设备像素」,但截图预览可能被缩放/加边**:2026-11-07 实测,目测截图把底部 tab 点在 y=1745,而 `uiautomator dump` 里真实 bounds 是 y=2143–2311 —— 点了 5 次都没切换,误判成「tab 点不动」。**正确姿势:先 `adb shell uiautomator dump /sdcard/ui.xml && adb shell cat /sdcard/ui.xml`,按 `content-desc` 找到节点再取 bounds 中点去点**;登录页的 `获取验证码`/`登录` 同理(踩过的假象:以为按钮坏了,实际是点偏)。
- ⚠️ **输入框聚焦时软键盘会让布局整体上移**:同一坐标「点前有效、点后无效」十有八九是键盘动画期间点的。先 `input keyevent 4` 收键盘、等 1 秒,再按 dump 的 bounds 点。
- ⚠️ **release 包偶发「网络不给力」而 debug 包同一操作成功**(2026-11-07 实测):先用 `flutter build apk --debug` 复测同一路径,别急着改代码 —— 本次根因是模拟器长跑劣化(见上一条),`adb reboot` 后恢复正常;release 包默认开证书绑定(`CERT_PINNING`),排查时可临时 `--dart-define=CERT_PINNING=off` 对照(该产物**不要**发版)。
  **2026-11-07 批次 I 复现**:`-no-snapshot-load` 冷启动 + 全新安装的 release 包,登录页点「获取验证码」仍报「网络不给力」,
  服务端 `/auth/sms/send` **0 条**(同机 `GET /app/config` 正常、每 0.6s 一次在刷);换成 `flutter build apk --debug`
  同一路径立刻成功(服务端有记录、倒计时 59 秒)。结论:**该模拟器上 UI 验收一律用 debug 包**(与批次 F 一致),
  release 包只用来验「装得上、能启动」;要复现 release 网络问题先试 `CERT_PINNING=off` 与 `adb reboot`。
- ⚠️ **release 与 debug 包签名不同**:直接 `install -r` 会 `INSTALL_FAILED_UPDATE_INCOMPATIBLE`,先 `adb uninstall com.chatapp.chatapp_app`。
- ⚠️ **模拟器上 App 的 WS「只收不发」**(2026-11-07 批次 J 实测,两次独立复现):聊天气泡一直停在
  **「发送中」**,10 秒 ×3 次重试后置为失败;**库内没有任何行**。但同一个连接:
  `auth_ok` 正常、25s 心跳让会话保持在线(`im:online:<uid>` 的 TTL 在刷新)、能收到对端下行消息 ——
  **只有 `send` 帧不生效**。
  - **判据(按这个顺序做判别实验,别先改代码)**:
    1. **同一台电脑的 Chrome 打开 Web 端发同一条消息** → 若立刻成功并落库,说明服务端与协议层没问题;
    2. **App 里改发一条纯文本** → 若同样卡「发送中」,说明与「哪种消息类型」无关;
    3. 查服务端份额:`im:sendq:<uid>:<minute>` 是否超 `IM_SEND_PER_MINUTE`(默认 120)、
       `im_pair` 是否存在、`im_user` 双方是否都有行 —— 都正常时即可排除业务拒绝。
  - 本批结论:服务端、白名单、配额全部正常,**生产 Web 端端到端通过**;问题只在本机模拟器的
    App→imserver 发送链路。已试过 `10.0.2.2:9100` 与 `adb reverse tcp:9100/9101/8000` +
    `ws://127.0.0.1:9100` 两种拓扑,都不通;`adb reboot` 后仍复现。
  - **绕开办法**:发送类功能的手测改用 **Web 端(Chrome)** 或 `curl`/脚本直连 WS(见
    `docs/ops/imserver.md` §17.4);模拟器只验「UI 渲染、面板、历史还原」这类不收发帧的路径。

