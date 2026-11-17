import 'dart:async';

import 'package:chatapp_app/core/api_exception.dart';
import 'package:chatapp_app/features/chat/voice_record_controller.dart';
import 'package:chatapp_app/features/profile/models.dart';
import 'package:chatapp_app/features/profile/profile_voice_controller.dart';
import 'package:chatapp_app/im/voice_recorder.dart';
import 'package:chatapp_app/im/voice_transcode.dart';
import 'package:fake_async/fake_async.dart';
import 'package:flutter_test/flutter_test.dart';

/// 假录音器:不碰麦克风,stop 返回固定路径。
class _FakeRecorder implements VoiceRecorder {
  bool permission = true;
  bool started = false;
  int cancelCalls = 0;

  @override
  Future<bool> hasPermission() async => permission;

  @override
  Future<void> start(String path) async => started = true;

  @override
  Future<String?> stop() async => started ? '/tmp/profile-voice-1.m4a' : null;

  @override
  Future<void> cancel() async => cancelCalls++;
}

void main() {
  late _FakeRecorder recorder;
  late List<String> notices;
  late List<String> uploaded;
  late DateTime clock;
  late bool failUpload;
  late bool queued;
  late String? transcodeFailure;
  Completer<void>? gate;
  late int deleteCalls;
  late List<String> deletedFiles;

  ProfileVoiceController build({VoiceIntro? initial}) => ProfileVoiceController(
        recorder: recorder,
        tempPath: () async => '/tmp/profile-voice-1.m4a',
        onUpload: (path, hook) async {
          if (failUpload) throw ApiException('语音不能超过 30 秒', statusCode: 400);
          uploaded.add(path);
          // 模拟 202(M-3):先回调「排队转码」,再按 [queueOutcome] 决定落点。
          if (queued) hook.onQueued?.call(7, const Duration(seconds: 5));
          // 观察「转码中」用:置上则挂在这里,测试推进后再放行
          final pendingGate = gate;
          if (pendingGate != null) await pendingGate.future;
          if (transcodeFailure != null) {
            throw VoiceTranscodeException(transcodeFailure!);
          }
          return const VoiceIntro(
              url: 'http://test/media/voices/intro.m4a', durationMs: 12000);
        },
        onDelete: () async => deleteCalls++,
        deleteFile: (path) async => deletedFiles.add(path),
        onNotice: notices.add,
        initialVoice: initial,
        now: () => clock,
      );

  setUp(() {
    recorder = _FakeRecorder();
    notices = [];
    uploaded = [];
    failUpload = false;
    queued = false;
    transcodeFailure = null;
    gate = null;
    deleteCalls = 0;
    deletedFiles = [];
    clock = DateTime(2026, 11, 9, 12);
  });

  test('初始状态:没语音是 idle,有语音是 saved', () {
    final empty = build();
    expect(empty.phase, ProfileVoicePhase.idle);
    expect(empty.voice, isNull);
    empty.dispose();

    final saved = build(
        initial: const VoiceIntro(url: 'http://test/a.m4a', durationMs: 5000));
    expect(saved.phase, ProfileVoicePhase.saved);
    expect(saved.voice?.durationMs, 5000);
    saved.dispose();
  });

  test('上限是 30 秒(聊天是 60 秒,参数不同不复制控制器)', () {
    final c = build();
    expect(c.maxSeconds, 30);
    expect(voiceChatMaxDurationMs, 60000);
    c.dispose();
  });

  test('录音 → 松手进入「已录」,此时还没上传', () async {
    final c = build();
    await c.start();
    expect(c.phase, ProfileVoicePhase.recording);
    clock = clock.add(const Duration(seconds: 2));
    await c.stop();
    expect(c.phase, ProfileVoicePhase.recorded);
    expect(c.localPath, '/tmp/profile-voice-1.m4a');
    expect(uploaded, isEmpty);
    c.dispose();
  });

  test('上传成功 → saved,用响应里的 url 与时长', () async {
    final c = build();
    await c.start();
    clock = clock.add(const Duration(seconds: 2));
    await c.stop();
    await c.upload();
    expect(uploaded, ['/tmp/profile-voice-1.m4a']);
    expect(c.phase, ProfileVoicePhase.saved);
    expect(c.voice?.url, 'http://test/media/voices/intro.m4a');
    expect(c.voice?.durationMs, 12000);
    expect(deletedFiles, ['/tmp/profile-voice-1.m4a'], reason: '上传成功后清掉临时文件');
    c.dispose();
  });

  test('上传失败(400 时长超限)→ 回「已录」并把异常抛给页面', () async {
    failUpload = true;
    final c = build();
    await c.start();
    clock = clock.add(const Duration(seconds: 2));
    await c.stop();
    await expectLater(c.upload(), throwsA(isA<ApiException>()));
    expect(c.phase, ProfileVoicePhase.recorded);
    expect(c.localPath, isNotNull, reason: '本地录音要留着,用户能原地重试');
    expect(c.voice, isNull);
    c.dispose();
  });

  test('满 30 秒自动停,进入「已录」', () {
    fakeAsync((async) {
      final c = build();
      c.start();
      async.flushMicrotasks();
      expect(c.phase, ProfileVoicePhase.recording);
      clock = clock.add(const Duration(seconds: 30));
      async.elapse(const Duration(seconds: 30));
      async.flushMicrotasks();
      expect(c.phase, ProfileVoicePhase.recorded);
      expect(c.localPath, isNotNull);
      c.dispose();
    });
  });

  test('删除已保存语音 → 调一次 DELETE 并回到 idle', () async {
    final c = build(
        initial: const VoiceIntro(url: 'http://test/a.m4a', durationMs: 5000));
    await c.remove();
    expect(deleteCalls, 1);
    expect(c.voice, isNull);
    expect(c.phase, ProfileVoicePhase.idle);
    c.dispose();
  });

  test('只有本地录音时删除 → 不调 DELETE,直接回 idle', () async {
    final c = build();
    await c.start();
    clock = clock.add(const Duration(seconds: 2));
    await c.stop();
    await c.remove();
    expect(deleteCalls, 0);
    expect(c.phase, ProfileVoicePhase.idle);
    expect(c.localPath, isNull);
    c.dispose();
  });

  test('「取消」只丢本地录音,已保存的语音还在', () async {
    final c = build(
        initial: const VoiceIntro(url: 'http://test/a.m4a', durationMs: 5000));
    await c.start();
    clock = clock.add(const Duration(seconds: 2));
    await c.stop();
    expect(c.phase, ProfileVoicePhase.recorded);
    await c.discardLocal();
    expect(c.phase, ProfileVoicePhase.saved);
    expect(c.voice?.url, 'http://test/a.m4a');
    expect(deleteCalls, 0);
    c.dispose();
  });

  test('不足 1 秒:提示太短,不进入「已录」', () async {
    final c = build();
    await c.start();
    clock = clock.add(const Duration(milliseconds: 400));
    await c.stop();
    expect(c.phase, ProfileVoicePhase.idle);
    expect(notices, contains(voiceTextTooShort));
    c.dispose();
  });

  test('无麦克风权限:提示且回到 idle', () async {
    recorder.permission = false;
    final c = build();
    await c.start();
    expect(c.phase, ProfileVoicePhase.idle);
    expect(notices, contains(voiceTextPermissionDenied));
    c.dispose();
  });

  test('202(转码排队):先「转码中」,轮询 ready 后落 saved', () async {
    queued = true;
    gate = Completer<void>();
    final c = build();
    await c.start();
    clock = clock.add(const Duration(seconds: 2));
    await c.stop();

    final uploading = c.upload();
    await pumpEventQueue();
    expect(c.phase, ProfileVoicePhase.transcoding);
    expect(c.busy, isTrue, reason: '转码中按钮要禁用');

    gate!.complete();
    await uploading;
    expect(c.phase, ProfileVoicePhase.saved);
    expect(c.voice?.url, 'http://test/media/voices/intro.m4a');
    expect(deletedFiles, ['/tmp/profile-voice-1.m4a'], reason: '落 saved 才清临时文件');
    c.dispose();
  });

  test('转码中不能重录 / 删除(状态机不允许半路插队)', () async {
    queued = true;
    gate = Completer<void>();
    final c = build();
    await c.start();
    clock = clock.add(const Duration(seconds: 2));
    await c.stop();

    final uploading = c.upload();
    await pumpEventQueue();
    await c.start();
    expect(c.phase, ProfileVoicePhase.transcoding);
    await c.remove();
    expect(deleteCalls, 0);

    gate!.complete();
    await uploading;
    c.dispose();
  });

  test('转码失败 → failed + 中文原因,重试重新上传后 saved', () async {
    queued = true;
    transcodeFailure = '存储空间已满,请先删除部分照片';
    final c = build();
    await c.start();
    clock = clock.add(const Duration(seconds: 2));
    await c.stop();

    await c.upload();
    expect(c.phase, ProfileVoicePhase.failed);
    expect(c.failureMessage, '存储空间已满,请先删除部分照片');
    expect(c.localPath, '/tmp/profile-voice-1.m4a', reason: '本地录音留着才能重试');
    expect(deletedFiles, isEmpty);

    // 用户删掉几张照片后点「重试」:重传同一段,这次转码成功
    transcodeFailure = null;
    queued = false;
    await c.retry();
    expect(c.phase, ProfileVoicePhase.saved);
    expect(uploaded, ['/tmp/profile-voice-1.m4a', '/tmp/profile-voice-1.m4a']);
    expect(c.failureMessage, isNull);
    c.dispose();
  });

  test('录音中 dispose 会取消录音(麦克风不留在采集态)', () async {
    final c = build();
    await c.start();
    clock = clock.add(const Duration(seconds: 2));
    c.dispose();
    expect(recorder.cancelCalls, greaterThanOrEqualTo(1));
    expect(uploaded, isEmpty);
  });
}
