import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/features/chat/voice_playback.dart';
import 'package:chatapp_app/features/chat/widgets/voice_bubble.dart';
import 'package:chatapp_app/im/im_client.dart';

import '../../support/fake_voice.dart';
import '../../support/heart_theme.dart';

ChatMessage _voice({String id = 'v1', int durationMs = 12500, bool isSelf = false, String? url}) =>
    ChatMessage(
      msgId: id,
      peerId: 'u9',
      isSelf: isSelf,
      timestamp: 0,
      kind: ChatMessageKind.voice,
      voiceUrl: url ?? 'http://cdn/media/chat/voices/$id.m4a',
      voiceDurationMs: durationMs,
    );

/// 把若干气泡挂起来,每个包一层带 key 的 Padding:多气泡用例靠它定位「哪一个」。
Future<void> _pumpBubbles(WidgetTester tester, FakeVoicePlayer player,
    Map<String, ChatMessage> bubbles) async {
  await tester.pumpWidget(ProviderScope(
    overrides: [voicePlayerProvider.overrideWithValue(player)],
    child: MaterialApp(
      theme: heartTheme,
      home: Scaffold(
        body: Column(
          children: [
            for (final entry in bubbles.entries)
              Padding(
                key: Key(entry.key),
                padding: const EdgeInsets.all(8),
                child: VoiceBubble(message: entry.value),
              ),
          ],
        ),
      ),
    ),
  ));
}

void main() {
  testWidgets('语音气泡显示秒数,点一下播放,再点暂停', (tester) async {
    final player = FakeVoicePlayer();
    await tester.pumpWidget(ProviderScope(
      overrides: [voicePlayerProvider.overrideWithValue(player)],
      child: MaterialApp(
        theme: heartTheme,
        home: Scaffold(body: VoiceBubble(message: _voice())),
      ),
    ));

    expect(find.text('13″'), findsOneWidget);

    await tester.tap(find.byKey(const Key('voice.play')));
    await tester.pump();
    expect(player.played.single, 'http://cdn/media/chat/voices/v1.m4a');
    // 开始播放时按本条倍速(1.0)设一遍:这是「换条复位」的落点
    expect(player.rates.last, 1.0);

    await tester.tap(find.byKey(const Key('voice.play')));
    await tester.pump();
    expect(player.stopped, isNotEmpty);
  });

  testWidgets('本地文件优先(发送中也能听)', (tester) async {
    final player = FakeVoicePlayer();
    await tester.pumpWidget(ProviderScope(
      overrides: [voicePlayerProvider.overrideWithValue(player)],
      child: MaterialApp(
        theme: heartTheme,
        home: Scaffold(
          body: VoiceBubble(
            message: ChatMessage(
              msgId: 'v2',
              peerId: 'u9',
              isSelf: true,
              timestamp: 0,
              kind: ChatMessageKind.voice,
              localPath: '/tmp/a.m4a',
              voiceDurationMs: 3000,
            ),
          ),
        ),
      ),
    ));

    await tester.tap(find.byKey(const Key('voice.play')));
    await tester.pump();
    expect(player.played.single, '/tmp/a.m4a');
  });

  testWidgets('拖动进度条:松手才 seek,拖动期间不跟播放进度跑', (tester) async {
    final player = FakeVoicePlayer();
    await tester.pumpWidget(ProviderScope(
      overrides: [voicePlayerProvider.overrideWithValue(player)],
      child: MaterialApp(
        theme: heartTheme,
        home: Scaffold(body: VoiceBubble(message: _voice())),
      ),
    ));
    await tester.tap(find.byKey(const Key('voice.play')));
    await tester.pump();

    final slider = find.byKey(const Key('chat.voice.slider'));
    final rect = tester.getRect(slider);
    // 从靠左处按下再往右拖:模拟「拖着找位置」
    final gesture = await tester.startGesture(Offset(rect.left + 8, rect.center.dy));
    await tester.pump();
    await gesture.moveBy(const Offset(50, 0));
    await tester.pump();
    final whileDragging = tester.widget<Slider>(slider).value;
    expect(whileDragging, greaterThan(0));

    // 拖动中播放器回报进度(10 秒):滑块**不能**被拽回去
    player.emitPosition(const Duration(seconds: 10));
    await tester.pump();
    expect(tester.widget<Slider>(slider).value, whileDragging);
    expect(player.seeks, isEmpty, reason: '还没松手就不该 seek,否则会一边拖一边跳');

    await gesture.up();
    await tester.pumpAndSettle();

    expect(player.seeks, hasLength(1));
    expect(player.seeks.single.inMilliseconds, closeTo(whileDragging * 1000, 50));
  });

  testWidgets('倍速按钮循环 1.0x → 1.5x → 2.0x → 1.0x,并同步给播放器', (tester) async {
    final player = FakeVoicePlayer();
    await _pumpBubbles(tester, player, {'a': _voice()});

    expect(find.text('1.0x'), findsOneWidget);

    await tester.tap(find.byKey(const Key('chat.voice.rate')));
    await tester.pump();
    expect(find.text('1.5x'), findsOneWidget);

    await tester.tap(find.byKey(const Key('chat.voice.rate')));
    await tester.pump();
    expect(find.text('2.0x'), findsOneWidget);

    await tester.tap(find.byKey(const Key('chat.voice.rate')));
    await tester.pump();
    expect(find.text('1.0x'), findsOneWidget);

    expect(player.rates, [1.5, 2.0, 1.0]);
  });

  testWidgets('换条播放:上一条复位成「未播」并把倍速归 1.0x', (tester) async {
    final player = FakeVoicePlayer();
    await _pumpBubbles(tester, player, {
      'a': _voice(id: 'va'),
      'b': _voice(id: 'vb'),
    });

    Finder inA(Finder matching) =>
        find.descendant(of: find.byKey(const Key('a')), matching: matching);
    Finder inB(Finder matching) =>
        find.descendant(of: find.byKey(const Key('b')), matching: matching);

    // A 播放并调到 2.0x
    await tester.tap(inA(find.byKey(const Key('voice.play'))));
    await tester.pump();
    await tester.tap(inA(find.byKey(const Key('chat.voice.rate'))));
    await tester.pump();
    await tester.tap(inA(find.byKey(const Key('chat.voice.rate'))));
    await tester.pump();
    expect(inA(find.text('2.0x')), findsOneWidget);
    expect(
      tester.widget<Icon>(inA(find.byKey(const Key('voice.play')))).icon,
      Icons.pause_rounded,
    );

    // 换 B 播:A 必须复位(图标回播放、倍速回 1.0x),否则会「两条同时像在播」
    await tester.tap(inB(find.byKey(const Key('voice.play'))));
    await tester.pumpAndSettle();

    expect(
      tester.widget<Icon>(inA(find.byKey(const Key('voice.play')))).icon,
      Icons.play_arrow_rounded,
    );
    expect(inA(find.text('1.0x')), findsOneWidget);
    expect(
      tester.widget<Icon>(inB(find.byKey(const Key('voice.play')))).icon,
      Icons.pause_rounded,
    );
    expect(player.played, [
      'http://cdn/media/chat/voices/va.m4a',
      'http://cdn/media/chat/voices/vb.m4a',
    ]);
  });
}
