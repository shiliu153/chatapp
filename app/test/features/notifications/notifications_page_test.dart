import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/features/notifications/notifications_page.dart';

import '../../support/fake_im_client.dart';
import '../../support/harness.dart';
import '../../support/heart_theme.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

const _loggedIn = {'auth.access': 'a', 'auth.refresh': 'r', 'auth.user_id': 3};

ScriptedAdapter _chatAdapter({Map<String, dynamic>? notifications}) => ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
      'POST /im/user_sig': (options) => ok({
            'backend': 'self',
            'token': 'tok',
            'ws_url': 'ws://test/im/ws',
            'http_url': 'http://test/im/api',
            'im_user_id': 'u3',
            'expire': 86400,
          }),
      'GET /matches': (options) => ok(pageJson([])),
      'GET /presence': (options) => ok({'results': []}),
      'GET /notifications/unread_count': (options) => ok({'unread': 3}),
      if (notifications != null) 'GET /notifications': (options) => ok(notifications),
      'POST /notifications/read': (options) => ok(const <String, dynamic>{}, status: 204),
      'GET /posts/9': (options) => ok(postJson(id: 9, nickname: 'Alice')),
      'GET /posts/9/comments': (options) => ok(pageJson([])),
    });

/// 只 pump 通知页本身(不经过路由):给空态 / 列表 / 错误态用。
Future<void> _pumpStandalone(WidgetTester tester, ScriptedAdapter adapter) async {
  final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
  final container = ProviderContainer(overrides: [
    baseDioProvider.overrideWithValue(dio),
    refreshDioProvider.overrideWithValue(dio),
  ]);
  addTearDown(container.dispose);
  await tester.pumpWidget(UncontrolledProviderScope(
    container: container,
    child: MaterialApp(theme: heartTheme, home: const NotificationsPage()),
  ));
  await pumpFrames(tester);
}

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  testWidgets('空态:标题 + 文案 + 无未读点', (tester) async {
    final adapter = ScriptedAdapter({
      'GET /notifications': (options) => ok(cursorPageJson([])),
    });
    await _pumpStandalone(tester, adapter);

    expect(find.byKey(const Key('notifications.empty')), findsOneWidget);
    expect(find.text('还没有通知'), findsOneWidget);
    expect(find.byKey(const Key('notifications.unreadDot')), findsNothing);
  });

  testWidgets('列表:正文/时间/未读点;已读行无未读点', (tester) async {
    final adapter = ScriptedAdapter({
      'GET /notifications': (options) => ok(cursorPageJson([
            notificationJson(id: 2, text: '小明 赞了你的动态'),
            notificationJson(id: 1, text: '小红 评论了你的动态:写得好', isRead: true),
          ])),
    });
    await _pumpStandalone(tester, adapter);

    expect(find.text('小明 赞了你的动态'), findsOneWidget);
    expect(find.text('小红 评论了你的动态:写得好'), findsOneWidget);
    expect(find.byKey(const Key('notifications.unreadDot')), findsOneWidget);
    expect(find.byKey(const Key('notifications.row.2')), findsOneWidget);
    expect(find.byKey(const Key('notifications.row.1')), findsOneWidget);
  });

  testWidgets('加载失败 → 错误态,重试成功', (tester) async {
    final adapter = ScriptedAdapter({'GET /notifications': offline});
    await _pumpStandalone(tester, adapter);
    expect(find.byKey(const Key('notifications.retry')), findsOneWidget);

    adapter.routes['GET /notifications'] = (options) =>
        ok(cursorPageJson([notificationJson(id: 2, text: '小明 赞了你的动态')]));
    await tester.tap(find.byKey(const Key('notifications.retry')));
    await pumpFrames(tester);
    expect(find.text('小明 赞了你的动态'), findsOneWidget);
  });

  testWidgets('消息页铃铛角标 → 进通知页 → 点一条标已读并跳动态详情', (tester) async {
    final adapter = _chatAdapter(
      notifications: cursorPageJson([
        notificationJson(id: 2, text: '小明 赞了你的动态', targetKind: 'post', targetId: 9),
      ]),
    );
    await pumpApp(tester, adapter, prefs: _loggedIn, imClient: FakeImClient());
    await tester.pumpAndSettle();
    await tester.tap(navTab('消息'));
    await tester.pumpAndSettle();

    // 铃铛角标 = 未读数
    expect(find.byKey(const Key('chats.notifications')), findsOneWidget);
    expect(find.text('3'), findsOneWidget);

    await tester.tap(find.byKey(const Key('chats.notifications')));
    await tester.pumpAndSettle();
    expect(find.text('通知'), findsOneWidget);
    expect(find.text('小明 赞了你的动态'), findsOneWidget);

    await tester.tap(find.byKey(const Key('notifications.row.2')));
    await tester.pumpAndSettle();

    final read = adapter.log.lastWhere((item) => item.path == '/notifications/read');
    expect(read.data, {
      'ids': [2],
    });
    expect(find.text('动态详情'), findsOneWidget);
  });
}
