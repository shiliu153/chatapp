import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/app.dart';
import 'package:chatapp_app/core/app_config.dart';
import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/core/theme/app_theme.dart';
import 'package:chatapp_app/core/theme/theme_controller.dart';
import 'package:chatapp_app/core/theme/theme_mode_store.dart';
import 'package:chatapp_app/core/token_storage.dart';
import 'package:chatapp_app/core/token_store.dart';
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
    {Map<String, Object> prefs = const {},
    FakeImClient? imClient,
    List<Override> overrides = const []}) async {
  final fake = imClient ?? FakeImClient();
  // 默认已同意协议,绝大多数用例直接进 App;协议用例自己传 legal.agreed_version: 0
  SharedPreferences.setMockInitialValues({'legal.agreed_version': legalVersion, ...prefs});
  final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
  final refreshDio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
  // 单元测试没有平台通道:令牌存储换成 SharedPreferences 实现,
  // 这样 `prefs:` 参数仍然等价于「已登录」,用例无需改动
  final tokenStore = TokenStore(storage: SharedPreferencesTokenStorage());
  // 与 main.dart 同一条路径:启动前先把外观模式从 prefs 读出来注入,
  // 这样 `prefs: {'theme_mode': 'dark'}` 就等于「用户上次选了深色」。
  final themeMode = await const ThemeModeStore().read();
  await tester.pumpWidget(ProviderScope(
    overrides: [
      baseDioProvider.overrideWithValue(dio),
      refreshDioProvider.overrideWithValue(refreshDio),
      tokenStoreProvider.overrideWithValue(tokenStore),
      imClientProvider.overrideWithValue(fake),
      appConfigCheckEnabledProvider.overrideWithValue(false),
      initialThemeModeProvider.overrideWithValue(themeMode),
      // 默认关掉登录态心跳:避免测试里周期性假请求干扰用例,心跳用例自己 override
      heartbeatIntervalProvider.overrideWithValue(null),
      // 同样默认关掉在线状态的周期刷新;需要测定时的用例自己 override
      presenceRefreshIntervalProvider.overrideWithValue(null),
      ...overrides,
    ],
    child: const ChatApp(),
  ));
  return fake;
}

/// 底部导航栏里的 Tab 标签(避开与各页 AppBar 标题重名)。
Finder navTab(String label) =>
    find.descendant(of: find.byType(AppBottomBar), matching: find.text(label));

/// 直接 pump 单个页面(真实 provider + 假网络 + 真实主题),不走路由。
///
/// 给「逐页暗色巡检」这类用例用:一次只关心一个页面,不需要 go_router 的跳转链。
/// [brightness] 决定挂哪套主题 —— 组件取色走 `context.heart`,所以必须是真实主题。
Future<void> pumpPage(
  WidgetTester tester,
  ScriptedAdapter adapter,
  Widget page, {
  Map<String, Object> prefs = const {},
  Brightness brightness = Brightness.light,
  FakeImClient? imClient,
  List<Override> overrides = const [],
}) async {
  SharedPreferences.setMockInitialValues({'legal.agreed_version': legalVersion, ...prefs});
  final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
  final refreshDio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
  await tester.pumpWidget(ProviderScope(
    overrides: [
      baseDioProvider.overrideWithValue(dio),
      refreshDioProvider.overrideWithValue(refreshDio),
      tokenStoreProvider
          .overrideWithValue(TokenStore(storage: SharedPreferencesTokenStorage())),
      imClientProvider.overrideWithValue(imClient ?? FakeImClient()),
      appConfigCheckEnabledProvider.overrideWithValue(false),
      heartbeatIntervalProvider.overrideWithValue(null),
      presenceRefreshIntervalProvider.overrideWithValue(null),
      ...overrides,
    ],
    child: MaterialApp(
      theme: buildAppTheme(brightness: brightness),
      home: page,
    ),
  ));
}

/// 页面含无限动画(涟漪/骨架/在线点)时,替代 pumpAndSettle 的「够用即停」推进:
/// 假时钟步进若干帧,放行网络链与入场动画后即可断言。
Future<void> pumpFrames(WidgetTester tester,
    {int frames = 8, Duration step = const Duration(milliseconds: 100)}) async {
  for (var i = 0; i < frames; i++) {
    await tester.pump(step);
  }
}

/// AppToast 的 2s 自动消失 Timer 会让 testWidgets 以 pending timer 失败:
/// 触发过 Toast 的用例收尾调用,把假时钟推过超时点。
Future<void> drainToast(WidgetTester tester) =>
    tester.pump(const Duration(seconds: 3));
