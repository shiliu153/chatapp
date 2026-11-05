import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/features/auth/session.dart';
import 'package:chatapp_app/features/chat/chat_page.dart';
import 'package:chatapp_app/features/presence/presence_controller.dart';
import 'package:chatapp_app/im/im_client.dart';
import 'package:chatapp_app/im/im_manager.dart';

import '../../support/fake_im_client.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';
import '../../support/heart_theme.dart';

/// 已读回执的页面级测试:两条链路(实时下行 `read` 帧 / 打开会话补拉)都要覆盖。
///
/// 关键判定:`MessageBubble` 只在**我方**消息且 `seq > 0 && seq <= peerReadSeq` 时
/// 渲染 `chat.status.read` 这个 key,所以直接用 key 计数最稳,不去比文案。

ChatMessage _text(
  String id, {
  required bool isSelf,
  required String text,
  int seq = 0,
  bool isPending = false,
  ChatMessageKind kind = ChatMessageKind.text,
}) =>
    ChatMessage(
      msgId: id,
      peerId: 'u9',
      isSelf: isSelf,
      timestamp: DateTime.now().millisecondsSinceEpoch,
      kind: kind,
      text: text,
      seq: seq,
      isPending: isPending,
    );

/// 让 IM 直接处于已登录态(测试的假时钟里裸 await 走 dio 的登录会死锁)。
class _LoggedInImManager extends ImManager {
  @override
  ImStatus build() => const ImLoggedIn('u3');
}

/// 会话也直接当已登录,否则 matches 缓存不会去拉数据。
class _LoggedInSession extends SessionController {
  @override
  SessionState build() => const SessionLoggedIn();
}

void main() {
  late ScriptedAdapter adapter;
  late FakeImClient fake;

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    adapter = ScriptedAdapter({
      'GET /matches': (options) => ok(pageJson([matchJson(userId: 9, nickname: '小红')])),
      'GET /users/me': (options) => ok(profileJson()),
      'GET /presence': (options) => ok({'results': []}),
    });
    fake = FakeImClient();
    addTearDown(fake.dispose);
  });

  Future<void> pumpChat(WidgetTester tester,
      {List<Override> overrides = const []}) async {
    final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
    final container = ProviderContainer(overrides: [
      baseDioProvider.overrideWithValue(dio),
      refreshDioProvider.overrideWithValue(dio),
      imClientProvider.overrideWithValue(fake),
      imStatusProvider.overrideWith(_LoggedInImManager.new),
      sessionProvider.overrideWith(_LoggedInSession.new),
      presenceRefreshIntervalProvider.overrideWithValue(null),
      ...overrides,
    ]);
    addTearDown(container.dispose);
    final router = GoRouter(
      initialLocation: '/chat/u9',
      routes: [
        GoRoute(
          path: '/chat/:peerId',
          builder: (context, state) => ChatPage(
            peerId: state.pathParameters['peerId']!,
            pickImage: () async => null,
          ),
        ),
      ],
    );
    await tester.pumpWidget(UncontrolledProviderScope(
      container: container,
      child: MaterialApp.router(theme: heartTheme, routerConfig: router),
    ));
    await tester.pumpAndSettle();
  }

  testWidgets('打开会话时从会话列表补拉:只有 seq<=peer_read_seq 的我方消息显示已读',
      (tester) async {
    fake.history = {
      'u9': [
        _text('m1', isSelf: true, text: '我发的一', seq: 1),
        _text('m2', isSelf: true, text: '我发的二', seq: 2),
      ],
    };
    // 对端只读到 1(离线期间读过一次,本地重连时不知道,靠这次补拉)
    fake.conversations = const [
      ImConversation(peerId: 'u9', unreadCount: 0, peerReadSeq: 1),
    ];
    await pumpChat(tester);

    expect(find.byKey(const Key('chat.status.read')), findsOneWidget);
    expect(find.text('我发的一'), findsOneWidget);
  });

  testWidgets('收到下行 read 帧:已读标记出现,且旧值不回退', (tester) async {
    fake.history = {
      'u9': [
        _text('m1', isSelf: true, text: '我发的一', seq: 1),
        _text('m2', isSelf: true, text: '我发的二', seq: 2),
      ],
    };
    await pumpChat(tester);
    expect(find.byKey(const Key('chat.status.read')), findsNothing);

    fake.emitPeerRead('u9', 2);
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('chat.status.read')), findsNWidgets(2));

    // 乱序到达的旧帧(seq=1)不能把「已读」推回去
    fake.emitPeerRead('u9', 1);
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('chat.status.read')), findsNWidgets(2));
  });

  testWidgets('发送中优先于已读', (tester) async {
    fake.history = {
      'u9': [
        _text('m1', isSelf: true, text: '还在发', seq: 1, isPending: true),
      ],
    };
    fake.conversations = const [
      ImConversation(peerId: 'u9', unreadCount: 0, peerReadSeq: 1),
    ];
    await pumpChat(tester);

    expect(find.byKey(const Key('chat.status.pending')), findsOneWidget);
    expect(find.byKey(const Key('chat.status.read')), findsNothing);
  });

  testWidgets('对方消息与灰条不显示已读', (tester) async {
    fake.history = {
      'u9': [
        _text('m1', isSelf: false, text: '对方说的', seq: 1),
        _text('m2', isSelf: true, text: '撮合成功', seq: 2, kind: ChatMessageKind.matchNotice),
      ],
    };
    fake.conversations = const [
      ImConversation(peerId: 'u9', unreadCount: 0, peerReadSeq: 2),
    ];
    await pumpChat(tester);

    expect(find.byKey(const Key('chat.status.read')), findsNothing);
  });

  testWidgets('实现不支持已读回执时不显示已读', (tester) async {
    fake.readReceiptCapability = false;
    fake.history = {
      'u9': [_text('m1', isSelf: true, text: '我发的一', seq: 1)],
    };
    fake.conversations = const [
      ImConversation(peerId: 'u9', unreadCount: 0, peerReadSeq: 1),
    ];
    await pumpChat(tester);

    expect(find.byKey(const Key('chat.status.read')), findsNothing);
  });
}
