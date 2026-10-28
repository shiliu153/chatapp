import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'app.dart';
import 'core/pinned_tls.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  // 证书绑定要在建 Dio 之前预热:读根证书是异步的,而 Dio 的构造是同步的
  await PinnedTls.warmUp();
  runApp(const ProviderScope(child: ChatApp()));
}
