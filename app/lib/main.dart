import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'app.dart';
import 'core/error_reporting.dart';
import 'core/pinned_tls.dart';
import 'core/theme/theme_controller.dart';
import 'core/theme/theme_mode_store.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  // 错误上报必须早于 runApp:启动阶段的崩溃也要能抓到(开关默认关,见 --dart-define)
  ErrorReporting.install();
  // 证书绑定要在建 Dio 之前预热:读根证书是异步的,而 Dio 的构造是同步的
  await PinnedTls.warmUp();
  // 外观模式也要早于 runApp 读出来:否则深色用户会先看到一帧浅色(闪白)
  final themeMode = await const ThemeModeStore().read();
  runApp(ProviderScope(
    overrides: [initialThemeModeProvider.overrideWithValue(themeMode)],
    child: const ChatApp(),
  ));
}
