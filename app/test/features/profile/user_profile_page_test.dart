import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/features/profile/user_profile_page.dart';
import 'package:chatapp_app/features/settings/blocked_users_page.dart';
import 'package:chatapp_app/im/im_client.dart';
import 'package:chatapp_app/im/im_manager.dart';

import '../../support/fake_im_client.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

class _LoggedInImManager extends ImManager {
  @override
  ImStatus build() => const ImLoggedIn('u3');
}

void main() {
  late ScriptedAdapter adapter;
  late FakeImClient fake;

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    adapter = ScriptedAdapter({});
    fake = FakeImClient();
    addTearDown(fake.dispose);
  });

  /// 从 '/' push 进资料卡,pop 才有得可退。
  Future<void> pumpProfile(WidgetTester tester, {int userId = 9}) async {
    final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
    final container = ProviderContainer(overrides: [
      baseDioProvider.overrideWithValue(dio),
      refreshDioProvider.overrideWithValue(dio),
      imClientProvider.overrideWithValue(fake),
      imStatusProvider.overrideWith(_LoggedInImManager.new),
    ]);
    addTearDown(container.dispose);
    final router = GoRouter(
      initialLocation: '/',
      routes: [
        GoRoute(path: '/', builder: (context, state) => const Scaffold(body: Text('首页'))),
        GoRoute(
          path: '/users/:id',
          builder: (context, state) =>
              UserProfilePage(userId: int.parse(state.pathParameters['id']!)),
        ),
      ],
    );
    await tester.pumpWidget(UncontrolledProviderScope(
      container: container,
      child: MaterialApp.router(routerConfig: router),
    ));
    await tester.pumpAndSettle();
    router.push('/users/$userId');
    await tester.pumpAndSettle();
  }

  testWidgets('渲染公开资料:昵称/年龄/城市/标签/简介/两个按钮', (tester) async {
    adapter.routes['GET /users/9'] = (options) => ok(publicProfileJson(
        nickname: '小红', age: 25, city: '上海', bio: '喜欢爬山', tags: [tagJson(1, '运动')]));
    await pumpProfile(tester);

    expect(find.text('小红 · 25 岁 · 上海'), findsOneWidget);
    expect(find.text('运动'), findsOneWidget);
    expect(find.text('喜欢爬山'), findsOneWidget);
    expect(find.byKey(const Key('user.report')), findsOneWidget);
    expect(find.byKey(const Key('user.block')), findsOneWidget);
  });

  testWidgets('404 → 「用户不存在」+ 重试按钮', (tester) async {
    adapter.routes['GET /users/9'] = (options) => jsonError(404, '用户不存在');
    await pumpProfile(tester);

    expect(find.text('用户不存在'), findsOneWidget);
    expect(find.byKey(const Key('user.retry')), findsOneWidget);
  });

  testWidgets('举报:选类型 → 提交 → POST /reports + 提示语', (tester) async {
    adapter.routes['GET /users/9'] = (options) => ok(publicProfileJson());
    adapter.routes['POST /reports'] =
        (options) => ok({'id': 1, 'type': 'harassment', 'status': 'pending'}, status: 201);
    await pumpProfile(tester);

    await tester.tap(find.byKey(const Key('user.report')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('report.type.harassment')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('report.submit')));
    await tester.pumpAndSettle();

    expect(adapter.log.lastWhere((r) => r.method == 'POST').path, '/reports');
    expect(find.text('已收到举报,我们会尽快处理'), findsOneWidget);
  });

  testWidgets('拉黑:确认 → POST /blocks + 删本机会话 + 返回上一页', (tester) async {
    adapter.routes['GET /users/9'] = (options) => ok(publicProfileJson());
    adapter.routes['POST /blocks'] = (options) => ok({'user_id': 9}, status: 201);
    fake.conversations = [const ImConversation(peerId: 'u9', unreadCount: 2)];
    await pumpProfile(tester);

    await tester.tap(find.byKey(const Key('user.block')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('user.block.confirm')));
    await tester.pumpAndSettle();

    expect(adapter.log.lastWhere((r) => r.method == 'POST').path, '/blocks');
    expect(fake.log, contains('deleteConversation:u9'));
    expect(find.text('首页'), findsOneWidget);   // 已返回上一页
    expect(find.text('已拉黑'), findsOneWidget);
  });

  testWidgets('拉黑后回黑名单页:缓存失效并重新拉取(复现 2026-09-11 手测)', (tester) async {
    adapter.routes['GET /users/9'] = (options) => ok(publicProfileJson(nickname: '小红'));
    var blocks = <Map<String, dynamic>>[];
    adapter.routes['GET /blocks'] = (options) => ok(blocks);
    adapter.routes['POST /blocks'] = (options) {
      blocks = [blockedUserJson(userId: 9, nickname: '小红')];
      return ok({'user_id': 9}, status: 201);
    };

    final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
    final container = ProviderContainer(overrides: [
      baseDioProvider.overrideWithValue(dio),
      refreshDioProvider.overrideWithValue(dio),
      imClientProvider.overrideWithValue(fake),
      imStatusProvider.overrideWith(_LoggedInImManager.new),
    ]);
    addTearDown(container.dispose);
    // 首页 = 黑名单页(先看过一次,空列表进缓存),可 push 资料卡
    final router = GoRouter(
      initialLocation: '/',
      routes: [
        GoRoute(path: '/', builder: (context, state) => const BlockedUsersPage()),
        GoRoute(
          path: '/users/:id',
          builder: (context, state) =>
              UserProfilePage(userId: int.parse(state.pathParameters['id']!)),
        ),
      ],
    );
    await tester.pumpWidget(UncontrolledProviderScope(
      container: container,
      child: MaterialApp.router(routerConfig: router),
    ));
    await tester.pumpAndSettle();
    expect(find.text('还没有拉黑任何人'), findsOneWidget);   // 预热:空态已缓存

    router.push('/users/9');
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('user.block')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('user.block.confirm')));
    await tester.pumpAndSettle();

    // 拉黑成功会 pop 回黑名单页;缓存若没失效,这里仍是空态(手测踩到的 bug)
    expect(find.text('小红'), findsOneWidget);
  });
}
