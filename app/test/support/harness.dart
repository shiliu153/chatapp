import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/app.dart';
import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/features/auth/session.dart';
import 'package:chatapp_app/features/legal/legal_texts.dart';
import 'package:chatapp_app/features/presence/presence_controller.dart';
import 'package:chatapp_app/features/shell/app_bottom_bar.dart';
import 'package:chatapp_app/im/im_manager.dart';

import 'fake_im_client.dart';
import 'scripted_adapter.dart';

/// 起整个 App(真实 provider + 假网络 + 假 IM)。prefs 里塞 {'auth.refresh': 'r', ...} 模拟已登录。
/// 返回注入的 FakeImClient,测试可用它铺数据/断言调用(想自定义就传 imClient)。
Future<FakeImClient> pumpApp(WidgetTester tester, ScriptedAdapter adapter,
    {Map<String, Object> prefs = const {}, FakeImClient? imClient}) async {
  final fake = imClient ?? FakeImClient();
  // 默认已同意协议,绝大多数用例直接进 App;协议用例自己传 legal.agreed_version: 0
  SharedPreferences.setMockInitialValues({'legal.agreed_version': legalVersion, ...prefs});
  final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
  final refreshDio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
  await tester.pumpWidget(ProviderScope(
    overrides: [
      baseDioProvider.overrideWithValue(dio),
      refreshDioProvider.overrideWithValue(refreshDio),
      imClientProvider.overrideWithValue(fake),
      // 默认关掉登录态心跳:避免测试里周期性假请求干扰用例,心跳用例自己 override
      heartbeatIntervalProvider.overrideWithValue(null),
      // 同样默认关掉在线状态的周期刷新;需要测定时的用例自己 override
      presenceRefreshIntervalProvider.overrideWithValue(null),
    ],
    child: const ChatApp(),
  ));
  return fake;
}

/// 底部导航栏里的 Tab 标签(避开与各页 AppBar 标题重名)。
Finder navTab(String label) =>
    find.descendant(of: find.byType(AppBottomBar), matching: find.text(label));
