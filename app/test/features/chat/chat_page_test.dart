import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/features/auth/session.dart';
import 'package:chatapp_app/features/chat/chat_page.dart';
import 'package:chatapp_app/im/im_client.dart';
import 'package:chatapp_app/im/im_manager.dart';

import '../../support/fake_im_client.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

ChatMessage _text(String id, {required bool isSelf, required String text}) => ChatMessage(
      msgId: id,
      peerId: 'u9',
      isSelf: isSelf,
      timestamp: DateTime.now().millisecondsSinceEpoch,
      kind: ChatMessageKind.text,
      text: text,
    );

/// 让 IM 直接处于已登录态:testWidgets 的假时钟里裸 await 走 dio 的登录会死锁
/// (dio 内部定时器不推进),登录流程本身在 im_manager_test / session_test 里测。
class _LoggedInImManager extends ImManager {
  @override
  ImStatus build() => const ImLoggedIn('u3');
}

/// 会话也直接当已登录(matches 缓存依赖它才会去拉数据)。
class _LoggedInSession extends SessionController {
  @override
  SessionState build() => const SessionLoggedIn();
}

void main() {
  late ScriptedAdapter adapter;
  late FakeImClient fake;
  late ProviderContainer container;

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    adapter = ScriptedAdapter({
      'GET /matches': (options) => ok([matchJson(userId: 9, nickname: '小红')]),
    });
    fake = FakeImClient();
    addTearDown(fake.dispose);
  });

  Future<void> pumpChat(WidgetTester tester, {String peerId = 'u9'}) async {
    final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
    container = ProviderContainer(overrides: [
      baseDioProvider.overrideWithValue(dio),
      refreshDioProvider.overrideWithValue(dio),
      imClientProvider.overrideWithValue(fake),
      imStatusProvider.overrideWith(_LoggedInImManager.new),
      sessionProvider.overrideWith(_LoggedInSession.new),
    ]);
    addTearDown(container.dispose);
    final router = GoRouter(
      initialLocation: '/chat/$peerId',
      routes: [
        GoRoute(
          path: '/chat/:peerId',
          builder: (context, state) => ChatPage(peerId: state.pathParameters['peerId']!),
        ),
        GoRoute(
          path: '/users/:id',
          builder: (context, state) =>
              Scaffold(body: Text('资料卡:${state.pathParameters['id']}')),
        ),
      ],
    );
    await tester.pumpWidget(UncontrolledProviderScope(
      container: container,
      child: MaterialApp.router(routerConfig: router),
    ));
    await tester.pumpAndSettle();
  }

  testWidgets('历史消息上屏;标题用 matches 缓存里的昵称', (tester) async {
    fake.history = {
      'u9': [
        _text('m1', isSelf: false, text: '你好'),
        _text('m2', isSelf: true, text: '嗨'),
      ],
    };
    await pumpChat(tester);

    expect(find.text('小红'), findsOneWidget);
    expect(find.text('你好'), findsOneWidget);
    expect(find.text('嗨'), findsOneWidget);
  });

  testWidgets('match_notice → 居中灰条', (tester) async {
    fake.history = {
      'u9': [
        const ChatMessage(
          msgId: 'm1',
          peerId: 'u9',
          isSelf: false,
          timestamp: 1700000000000,
          kind: ChatMessageKind.matchNotice,
          text: '你们已互相喜欢,开始聊天吧',
        ),
      ],
    };
    await pumpChat(tester);

    expect(find.byKey(const Key('chat.notice')), findsOneWidget);
    expect(find.text('你们已互相喜欢,开始聊天吧'), findsOneWidget);
  });

  testWidgets('ban_notice → 居中灰条', (tester) async {
    fake.history = {
      'system_notice': [
        const ChatMessage(
          msgId: 's1',
          peerId: 'system_notice',
          isSelf: false,
          timestamp: 1700000000000,
          kind: ChatMessageKind.banNotice,
          text: '您的账号因「骚扰他人」被限制。',
        ),
      ],
    };
    await pumpChat(tester, peerId: 'system_notice');

    expect(find.byKey(const Key('chat.notice')), findsOneWidget);
    expect(find.text('您的账号因「骚扰他人」被限制。'), findsOneWidget);
  });

  testWidgets('输入发送 → 气泡上屏 + 调 SDK;清空输入框', (tester) async {
    await pumpChat(tester);

    await tester.enterText(find.byKey(const Key('chat.input')), '你好呀');
    await tester.tap(find.byKey(const Key('chat.send')));
    await tester.pumpAndSettle();

    expect(find.text('你好呀'), findsOneWidget);
    expect(fake.log, contains('send:u9:你好呀'));
    expect(tester.widget<TextField>(find.byKey(const Key('chat.input'))).controller!.text, isEmpty);
  });

  testWidgets('发送失败 → 气泡保留 + 叹号;点叹号重发成功', (tester) async {
    fake.sendError = const ImException(6013, 'network');
    await pumpChat(tester);

    await tester.enterText(find.byKey(const Key('chat.input')), '你好');
    await tester.tap(find.byKey(const Key('chat.send')));
    await tester.pumpAndSettle();

    expect(find.text('你好'), findsOneWidget); // 消息还在
    expect(find.byKey(const Key('chat.retry')), findsOneWidget); // 有叹号

    fake.sendError = null; // 网络恢复
    await tester.tap(find.byKey(const Key('chat.retry')));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('chat.retry')), findsNothing);
    expect(fake.log.where((l) => l == 'send:u9:你好').length, 2); // 重发走了 send
  });

  testWidgets('收到实时消息 → 立即上屏', (tester) async {
    await pumpChat(tester);

    fake.emitIncoming('u9', '在吗');
    await tester.pumpAndSettle();

    expect(find.text('在吗'), findsOneWidget);
  });

  testWidgets('点标题进对方资料卡', (tester) async {
    await pumpChat(tester);

    await tester.tap(find.byKey(const Key('chat.title')));
    await tester.pumpAndSettle();

    expect(find.text('资料卡:9'), findsOneWidget);   // u9 → 用户 9
  });
}
