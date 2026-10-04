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
- ⚠️ **模拟器长跑数小时后 IM 长连接劣化**(2026-09-12 实测):消息最长隔 ~2 分钟才到、记录加载慢、偶发「网络不给力」;`adb logcat -d | grep -c ERR_CONNECTION_RESET` 每 ~2 分钟一次(SDK 心跳 120s 踩线跑不过链路重置)。判据:同机裸 TCP 空闲不断、后端接口全 15~60ms、宿主直连腾讯正常 → 模拟器侧劣化。处理:**冷启动重启(`-no-snapshot-load`)即恢复**——⚠️ 动模拟器前先和用户确认。
- ⚠️ **模拟器相册默认是空的**:测照片上传先 `adb push 本地图.png /sdcard/Pictures/x.png` 并触发媒体扫描(`adb shell am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file:///sdcard/Pictures/x.png`),或改用 `-d windows` 走文件选择。
- ⚠️ 模拟器访问宿主机一律 **`10.0.2.2`**(不是 127.0.0.1——那指向模拟器自己)。
