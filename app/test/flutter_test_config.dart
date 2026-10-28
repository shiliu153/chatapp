import 'dart:async';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

/// 全局测试配置:给 `flutter_secure_storage` 的 MethodChannel 装一个内存实现。
///
/// 为什么需要它:组件测试跑在 FakeAsync 里,未注册的平台通道**不会**抛
/// `MissingPluginException`,而是永远不返回 —— 表现成 `pumpAndSettle timed out`。
/// 用内存 Map 顶掉真实插件后,默认的 `TokenStore`(安全存储)在测试里也能正常工作,
/// 各测试文件不必逐个 override `tokenStoreProvider`。
Future<void> testExecutable(FutureOr<void> Function() testMain) async {
  TestWidgetsFlutterBinding.ensureInitialized();
  final values = <String, String>{};
  TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(
    const MethodChannel('plugins.it_nomads.com/flutter_secure_storage'),
    (call) async {
      final args = (call.arguments as Map?) ?? const {};
      final key = args['key'] as String?;
      switch (call.method) {
        case 'read':
          return values[key];
        case 'write':
          values[key ?? ''] = args['value'] as String? ?? '';
          return null;
        case 'delete':
          values.remove(key);
          return null;
        case 'deleteAll':
          values.clear();
          return null;
        case 'readAll':
          return Map<String, String>.from(values);
        case 'containsKey':
          return values.containsKey(key);
        default:
          return null;
      }
    },
  );
  await testMain();
}
