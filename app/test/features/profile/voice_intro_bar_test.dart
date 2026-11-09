import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/features/chat/voice_playback.dart';
import 'package:chatapp_app/features/profile/widgets/voice_intro_bar.dart';

import '../../support/fake_voice.dart';
import '../../support/harness.dart';
import '../../support/scripted_adapter.dart';

void main() {
  Future<void> pumpBar(
    WidgetTester tester,
    FakeVoicePlayer player, {
    String source = 'http://test/media/voices/intro.m4a',
    int durationMs = 18000,
    bool isLocal = false,
  }) =>
      pumpPage(
        tester,
        ScriptedAdapter({}),
        Scaffold(
          body: Padding(
            padding: const EdgeInsets.all(16),
            child: VoiceIntroBar(
              source: source,
              durationMs: durationMs,
              isLocal: isLocal,
              keyPrefix: 'voice',
            ),
          ),
        ),
        overrides: [voicePlayerProvider.overrideWithValue(player)],
      );

  testWidgets('点播放 → 播这个地址,图标切暂停;再点 → 停', (tester) async {
    final player = FakeVoicePlayer();
    await pumpBar(tester, player);

    expect(find.text('0:00 / 0:18'), findsOneWidget);
    await tester.tap(find.byKey(const Key('voice.play')));
    await tester.pump();

    expect(player.played, ['http://test/media/voices/intro.m4a']);
    expect(player.lastIsLocal, isFalse);
    expect(find.byIcon(Icons.pause_rounded), findsOneWidget);

    await tester.tap(find.byKey(const Key('voice.play')));
    await tester.pump();
    expect(player.stopped, ['http://test/media/voices/intro.m4a']);
    expect(find.byIcon(Icons.play_arrow_rounded), findsOneWidget);
  });

  testWidgets('进度回调 → 进度文案跟着走;播完复位', (tester) async {
    final player = FakeVoicePlayer();
    await pumpBar(tester, player);
    await tester.tap(find.byKey(const Key('voice.play')));
    await tester.pump();

    player.emitPosition(const Duration(seconds: 6));
    // 进度走 Stream 回调:一帧派发事件,一帧重建。
    await tester.pump();
    await tester.pump();
    expect(find.text('0:06 / 0:18'), findsOneWidget);

    player.finish();
    await tester.pump();
    await tester.pump();
    expect(find.text('0:00 / 0:18'), findsOneWidget);
    expect(find.byIcon(Icons.play_arrow_rounded), findsOneWidget);
  });

  testWidgets('加载失败 → 「播放失败,点击重试」,再点一次可重试', (tester) async {
    final player = FakeVoicePlayer()..failPlay = true;
    await pumpBar(tester, player);

    await tester.tap(find.byKey(const Key('voice.play')));
    await tester.pump();

    expect(find.text('播放失败,点击重试'), findsOneWidget);
    expect(find.byIcon(Icons.refresh_rounded), findsOneWidget);

    player.failPlay = false;
    await tester.tap(find.byKey(const Key('voice.play')));
    await tester.pump();
    expect(player.played, ['http://test/media/voices/intro.m4a']);
    expect(find.byIcon(Icons.pause_rounded), findsOneWidget);
  });

  testWidgets('本地录音试听走 DeviceFileSource(isLocal)', (tester) async {
    final player = FakeVoicePlayer();
    await pumpBar(tester, player,
        source: '/tmp/voice.m4a', durationMs: 3000, isLocal: true);

    await tester.tap(find.byKey(const Key('voice.play')));
    await tester.pump();

    expect(player.played, ['/tmp/voice.m4a']);
    expect(player.lastIsLocal, isTrue);
    expect(find.text('0:00 / 0:03'), findsOneWidget);
  });
}
