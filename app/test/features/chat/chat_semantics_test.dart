import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/theme/app_theme.dart';
import 'package:chatapp_app/features/chat/voice_playback.dart';
import 'package:chatapp_app/features/chat/widgets/conversation_tile.dart';
import 'package:chatapp_app/features/chat/widgets/message_bubble.dart';
import 'package:chatapp_app/im/im_client.dart';

import '../../support/fake_voice.dart';

/// 读屏口径断言(E-5.3 page spec §6 第 3 条 / 「余烬 Ember」§8.4):
///
/// - 会话行读作「昵称，最后一条，时间，N 条未读」;
/// - 气泡读作「我 / 对方，内容，时间，发送状态」。
///
/// 为什么单独一个文件而不并进 golden:golden 比的是**像素**,这里比的是**语义**;
/// 两者失败的修法完全不同(改取值 vs 改 `Semantics` 拼句),分开跑更容易定位。
void main() {
  /// 今天 12:30 —— 同一自然日才会被格式化成 `HH:mm`(否则是 `MM-DD`),
  /// 断言才不会因为跨零点跑测试而抖动。
  DateTime noon() {
    final now = DateTime.now();
    return DateTime(now.year, now.month, now.day, 12, 30);
  }

  Future<void> pumpTile(WidgetTester tester, {int unread = 3}) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: buildAppTheme(brightness: Brightness.light),
        home: Scaffold(
          body: ConversationTile(
            peerId: 'u9',
            name: '小红',
            preview: '晚上一起吃饭吗?',
            timeLabel: '12:30',
            unread: unread,
            onTap: () {},
          ),
        ),
      ),
    );
    await tester.pump();
  }

  ChatMessage text({
    bool isSelf = false,
    bool isPending = false,
    bool isFailed = false,
    ChatMessageKind kind = ChatMessageKind.text,
    int voiceDurationMs = 0,
  }) => ChatMessage(
    msgId: 'm1',
    peerId: 'u9',
    isSelf: isSelf,
    timestamp: noon().millisecondsSinceEpoch,
    kind: kind,
    text: '你好呀',
    isPending: isPending,
    isFailed: isFailed,
    voiceDurationMs: voiceDurationMs,
  );

  /// 断言渲染树里**存在**一句这样的读屏文案。
  ///
  /// 用 `find.bySemanticsLabel` 而不是 `getSemantics(find.byType(...))`:后者取的是
  /// 「该 widget 最近的那个语义节点」,而气泡的句子挂在里层的 `Semantics` 上,
  /// 外层 `AnimatedContainer` 本身没有标签。
  void expectLabel(String label) =>
      expect(find.bySemanticsLabel(label), findsOneWidget);

  testWidgets('会话行读作「昵称，最后一条，时间，N 条未读」', (tester) async {
    final handle = tester.ensureSemantics();
    await pumpTile(tester);

    expectLabel('小红，晚上一起吃饭吗?，12:30，3 条未读');
    handle.dispose();
  });

  testWidgets('会话行没有未读时不念「0 条未读」', (tester) async {
    final handle = tester.ensureSemantics();
    await pumpTile(tester, unread: 0);

    expectLabel('小红，晚上一起吃饭吗?，12:30');
    handle.dispose();
  });

  final fakePlayer = FakeVoicePlayer();

  Future<void> pumpBubble(WidgetTester tester, ChatMessage message) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [voicePlayerProvider.overrideWithValue(fakePlayer)],
        child: MaterialApp(
          theme: buildAppTheme(brightness: Brightness.light),
          home: Scaffold(
            body: Align(
              alignment: Alignment.topLeft,
              child: SizedBox(
                width: 390,
                child: MessageBubble(
                  message: message,
                  peerName: '小红',
                  onRetry: message.isFailed ? () {} : null,
                ),
              ),
            ),
          ),
        ),
      ),
    );
    await tester.pump();
  }

  testWidgets('我方气泡读作「我，内容，时间，发送状态」', (tester) async {
    final handle = tester.ensureSemantics();
    await pumpBubble(tester, text(isSelf: true));

    expectLabel('我，你好呀，12:30，已发送');
    handle.dispose();
  });

  testWidgets('对方气泡读作「对方，内容，时间」(对端消息没有发送状态)', (tester) async {
    final handle = tester.ensureSemantics();
    await pumpBubble(tester, text());

    expectLabel('对方，你好呀，12:30');
    handle.dispose();
  });

  testWidgets('发送中 / 失败的状态也念出来', (tester) async {
    final handle = tester.ensureSemantics();
    await pumpBubble(tester, text(isSelf: true, isPending: true));
    expectLabel('我，你好呀，12:30，发送中');

    await pumpBubble(tester, text(isSelf: true, isFailed: true));
    expectLabel('我，你好呀，12:30，发送失败，点按重发');
    handle.dispose();
  });

  testWidgets('语音气泡念「语音 N 秒」而不是空内容', (tester) async {
    final handle = tester.ensureSemantics();
    await pumpBubble(
      tester,
      text(isSelf: true, kind: ChatMessageKind.voice, voiceDurationMs: 3200),
    );

    expectLabel('我，语音 3 秒，12:30，已发送');
    handle.dispose();
  });
}
