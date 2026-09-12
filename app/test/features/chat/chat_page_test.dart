import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/image_pick.dart';
import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/features/auth/session.dart';
import 'package:chatapp_app/features/chat/chat_page.dart';
import 'package:chatapp_app/im/im_client.dart';
import 'package:image_picker/image_picker.dart';
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

ChatMessage _textAt(String id, DateTime time, {required String text, bool isSelf = false}) =>
    ChatMessage(
      msgId: id,
      peerId: 'u9',
      isSelf: isSelf,
      timestamp: time.millisecondsSinceEpoch,
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
      'GET /matches': (options) => ok(pageJson([matchJson(userId: 9, nickname: '小红')])),
      'GET /users/me': (options) => ok(profileJson()),
    });
    fake = FakeImClient();
    addTearDown(fake.dispose);
  });

  Future<void> pumpChat(WidgetTester tester,
      {String peerId = 'u9', PickImage? pickImage}) async {
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
          builder: (context, state) => ChatPage(
            peerId: state.pathParameters['peerId']!,
            pickImage: pickImage ?? () async => null,
          ),
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

  testWidgets('超过 5 分钟的两个消息之间出现时间条', (tester) async {
    final base = DateTime.now().subtract(const Duration(hours: 1));
    fake.history = {
      'u9': [
        _textAt('m1', base, text: '早'),
        _textAt('m2', base.add(const Duration(minutes: 6)), text: '晚'),
      ],
    };
    await pumpChat(tester);

    expect(find.byKey(const Key('chat.time')), findsNWidgets(2));
  });

  testWidgets('长按消息 → 复制进剪贴板', (tester) async {
    final calls = <MethodCall>[];
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
        SystemChannels.platform, (call) async {
      calls.add(call);
      return null;
    });
    addTearDown(() => tester.binding.defaultBinaryMessenger
        .setMockMethodCallHandler(SystemChannels.platform, null));

    fake.history = {
      'u9': [_text('m1', isSelf: false, text: '你好')],
    };
    await pumpChat(tester);

    await tester.longPress(find.text('你好'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('chat.menu.copy')));
    await tester.pumpAndSettle();

    expect(calls.any((c) => c.method == 'Clipboard.setData'), isTrue);
  });

  testWidgets('长按消息 → 删除本机', (tester) async {
    fake.history = {
      'u9': [_text('m1', isSelf: false, text: '再见')],
    };
    await pumpChat(tester);

    await tester.longPress(find.text('再见'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('chat.menu.delete')));
    await tester.pumpAndSettle();

    expect(find.text('再见'), findsNothing);
    expect(fake.log, contains('delete:m1'));
  });

  testWidgets('缓存里没有对方时,标题降级用 IM 会话名', (tester) async {
    adapter = ScriptedAdapter({
      'GET /matches': (options) => ok(pageJson([])),
      'GET /users/me': (options) => ok(profileJson()),
    });
    fake.conversations = [
      const ImConversation(peerId: 'u9', unreadCount: 0, showName: '小鹿'),
    ];
    await pumpChat(tester);

    expect(find.text('小鹿'), findsOneWidget);
  });

  testWidgets('表情面板:点选插入输入框', (tester) async {
    await pumpChat(tester);
    await tester.tap(find.byKey(const Key('chat.emoji.button')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('chat.emoji.panel')), findsOneWidget);

    await tester.tap(find.byKey(const Key('chat.emoji.😀')));
    await tester.pumpAndSettle();
    expect(tester.widget<TextField>(find.byKey(const Key('chat.input'))).controller!.text,
        contains('😀'));
  });

  testWidgets('＋面板选图 → 发出图片消息', (tester) async {
    await pumpChat(tester, pickImage: () async => XFile('fake.png'));
    await tester.tap(find.byKey(const Key('chat.more.button')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('chat.more.image')));
    await tester.pumpAndSettle();

    expect(fake.log, contains('sendImage:u9:fake.png'));
    expect(find.byKey(const Key('chat.image')), findsWidgets);
  });

  testWidgets('点图片气泡 → 打开全屏查看', (tester) async {
    fake.history = {
      'u9': [
        const ChatMessage(
            msgId: 'i1',
            peerId: 'u9',
            isSelf: false,
            timestamp: 1,
            kind: ChatMessageKind.image,
            imageUrl: 'https://x/1.png'),
      ],
    };
    await pumpChat(tester);

    await tester.tap(find.byKey(const Key('chat.image')));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('viewer.page')), findsOneWidget);
  });
}
