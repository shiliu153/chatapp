import 'dart:async';
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

/// 可拨动的假时钟:录音时长 = 「松手时刻 − 按下时刻」,测试里把时间拨过去即可。
///
/// 为什么需要它:早先这里靠 `runAsync(Future.delayed(1.1s))` **真等墙钟**跨过
/// 「最短 1 秒」,CPU 被占满时窗口会抖,于是同一文件单跑也会随机挂**不同**的用例
/// (#533)。注入假钟后既不用等待,也不受机器负载影响。
class _FakeClock {
  DateTime _now = DateTime.utc(2026, 1, 1, 12);

  /// 供 `profileVoiceClockProvider` 使用(是 `DateTime Function()`)。
  DateTime call() => _now;

  /// 把时间往前拨。
  void advance(Duration delta) => _now = _now.add(delta);
}

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
  late _FakeClock clock;

  setUp(() {
    io = _FakeVoiceIo();
    clock = _FakeClock();
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
      profileVoiceClockProvider.overrideWithValue(clock.call),
    ]);
    await tester.pumpAndSettle();
    await tester.tap(navTab('我'));
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

  /// 滚到某个 key 可见。
  ///
  /// E-5.6c 之后编辑页多了底部主操作区(保存 52 + 上下 12),列表可视高度少了约 76,
  /// 语音卡后半段的按钮会落到 `ListView` 的构建范围之外 —— `ensureVisible` 要求元素
  /// 已经在树里,所以先用 `scrollUntilVisible` 把它滚进来(元素已在树里时照旧直接
  /// `ensureVisible`,不做多余滚动)。
  Future<void> scrollTo(WidgetTester tester, Key key) async {
    final target = find.byKey(key);
    if (target.evaluate().isEmpty) {
      await tester.scrollUntilVisible(
        target,
        200,
        scrollable: find
            .descendant(of: find.byType(ListView), matching: find.byType(Scrollable))
            .first,
      );
    }
    await tester.ensureVisible(target);
    await tester.pumpAndSettle();
  }

  /// 卡内按钮会随录音状态换位置(录音后卡片变高),点之前先滚到可见。
  Future<void> tapKey(WidgetTester tester, Key key) async {
    await scrollTo(tester, key);
    await tester.tap(find.byKey(key));
    await tester.pumpAndSettle();
  }

  /// 录一段「够长」的录音:按下 → 拨快 1.1 秒假钟 → 松手。
  ///
  /// 不再真等墙钟(#533):`pump(600ms)` 只负责跨过长按识别阈值,
  /// 「录了多久」由 [clock] 决定,所以这条 helper 与机器负载无关。
  Future<void> recordOneSecond(WidgetTester tester) async {
    final gesture = await tester
        .startGesture(tester.getCenter(find.byKey(const Key('edit.voice.mic'))));
    await tester.pump(const Duration(milliseconds: 600)); // 触发长按
    clock.advance(const Duration(milliseconds: 1100)); // 拨快假钟,不用等待
    await tester.pump(const Duration(milliseconds: 16));
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
    await scrollTo(tester, const Key('edit.voice.upload'));
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

  testWidgets('上传收到 202 → 卡片「处理中」,轮询 ready 后变成已保存', (tester) async {
    final gate = Completer<void>();
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
      'GET /users/tags': (options) => ok([tagJson(1, '运动')]),
      'POST /users/me/voice': (options) =>
          ok({'id': 7, 'status': 'pending', 'retry_after': 5}, status: 202),
      // 轮询挂住,好观察「处理中」那一帧
      'GET /users/me/voice': (options) async {
        await gate.future;
        return ok({
          'id': 7,
          'status': 'ready',
          'url': 'http://test/media/voices/7.m4a',
          'duration_ms': 2000,
          'size': 12000,
          'code': null,
          'message': null,
        });
      },
    });
    await openVoiceCard(tester, adapter);

    await recordOneSecond(tester);
    await scrollTo(tester, const Key('edit.voice.upload'));
    await tester.tap(find.byKey(const Key('edit.voice.upload')));
    // 转码中有常驻转圈:有限推进,不能 pumpAndSettle
    await pumpFrames(tester);

    expect(find.byKey(const Key('edit.voice.transcoding')), findsOneWidget);
    expect(find.text('转码中,请稍候…'), findsOneWidget);
    expect(find.byKey(const Key('edit.voice.saved.play')), findsNothing);

    gate.complete();
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('edit.voice.transcoding')), findsNothing);
    expect(find.byKey(const Key('edit.voice.saved.play')), findsOneWidget);
    expect(find.text('语音已保存'), findsOneWidget);
    // FakeVoiceRecorder.stop() 固定回 '/tmp/voice.m4a'(见 test/support/fake_voice.dart)
    expect(io.deleted, ['/tmp/voice.m4a'], reason: '转到 ready 才清本地临时文件');
    await drainToast(tester);
  });

  testWidgets('转码失败 → 卡片显示原因 + 重试;点重试重新上传后成功', (tester) async {
    var posts = 0;
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
      'GET /users/tags': (options) => ok([tagJson(1, '运动')]),
      'POST /users/me/voice': (options) {
        posts++;
        // 第一次排队转码,重试那次直接同步成功
        return posts == 1
            ? ok({'id': 7, 'status': 'pending', 'retry_after': 5}, status: 202)
            : ok(voiceJson(), status: 201);
      },
      'GET /users/me/voice': (options) => ok({
            'id': 7,
            'status': 'failed',
            'url': null,
            'duration_ms': null,
            'size': null,
            'code': '41301',
            'message': '存储空间已满,请先删除部分照片',
          }),
    });
    await openVoiceCard(tester, adapter);

    await recordOneSecond(tester);
    await tapKey(tester, const Key('edit.voice.upload'));

    expect(find.text('存储空间已满,请先删除部分照片'), findsOneWidget);
    expect(find.byKey(const Key('edit.voice.retry')), findsOneWidget);
    expect(find.byKey(const Key('edit.voice.saved.play')), findsNothing);

    await tapKey(tester, const Key('edit.voice.retry'));

    expect(posts, 2);
    expect(find.byKey(const Key('edit.voice.saved.play')), findsOneWidget);
    expect(find.byKey(const Key('edit.voice.retry')), findsNothing);
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
