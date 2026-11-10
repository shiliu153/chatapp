// 多选删除的真机交互判定(批次 T-2 / issue #236)。
//
// 为什么单开一条 integration_test:多选模式与长按菜单是**两套手势叠在同一条气泡上**。
// widget 测试在 800×600 里跑,气泡几乎不需要滚动、热区也不紧张;真机是 411×914dp,
// 底部还要让位给操作条。这类「画得出来但点不动 / 点串了」的毛病单测抓不住
// (同 `discovery_filter_test.dart` 立这条轨的理由)。
//
// 这条用例在**真实设备布局**上用真实指针事件钉住三件事:
// 1. 长按气泡能弹出菜单、菜单里的「多选」点得中;
// 2. 进多选后点消息本体是**切换选中**(顶栏计数必须跟着变);
// 3. 底部「删除」→ 确认框 → 确认之后,那两条真的从列表里消失。
//
// 后端**不可达也不影响**:Dio 换成 `ScriptedAdapter`、IM 换成 `FakeImClient`,
// 全程不碰网络(与 `smoke_test.dart` 的 `API_BASE=127.0.0.1:1` 口径一致)。

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:integration_test/integration_test.dart';

import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/core/theme/app_theme.dart';
import 'package:chatapp_app/features/auth/session.dart';
import 'package:chatapp_app/features/chat/chat_page.dart';
import 'package:chatapp_app/features/presence/presence_controller.dart';
import 'package:chatapp_app/im/im_client.dart';
import 'package:chatapp_app/im/im_manager.dart';

import '../test/support/fake_im_client.dart';
import '../test/support/sample_data.dart';
import '../test/support/scripted_adapter.dart';

ChatMessage _text(String id, String text) => ChatMessage(
      msgId: id,
      peerId: 'u9',
      isSelf: id == '2',
      timestamp: DateTime.now().millisecondsSinceEpoch,
      kind: ChatMessageKind.text,
      text: text,
    );

/// 直接当已登录:真登录要打网络,而这条用例只验手势与列表变化。
class _LoggedInImManager extends ImManager {
  @override
  ImStatus build() => const ImLoggedIn('u3');
}

class _LoggedInSession extends SessionController {
  @override
  SessionState build() => const SessionLoggedIn();
}

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('长按 → 多选 → 勾两条 → 删除:列表真的少两条', (tester) async {
    final adapter = ScriptedAdapter({
      'GET /matches': (options) => ok(pageJson([matchJson(userId: 9, nickname: '小红')])),
      'GET /users/me': (options) => ok(profileJson()),
      'GET /presence': (options) => ok({'results': []}),
    });
    final dio = Dio(BaseOptions(baseUrl: 'http://127.0.0.1:1/api/v1'))
      ..httpClientAdapter = adapter;
    final fake = FakeImClient()
      ..history = {
        'u9': [
          _text('1', '第一条'),
          _text('2', '第二条'),
          _text('3', '第三条'),
        ],
      };
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
      initialLocation: '/chat/u9',
      routes: [
        GoRoute(
          path: '/chat/:peerId',
          builder: (context, state) => ChatPage(peerId: state.pathParameters['peerId']!),
        ),
      ],
    );
    await tester.pumpWidget(UncontrolledProviderScope(
      container: container,
      child: MaterialApp.router(
        theme: buildAppTheme(brightness: Brightness.light),
        routerConfig: router,
      ),
    ));
    await tester.pumpAndSettle();

    // ① 长按第一条 → 菜单点「多选」→ 顶栏「已选 0 条」
    await tester.longPress(find.byKey(const Key('chat.bubble:1')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('chat.menu.multi')), findsOneWidget,
        reason: '长按没有弹出菜单,或菜单里没有「多选」入口');
    await tester.tap(find.byKey(const Key('chat.menu.multi')));
    await tester.pumpAndSettle();
    expect(find.text('已选 0 条'), findsOneWidget);

    // ② 点两条消息 → 「已选 2 条」(点的是气泡本体:真实 hit test)
    await tester.tap(find.byKey(const Key('chat.bubble:1')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('chat.bubble:3')));
    await tester.pumpAndSettle();
    expect(find.text('已选 2 条'), findsOneWidget,
        reason: '点气泡没有切换选中(多选模式下气泡本体必须吃得到指针事件)');

    // ③ 删除 → 确认 → 列表少两条
    await tester.tap(find.byKey(const Key('chat.select.delete')));
    await tester.pumpAndSettle();
    expect(find.text('只在你这边删除,对方仍可见。'), findsOneWidget);
    await tester.tap(find.byKey(const Key('chat.select.confirm')));
    await tester.pumpAndSettle();

    expect(fake.log.where((line) => line.startsWith('delete:')).length, 1,
        reason: '多选删除必须是一次批量调用,不能一条一个请求');
    expect(find.text('第一条'), findsNothing);
    expect(find.text('第三条'), findsNothing);
    expect(find.text('第二条'), findsOneWidget);
    expect(find.byKey(const Key('chat.select.count')), findsNothing,
        reason: '删完应退出多选,回到正常输入态');
  });
}
