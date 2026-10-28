import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/features/chat/voice_playback.dart';
import 'package:chatapp_app/features/chat/widgets/voice_bubble.dart';
import 'package:chatapp_app/im/im_client.dart';

import '../../support/fake_voice.dart';

ChatMessage _voice({int durationMs = 12500, bool isSelf = false, String? url}) => ChatMessage(
      msgId: 'v1',
      peerId: 'u9',
      isSelf: isSelf,
      timestamp: 0,
      kind: ChatMessageKind.voice,
      voiceUrl: url ?? 'http://cdn/media/chat/voices/a.m4a',
      voiceDurationMs: durationMs,
    );

void main() {
  testWidgets('语音气泡显示秒数,点一下播放,再点暂停', (tester) async {
    final player = FakeVoicePlayer();
    await tester.pumpWidget(ProviderScope(
      overrides: [voicePlayerProvider.overrideWithValue(player)],
      child: MaterialApp(
        home: Scaffold(body: VoiceBubble(message: _voice())),
      ),
    ));

    expect(find.text('13″'), findsOneWidget);

    await tester.tap(find.byKey(const Key('voice.play')));
    await tester.pump();
    expect(player.played.single, 'http://cdn/media/chat/voices/a.m4a');

    await tester.tap(find.byKey(const Key('voice.play')));
    await tester.pump();
    expect(player.stopped, isNotEmpty);
  });

  testWidgets('本地文件优先(发送中也能听)', (tester) async {
    final player = FakeVoicePlayer();
    await tester.pumpWidget(ProviderScope(
      overrides: [voicePlayerProvider.overrideWithValue(player)],
      child: MaterialApp(
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
}
