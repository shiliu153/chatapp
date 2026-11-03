import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'app.dart';
import 'core/error_reporting.dart';
import 'core/pinned_tls.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  // 错误上报必须早于 runApp:启动阶段的崩溃也要能抓到(开关默认关,见 --dart-define)
  ErrorReporting.install();
  // 证书绑定要在建 Dio 之前预热:读根证书是异步的,而 Dio 的构造是同步的
  await PinnedTls.warmUp();
  runApp(const ProviderScope(child: ChatApp()));
}
