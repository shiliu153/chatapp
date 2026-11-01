import 'package:chatapp_app/features/chat/voice_record_controller.dart';
import 'package:chatapp_app/im/voice_recorder.dart';
import 'package:fake_async/fake_async.dart';
import 'package:flutter_test/flutter_test.dart';

/// 假录音器:记录调用次数,stop 返回固定路径。
class _FakeRecorder implements VoiceRecorder {
  bool permission = true;
  bool started = false;
  int cancelCalls = 0;
  int stopCalls = 0;

  @override
  Future<bool> hasPermission() async => permission;

  @override
  Future<void> start(String path) async => started = true;

  @override
  Future<String?> stop() async {
    stopCalls++;
    return '/tmp/voice-1.m4a';
  }

  @override
  Future<void> cancel() async => cancelCalls++;
}

void main() {
  late _FakeRecorder recorder;
  late List<String> notices;
  late List<({String path, int durationMs})> sent;
  late DateTime clock;

  DateTime now() => clock;

  VoiceRecordController build() => VoiceRecordController(
        recorder: recorder,
        tempPath: () async => '/tmp/voice-1.m4a',
        onNotice: notices.add,
        onSend: (path, durationMs) async => sent.add((path: path, durationMs: durationMs)),
        now: now,
      );

  setUp(() {
    recorder = _FakeRecorder();
    notices = [];
    sent = [];
    clock = DateTime(2026, 1, 1, 12);
  });

  test('start 后进入 recording', () async {
    final c = build();
    await c.start();
    expect(c.phase, VoicePhase.recording);
    c.dispose();
  });

  test('无权限提示且不进入录音', () async {
    recorder.permission = false;
    final c = build();
    await c.start();
    expect(c.phase, VoicePhase.idle);
    expect(notices, contains(voiceTextPermissionDenied));
    c.dispose();
  });

  test('不足 1 秒不发送并提示太短', () async {
    final c = build();
    await c.start();
    clock = clock.add(const Duration(milliseconds: 500));
    await c.stopAndSend();
    expect(sent, isEmpty);
    expect(notices, contains(voiceTextTooShort));
    expect(c.phase, VoicePhase.idle);
    c.dispose();
  });

  test('满 1 秒发送一次', () async {
    final c = build();
    await c.start();
    clock = clock.add(const Duration(seconds: 2));
    await c.stopAndSend();
    expect(sent, hasLength(1));
    expect(sent.single.path, '/tmp/voice-1.m4a');
    c.dispose();
  });

  test('60 秒自动发送', () {
    fakeAsync((async) {
      final c = build();
      c.start();
      async.flushMicrotasks();
      clock = clock.add(const Duration(seconds: 60));
      async.elapse(const Duration(seconds: 60));
      async.flushMicrotasks();
      expect(sent, hasLength(1));
      c.dispose();
    });
  });

  test('取消不发任何消息', () async {
    final c = build();
    await c.start();
    clock = clock.add(const Duration(seconds: 2));
    await c.cancel();
    expect(sent, isEmpty);
    expect(recorder.cancelCalls, greaterThanOrEqualTo(1));
    expect(c.phase, VoicePhase.idle);
    c.dispose();
  });

  test('dispose 时录音中会取消录音,不发送', () async {
    final c = build();
    await c.start();
    clock = clock.add(const Duration(seconds: 2));
    c.dispose();
    expect(recorder.cancelCalls, greaterThanOrEqualTo(1));
    expect(sent, isEmpty);
  });
}
