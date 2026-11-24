import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/features/auth/session.dart';
import 'package:chatapp_app/features/presence/presence_controller.dart';
import 'package:chatapp_app/features/profile/my_profile_page.dart';
import 'package:chatapp_app/features/profile/user_profile_page.dart';
import 'package:chatapp_app/im/im_manager.dart';

import '../../support/fake_im_client.dart';
import '../../support/harness.dart';
import '../../support/heart_theme.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

/// E-5.4 page spec §6 第 3 条:**Semantics 断言**。
///
/// | 元素 | 读什么 |
/// |---|---|
/// | 头像 | 「昵称,在线」 |
/// | 信息行 | 「标签,值」 |
/// | 语音介绍 | 「语音介绍,N 秒」 |
///
/// 为什么必须钉这三条:§8.4「颜色不是唯一线索」—— 在线点、语音条这类纯视觉信号
/// 对读屏用户等于不存在,只有语义标签能把它们说出来。
const _loggedIn = {'auth.access': 'a', 'auth.refresh': 'r', 'auth.user_id': 7};

class _LoggedInImManager extends ImManager {
  @override
  ImStatus build() => const ImLoggedIn('u3');
}

class _LoggedInSession extends SessionController {
  @override
  SessionState build() => const SessionLoggedIn();
}

/// 把他人资料页单独挂起来(与 user_profile_page_test 同款最少依赖)。
Future<void> pumpUserProfile(
  WidgetTester tester,
  ScriptedAdapter adapter, {
  int userId = 9,
  bool settle = true,
}) async {
  SharedPreferences.setMockInitialValues({});
  final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))
    ..httpClientAdapter = adapter;
  final fake = FakeImClient();
  addTearDown(fake.dispose);
  final container = ProviderContainer(overrides: [
    baseDioProvider.overrideWithValue(dio),
    refreshDioProvider.overrideWithValue(dio),
    imClientProvider.overrideWithValue(fake),
    imStatusProvider.overrideWith(_LoggedInImManager.new),
    sessionProvider.overrideWith(_LoggedInSession.new),
    presenceRefreshIntervalProvider.overrideWithValue(null),
  ]);
  addTearDown(container.dispose);
  final router = GoRouter(
    initialLocation: '/',
    routes: [
      GoRoute(
        path: '/',
        builder: (context, state) => const Scaffold(body: Text('首页')),
      ),
      GoRoute(
        path: '/users/:id',
        builder: (context, state) =>
            UserProfilePage(userId: int.parse(state.pathParameters['id']!)),
      ),
    ],
  );
  await tester.pumpWidget(UncontrolledProviderScope(
    container: container,
    child: MaterialApp.router(theme: heartTheme, routerConfig: router),
  ));
  await tester.pumpAndSettle();
  router.push('/users/$userId');
  if (settle) {
    await tester.pumpAndSettle();
  } else {
    // 在线点呼吸是无限动画:在线用例只能有限推进
    await pumpFrames(tester);
  }
}

void main() {
  testWidgets('头像读「昵称,在线」', (tester) async {
    final semantics = tester.ensureSemantics();
    final adapter = ScriptedAdapter({
      'GET /users/9': (options) => ok(publicProfileJson(nickname: '小红')),
      'GET /matches': (options) => ok(pageJson([])),
      'GET /presence': (options) => ok({
            'results': [
              {'user_id': 9, 'online': true, 'last_active_at': null}
            ]
          }),
    });
    await pumpUserProfile(tester, adapter, settle: false);

    // EmberAvatar 的默认标签是「昵称,在线」(spec §8.4 颜色之外给文字)
    expect(find.bySemanticsLabel('小红，在线'), findsWidgets);
    semantics.dispose();
  });

  testWidgets('信息行读「标签,值」', (tester) async {
    final semantics = tester.ensureSemantics();
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me':
          (options) => ok(profileJson(nickname: '小雨', city: '杭州', bio: '你好')),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();
    await tester.tap(navTab('我'));
    await tester.pumpAndSettle();

    expect(find.byType(MyProfilePage), findsOneWidget);
    // 一行一件事:读屏不会把「城市」和「杭州」分成两条
    expect(find.bySemanticsLabel('城市，杭州'), findsOneWidget);
    expect(find.bySemanticsLabel('简介，你好'), findsOneWidget);
    semantics.dispose();
  });

  testWidgets('语音介绍读「语音介绍,18 秒」', (tester) async {
    final semantics = tester.ensureSemantics();
    final adapter = ScriptedAdapter({
      'GET /users/9': (options) =>
          ok(publicProfileJson(nickname: '小红', voice: voiceJson(durationMs: 18000))),
      'GET /matches': (options) => ok(pageJson([])),
      'GET /presence': (options) => ok({'results': []}),
    });
    await pumpUserProfile(tester, adapter);

    expect(find.bySemanticsLabel('语音介绍，18 秒'), findsOneWidget);
    // 播放键自己的标签仍在(容器语义不吞子节点)
    expect(find.bySemanticsLabel('播放'), findsOneWidget);
    semantics.dispose();
  });
}
