import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/features/profile/profile_voice_io.dart';
import 'package:chatapp_app/im/voice_recorder.dart';

import '../../support/fake_voice.dart';
import '../../support/harness.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

const _loggedIn = {'auth.access': 'a', 'auth.refresh': 'r', 'auth.user_id': 7};

/// 内存版文件读写:widget 测试跑在假时钟 zone 里,真实文件 IO 的 Future 不会完成。
class _FakeVoiceIo implements ProfileVoiceIo {
  final deleted = <String>[];

  @override
  Future<Uint8List> read(String path) async => Uint8List.fromList([0, 1, 2, 3]);

  @override
  Future<void> delete(String path) async => deleted.add(path);
}

void main() {
  late _FakeVoiceIo io;

  setUp(() {
    io = _FakeVoiceIo();
  });

  ScriptedAdapter adapterWith({
    Map<String, dynamic>? voice,
    Responder? upload,
  }) =>
      ScriptedAdapter({
        'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
        'GET /users/me': (options) => ok(profileJson(voice: voice)),
        'GET /users/tags': (options) => ok([tagJson(1, '运动')]),
        'POST /users/me/voice': upload ?? (options) => ok(voiceJson(), status: 201),
      });

  /// 进「我的 → 编辑资料」并滚到语音卡。
  Future<void> openVoiceCard(WidgetTester tester, ScriptedAdapter adapter) async {
    await pumpApp(tester, adapter, prefs: _loggedIn, overrides: [
      voiceRecorderProvider.overrideWithValue(FakeVoiceRecorder()),
      voiceTempPathProvider.overrideWithValue(() async => '/tmp/profile-voice.m4a'),
      profileVoiceIoProvider.overrideWithValue(io),
    ]);
    await tester.pumpAndSettle();
    await tester.tap(navTab('我的'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('my.card.identity')));
    await tester.pumpAndSettle();
    // 编辑页是一个 ListView;页面里还有别的 Scrollable(输入类控件),要指定这一个。
    await tester.scrollUntilVisible(
      find.byKey(const Key('edit.voice.mic')),
      300,
      scrollable:
          find.descendant(of: find.byType(ListView), matching: find.byType(Scrollable)).first,
    );
    await tester.pumpAndSettle();
  }

  /// 卡内按钮会随录音状态换位置(录音后卡片变高),点之前先滚到可见。
  Future<void> tapKey(WidgetTester tester, Key key) async {
    await tester.ensureVisible(find.byKey(key));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(key));
    await tester.pumpAndSettle();
  }

  /// 按住麦克风 1.1 秒(真实时间,跨过最短 1 秒)再松手。
  Future<void> recordOneSecond(WidgetTester tester) async {
    final gesture = await tester
        .startGesture(tester.getCenter(find.byKey(const Key('edit.voice.mic'))));
    await tester.pump(const Duration(milliseconds: 600)); // 触发长按
    await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 1100)));
    await gesture.up();
    await tester.pumpAndSettle();
  }

  testWidgets('未录制:显示按住录音,没有播放条', (tester) async {
    await openVoiceCard(tester, adapterWith());

    expect(find.text('语音自我介绍'), findsOneWidget);
    expect(find.byKey(const Key('edit.voice.mic')), findsOneWidget);
    expect(find.byKey(const Key('edit.voice.saved.play')), findsNothing);
    expect(find.byKey(const Key('edit.voice.upload')), findsNothing);
  });

  testWidgets('按住录音 → 松手 → 保存语音 → 已保存(POST /users/me/voice)', (tester) async {
    final adapter = adapterWith();
    await openVoiceCard(tester, adapter);

    await recordOneSecond(tester);
    expect(find.byKey(const Key('edit.voice.upload')), findsOneWidget);
    expect(find.byKey(const Key('edit.voice.local.play')), findsOneWidget);

    await tapKey(tester, const Key('edit.voice.upload'));

    final post = adapter.log.where((r) => r.method == 'POST' && r.path == '/users/me/voice');
    expect(post, hasLength(1));
    expect(find.byKey(const Key('edit.voice.saved.play')), findsOneWidget);
    expect(find.byKey(const Key('edit.voice.delete')), findsOneWidget);
    expect(find.byKey(const Key('edit.voice.upload')), findsNothing);
    expect(find.text('语音已保存'), findsOneWidget);
    await drainToast(tester);
  });

  testWidgets('上传 400(超 30 秒)→ 弹后端中文提示,本地录音保留可重试', (tester) async {
    final adapter = adapterWith(
        upload: (options) => jsonError(400, '语音不能超过 30 秒'));
    await openVoiceCard(tester, adapter);

    await recordOneSecond(tester);
    await tapKey(tester, const Key('edit.voice.upload'));

    expect(find.text('语音不能超过 30 秒'), findsOneWidget);
    expect(find.byKey(const Key('edit.voice.upload')), findsOneWidget);
    expect(find.byKey(const Key('edit.voice.saved.play')), findsNothing);
    await drainToast(tester);
  });

  testWidgets('上传 413(配额满)→ 弹后端中文提示', (tester) async {
    final adapter = adapterWith(
        upload: (options) => jsonError(413, '存储空间已满,请先删除部分照片'));
    await openVoiceCard(tester, adapter);

    await recordOneSecond(tester);
    await tapKey(tester, const Key('edit.voice.upload'));

    expect(find.text('存储空间已满,请先删除部分照片'), findsOneWidget);
    expect(find.byKey(const Key('edit.voice.upload')), findsOneWidget);
    await drainToast(tester);
  });

  testWidgets('已有语音:显示播放条;删除 → DELETE + 播放条消失', (tester) async {
    final adapter = adapterWith(voice: voiceJson());
    adapter.routes['DELETE /users/me/voice'] =
        (options) => ok(const <String, dynamic>{}, status: 204);
    await openVoiceCard(tester, adapter);

    expect(find.byKey(const Key('edit.voice.saved.play')), findsOneWidget);
    await tapKey(tester, const Key('edit.voice.delete'));
    await tapKey(tester, const Key('edit.voice.delete.confirm'));

    expect(adapter.log.any((r) => r.method == 'DELETE' && r.path == '/users/me/voice'), isTrue);
    expect(find.byKey(const Key('edit.voice.saved.play')), findsNothing);
    expect(find.text('已删除'), findsOneWidget);
    await drainToast(tester);
  });

  testWidgets('本地录音点「取消」→ 回到空态,不发请求', (tester) async {
    final adapter = adapterWith();
    await openVoiceCard(tester, adapter);

    await recordOneSecond(tester);
    await tapKey(tester, const Key('edit.voice.cancel'));

    expect(find.byKey(const Key('edit.voice.upload')), findsNothing);
    expect(adapter.log.any((r) => r.path == '/users/me/voice'), isFalse);
  });
}
