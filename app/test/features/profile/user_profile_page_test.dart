import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/core/widgets/avatar_hero.dart';
import 'package:chatapp_app/features/auth/session.dart';
import 'package:chatapp_app/features/presence/presence_controller.dart';
import 'package:chatapp_app/features/profile/user_profile_page.dart';
import 'package:chatapp_app/features/settings/blocked_users_page.dart';
import 'package:chatapp_app/im/im_client.dart';
import 'package:chatapp_app/im/im_manager.dart';

import '../../support/fake_im_client.dart';
import '../../support/harness.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

class _LoggedInImManager extends ImManager {
  @override
  ImStatus build() => const ImLoggedIn('u3');
}

/// 配对缓存依赖登录态才会去拉 /matches(与真实 App 一致)。
class _LoggedInSession extends SessionController {
  @override
  SessionState build() => const SessionLoggedIn();
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
  Future<void> pumpProfile(WidgetTester tester, {int userId = 9, String? heroTag}) async {
    final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
    final container = ProviderContainer(overrides: [
      baseDioProvider.overrideWithValue(dio),
      refreshDioProvider.overrideWithValue(dio),
      imClientProvider.overrideWithValue(fake),
      imStatusProvider.overrideWith(_LoggedInImManager.new),
      sessionProvider.overrideWith(_LoggedInSession.new),
      // 页面会 track 在线状态;关掉周期刷新,否则测试结束时有 pending Timer
      presenceRefreshIntervalProvider.overrideWithValue(null),
    ]);
    addTearDown(container.dispose);
    final router = GoRouter(
      initialLocation: '/',
      routes: [
        GoRoute(path: '/', builder: (context, state) => const Scaffold(body: Text('首页'))),
        GoRoute(
          path: '/users/:id',
          builder: (context, state) => UserProfilePage(
            userId: int.parse(state.pathParameters['id']!),
            heroTag: state.extra as String?,
          ),
        ),
      ],
    );
    await tester.pumpWidget(UncontrolledProviderScope(
      container: container,
      child: MaterialApp.router(routerConfig: router),
    ));
    await tester.pumpAndSettle();
    router.push('/users/$userId', extra: heroTag);
    await tester.pumpAndSettle();
  }

  testWidgets('渲染公开资料:昵称·年龄/ID/地区/签名/标签 + ···菜单', (tester) async {
    adapter.routes['GET /users/9'] = (options) => ok(publicProfileJson(
        nickname: '小红', age: 25, city: '上海', bio: '喜欢爬山', tags: [tagJson(1, '运动')]));
    await pumpProfile(tester);

    expect(find.text('小红,25'), findsOneWidget); // 与发现卡同款格式(无「· 岁」)
    expect(find.text('ID:u9'), findsOneWidget);
    expect(find.text('上海'), findsOneWidget);
    expect(find.text('喜欢爬山'), findsOneWidget);
    expect(find.text('运动'), findsOneWidget);

    await tester.tap(find.byKey(const Key('user.more')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('user.report')), findsOneWidget);
    expect(find.byKey(const Key('user.block')), findsOneWidget);
  });

  testWidgets('未配对时菜单没有「解除配对」', (tester) async {
    adapter.routes['GET /users/9'] = (options) => ok(publicProfileJson(nickname: '小红'));
    adapter.routes['GET /matches'] = (options) => ok(pageJson([]));
    await pumpProfile(tester);

    await tester.tap(find.byKey(const Key('user.more')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('user.unmatch')), findsNothing);
  });

  testWidgets('已配对时菜单有「解除配对」', (tester) async {
    adapter.routes['GET /users/9'] = (options) => ok(publicProfileJson(nickname: '小红'));
    adapter.routes['GET /matches'] =
        (options) => ok(pageJson([matchJson(userId: 9, nickname: '小红')]));
    await pumpProfile(tester);

    await tester.tap(find.byKey(const Key('user.more')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('user.unmatch')), findsOneWidget);
  });

  testWidgets('相册照片点开全屏查看', (tester) async {
    adapter.routes['GET /users/9'] = (options) =>
        ok(publicProfileJson(photos: [photoJson(900), photoJson(901)]));
    await pumpProfile(tester);

    // 头图占了约一屏高,相册在折叠线以下,先滚到可见
    await tester.ensureVisible(find.byKey(const Key('user.album.photo:0')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('user.album.photo:0')));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('viewer.page')), findsOneWidget);
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

    await tester.tap(find.byKey(const Key('user.more')));
    await tester.pumpAndSettle();
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

    await tester.tap(find.byKey(const Key('user.more')));
    await tester.pumpAndSettle();
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
    adapter.routes['GET /blocks'] = (options) => ok(pageJson(blocks));
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
      sessionProvider.overrideWith(_LoggedInSession.new),
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
    await tester.tap(find.byKey(const Key('user.more')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('user.block')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('user.block.confirm')));
    await tester.pumpAndSettle();

    // 拉黑成功会 pop 回黑名单页;缓存若没失效,这里仍是空态(手测踩到的 bug)
    expect(find.text('小红'), findsOneWidget);
  });

  testWidgets('照片头图:渲染昵称·年龄/城市,不显示「详细资料」标题', (tester) async {
    adapter.routes['GET /users/9'] =
        (options) => ok(publicProfileJson(nickname: '小红', age: 25, city: '上海'));
    await pumpProfile(tester);

    expect(find.text('小红,25'), findsOneWidget);
    expect(find.text('上海'), findsOneWidget);
    expect(find.text('详细资料'), findsNothing); // 标题已删(身份由头图承载)
    expect(find.byKey(const Key('user.back')), findsOneWidget);
  });

  testWidgets('无照片:头图走 person 占位且不渲染相册', (tester) async {
    adapter.routes['GET /users/9'] = (options) => ok(publicProfileJson(photos: const []));
    await pumpProfile(tester);

    expect(find.byIcon(Icons.person_rounded), findsOneWidget);
    expect(find.text('相册'), findsNothing);
    expect(find.byKey(const Key('user.album.photo:0')), findsNothing);
  });

  testWidgets('在线 → 头图显示呼吸点与「在线」', (tester) async {
    adapter.routes['GET /users/9'] = (options) => ok(publicProfileJson());
    adapter.routes['GET /presence'] = (options) => ok({
          'results': [
            {'user_id': 9, 'online': true, 'last_active_at': null}
          ]
        });
    // 在线时头图有呼吸点(无限动画),不能 pumpAndSettle —— 这里自己铺一遍流程
    final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
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
        GoRoute(path: '/', builder: (context, state) => const Scaffold(body: Text('首页'))),
        GoRoute(
          path: '/users/:id',
          builder: (context, state) => UserProfilePage(
            userId: int.parse(state.pathParameters['id']!),
            heroTag: state.extra as String?,
          ),
        ),
      ],
    );
    await tester.pumpWidget(UncontrolledProviderScope(
      container: container,
      child: MaterialApp.router(routerConfig: router),
    ));
    await tester.pumpAndSettle();
    router.push('/users/9');
    await pumpFrames(tester);

    expect(find.text('在线'), findsOneWidget);
    expect(find.byKey(const Key('user.onlineDot')), findsOneWidget);
  });

  testWidgets('离线 → 不显示在线行', (tester) async {
    adapter.routes['GET /users/9'] = (options) => ok(publicProfileJson());
    adapter.routes['GET /presence'] = (options) => ok({
          'results': [
            {'user_id': 9, 'online': false, 'last_active_at': null}
          ]
        });
    await pumpProfile(tester);

    expect(find.text('在线'), findsNothing);
  });

  testWidgets('heroTag 由路由 extra 传入 → 头图包 Hero', (tester) async {
    adapter.routes['GET /users/9'] = (options) => ok(publicProfileJson());
    await pumpProfile(tester, heroTag: 'avatar-post-1');

    final hero = tester.widget<AvatarHero>(find.byType(AvatarHero));
    expect(hero.tag, 'avatar-post-1');
  });

  testWidgets('无 heroTag(深链)→ 不包 Hero', (tester) async {
    adapter.routes['GET /users/9'] = (options) => ok(publicProfileJson());
    await pumpProfile(tester);

    expect(find.byType(Hero), findsNothing);
  });

  testWidgets('点返回键 → 回到上一页', (tester) async {
    adapter.routes['GET /users/9'] = (options) => ok(publicProfileJson());
    await pumpProfile(tester);

    await tester.tap(find.byKey(const Key('user.back')));
    await tester.pumpAndSettle();
    expect(find.text('首页'), findsOneWidget);
  });
}
