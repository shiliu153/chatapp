import 'package:chatapp_app/core/api_exception.dart';
import 'package:chatapp_app/im/voice_transcode.dart';
import 'package:flutter_test/flutter_test.dart';

/// 造一条状态接口响应(`docs/api/im.md` §6.5 / `docs/api/users.md` §2.13 同形)。
VoiceTranscode _status(String status, {String? url, int? durationMs, int? size,
        String? code, String? message}) =>
    VoiceTranscode(
      id: 46,
      status: voiceTranscodeStatusOf(status),
      url: url,
      durationMs: durationMs,
      size: size,
      code: code,
      message: message,
    );

void main() {
  group('VoiceTranscode 解析(契约字段与 docs/api 逐字对齐)', () {
    test('ready:带 url / duration_ms / size,code 与 message 为 null', () {
      // 逐字取自 im.md §6.5 的响应示例
      final parsed = VoiceTranscode.parse({
        'id': 46,
        'status': 'ready',
        'url': 'https://test/media/chat/voices/2026/11/7-a1b2c3d4.m4a?e=1&s=ab',
        'duration_ms': 12500,
        'size': 48000,
        'code': null,
        'message': null,
      });

      expect(parsed, isNotNull);
      expect(parsed!.status, VoiceTranscodeStatus.ready);
      expect(parsed.isReady, isTrue);
      expect(parsed.url, contains('voices/2026/11/7-a1b2c3d4.m4a'));
      expect(parsed.durationMs, 12500);
      expect(parsed.size, 48000);
      expect(parsed.code, isNull);
    });

    test('pending:url / duration_ms / size 都是 null', () {
      final parsed = VoiceTranscode.parse({
        'id': 46,
        'status': 'pending',
        'url': null,
        'duration_ms': null,
        'size': null,
        'code': null,
        'message': null,
      });
      expect(parsed!.status, VoiceTranscodeStatus.pending);
      expect(parsed.isReady, isFalse);
      expect(parsed.url, isNull);
    });

    test('failed:失败原因走 code / message(如 41301 配额满)', () {
      final parsed = VoiceTranscode.parse({
        'id': 46,
        'status': 'failed',
        'url': null,
        'duration_ms': null,
        'size': null,
        'code': '41301',
        'message': '存储空间已满,请先删除部分照片',
      });
      expect(parsed!.isFailed, isTrue);
      expect(parsed.code, '41301');
      expect(parsed.message, '存储空间已满,请先删除部分照片');
    });

    test('没见过的 status 按 pending 处理(不误判成失败)', () {
      expect(voiceTranscodeStatusOf('transcoding'), VoiceTranscodeStatus.pending);
      expect(voiceTranscodeStatusOf(null), VoiceTranscodeStatus.pending);
    });

    test('非对象(空响应 / 老服务端)→ null', () {
      expect(VoiceTranscode.parse(null), isNull);
      expect(VoiceTranscode.parse('oops'), isNull);
    });
  });

  group('VoiceQueued 解析(202 响应)', () {
    test('读 retry_after', () {
      final queued = VoiceQueued.parse({'id': 46, 'status': 'pending', 'retry_after': 3});
      expect(queued!.id, 46);
      expect(queued.retryAfter, const Duration(seconds: 3));
    });

    test('缺 retry_after 时按 5 秒兜底', () {
      final queued = VoiceQueued.parse({'id': 46, 'status': 'pending'});
      expect(queued!.retryAfter, VoiceQueued.defaultRetryAfter);
      expect(queued.retryAfter, const Duration(seconds: 5));
    });

    test('没有 id(不是 202 的体)→ null', () {
      expect(VoiceQueued.parse({'status': 'pending'}), isNull);
      expect(VoiceQueued.parse(null), isNull);
    });
  });

  group('VoiceTranscodePoller', () {
    test('pending 一次后 ready:按 retry_after 查一次就收工', () async {
      final waits = <Duration>[];
      var calls = 0;
      final poller = VoiceTranscodePoller(
        fetch: () async {
          calls++;
          return calls == 1
              ? _status('pending')
              : _status('ready', url: 'http://test/v.m4a', durationMs: 3200, size: 900);
        },
        sleep: (delay) async => waits.add(delay),
      );

      final result = await poller.run(retryAfter: const Duration(seconds: 2));

      expect(result.outcome, VoicePollOutcome.settled);
      expect(result.status!.isReady, isTrue);
      expect(result.status!.url, 'http://test/v.m4a');
      expect(calls, 2);
      expect(waits, [const Duration(seconds: 2)], reason: '首轮间隔用 202 给的 retry_after');
    });

    test('failed 也是终态:不再继续轮询', () async {
      var calls = 0;
      final poller = VoiceTranscodePoller(fetch: () async {
        calls++;
        return _status('failed', code: '41301', message: '存储空间已满');
      }, sleep: (delay) async {});

      final result = await poller.run();
      expect(result.outcome, VoicePollOutcome.settled);
      expect(result.status!.isFailed, isTrue);
      expect(voicePollFailureText(result), '存储空间已满');
      expect(calls, 1);
    });

    test('查询本身失败(5xx)→ 退避重试,不一次性判死', () async {
      final waits = <Duration>[];
      var calls = 0;
      final poller = VoiceTranscodePoller(
        fetch: () async {
          calls++;
          if (calls == 1) throw ApiException('服务端错误', statusCode: 500);
          return _status('ready', url: 'http://test/v.m4a', durationMs: 1000);
        },
        sleep: (delay) async => waits.add(delay),
      );

      final result = await poller.run(retryAfter: const Duration(seconds: 2));

      expect(result.outcome, VoicePollOutcome.settled);
      expect(result.status!.isReady, isTrue);
      expect(calls, 2);
      // 失败一次后间隔翻倍(2s → 4s),而重试前的那一觉用的是退避后的间隔
      expect(waits, [const Duration(seconds: 4)]);
    });

    test('连续失败超过上限才把异常抛出去', () async {
      final poller = VoiceTranscodePoller(
        fetch: () async => throw ApiException('服务端错误', statusCode: 500),
        sleep: (delay) async {},
      );
      await expectLater(poller.run(), throwsA(isA<ApiException>()));
    });

    test('4xx(404)立刻抛:重试没有意义,别白烧轮询额度', () async {
      var calls = 0;
      final poller = VoiceTranscodePoller(
        fetch: () async {
          calls++;
          throw ApiException('语音不存在', statusCode: 404);
        },
        sleep: (delay) async {},
      );
      await expectLater(poller.run(), throwsA(isA<ApiException>()));
      expect(calls, 1);
    });

    test('查不到这条语音 → missing(资料语音没语音时不是错误)', () async {
      final poller = VoiceTranscodePoller(fetch: () async => null, sleep: (delay) async {});
      final result = await poller.run();
      expect(result.outcome, VoicePollOutcome.missing);
      expect(voicePollFailureText(result), voiceTranscodeMissingText);
    });

    test('取消信号一置位就收工(页面已离开)', () async {
      var cancelled = false;
      var calls = 0;
      final poller = VoiceTranscodePoller(
        fetch: () async {
          calls++;
          cancelled = true; // 第一轮查完用户就退出了
          return _status('pending');
        },
        cancelled: () => cancelled,
        sleep: (delay) async {},
      );
      final result = await poller.run();
      expect(result.outcome, VoicePollOutcome.aborted);
      expect(calls, 1);
    });

    test('次数用尽 → aborted(不死循环)', () async {
      final poller = VoiceTranscodePoller(
        fetch: () async => _status('pending'),
        sleep: (delay) async {},
        maxAttempts: 3,
      );
      final result = await poller.run();
      expect(result.outcome, VoicePollOutcome.aborted);
      expect(voicePollFailureText(result), voiceTranscodeTimeoutText);
    });
  });
}
