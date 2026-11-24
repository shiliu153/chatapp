import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/api_client.dart';
import 'package:chatapp_app/core/api_exception.dart';
import 'package:chatapp_app/im/self_voice_uploader.dart';
import 'package:chatapp_app/im/upload_idempotency.dart';
import 'package:chatapp_app/im/voice_transcode.dart';

import '../support/scripted_adapter.dart';

void main() {
  late ScriptedAdapter adapter;
  late ApiVoiceUploader uploader;
  late Directory tempDir;
  late String filePath;
  late List<Duration> sleeps;

  setUp(() async {
    adapter = ScriptedAdapter({});
    final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
    sleeps = <Duration>[];
    // 轮询等待换成 no-op:5 秒真等会把单测拖成分钟级;
    // 上传的退避等待记账,断言「同一次上传的重试复用同一个 key」。
    uploader = ApiVoiceUploader(
      ApiClient(dio),
      sleep: (delay) async {},
      retry: UploadRetry(sleep: (delay) async => sleeps.add(delay)),
    );
    tempDir = await Directory.systemTemp.createTemp('voice-uploader-test');
    filePath = '${tempDir.path}/voice.m4a';
    await File(filePath).writeAsBytes([0, 1, 2, 3]);
  });

  tearDown(() async {
    if (await tempDir.exists()) await tempDir.delete(recursive: true);
  });

  /// 请求头里带的幂等键,按发出顺序。
  List<String?> sentKeys() =>
      adapter.log.map((options) => options.headers[idempotencyKeyHeader] as String?).toList();

  test('201:同步转码完成,直接拿到可播放上传结果', () async {
    adapter.routes['POST /im/voices'] = (options) => ok({
          'id': 45,
          'url': 'http://test/media/chat/voices/2026/11/45-a1b2.m4a',
          'duration_ms': 12500,
          'size': 48000,
          'status': 'ready',
        }, status: 201);

    final sent = <(int, Duration)>[];
    final upload = await uploader.upload(filePath, 12500,
        hook: VoiceTranscodeHook(onQueued: (id, retry) => sent.add((id, retry))));

    expect(upload.id, 45);
    expect(upload.url, contains('45-a1b2.m4a'));
    expect(upload.durationMs, 12500);
    expect(upload.size, 48000);
    expect(upload.toPayload(), {
      'url': 'http://test/media/chat/voices/2026/11/45-a1b2.m4a',
      'duration_ms': 12500,
      'size': 48000,
    });
    // 同步路径没有排队,就不该回调「处理中」
    expect(sent, isEmpty);
    // multipart 的短视频字段照旧:string 形式的 duration_ms
    final form = adapter.log.last.data as FormData;
    expect(form.fields.single.key, 'duration_ms');
    expect(form.fields.single.value, '12500');
    expect(form.files.single.value.contentType?.mimeType, 'audio/mp4');
    expect(form.files.single.value.filename, 'voice.m4a',
        reason: '文件名只取 basename,不能带上临时目录');
    // 上传带一个合法的幂等键(口径见 docs/api/conventions.md「幂等键」)
    expect(sentKeys().single, matches(RegExp(r'^[A-Za-z0-9._:-]{1,128}$')));
  });

  // 回归(#499):文件名不能靠 `Platform.pathSeparator` 切 —— Windows 上是 `\`,
  // 而临时目录 / 部分插件给的路径用 `/` 拼,切不动就会把整条路径当文件名发给服务端。
  group('文件名只取 basename,两种分隔符都要取到', () {
    for (final separator in ['/', '\\']) {
      test('路径用 `$separator` 分隔', () async {
        adapter.routes['POST /im/voices'] = (options) => ok({
              'id': 48,
              'url': 'http://test/media/chat/voices/48-ff.m4a',
              'duration_ms': 3000,
              'size': 4,
              'status': 'ready',
            }, status: 201);
        final path = '${tempDir.path}${separator}separator-voice.m4a';
        // 路径原样物化成真实文件,断言便与平台无关:POSIX 上反斜杠是合法的文件名字符
        // (文件落在 tempDir 的父目录里,不必建子目录),Windows 上它就是分隔符。
        final file = File(path);
        addTearDown(() async {
          if (await file.exists()) await file.delete();
        });
        await file.writeAsBytes([0, 1, 2, 3]);

        await uploader.upload(path, 3000);

        final form = adapter.log.last.data as FormData;
        expect(form.files.single.value.filename, 'separator-voice.m4a',
            reason: '文件名里不该带任何目录,更不能变成整条本地路径');
      });
    }
  });

  test('202 → pending → ready:先回调排队,再轮询一次拿 url', () async {
    adapter.routes['POST /im/voices'] = (options) =>
        ok({'id': 46, 'status': 'pending', 'retry_after': 2}, status: 202);
    var polls = 0;
    adapter.routes['GET /im/voices/46'] = (options) {
      polls++;
      return polls == 1
          ? ok({
              'id': 46,
              'status': 'pending',
              'url': null,
              'duration_ms': null,
              'size': null,
              'code': null,
              'message': null,
            })
          : ok({
              'id': 46,
              'status': 'ready',
              'url': 'http://test/media/chat/voices/2026/11/46-c3d4.m4a',
              'duration_ms': 11800,
              'size': 47000,
              'code': null,
              'message': null,
            });
    };

    final queued = <(int, Duration)>[];
    final upload = await uploader.upload(filePath, 12500,
        hook: VoiceTranscodeHook(onQueued: (id, retry) => queued.add((id, retry))));

    expect(queued, [(46, const Duration(seconds: 2))], reason: '界面靠它打出「处理中」');
    expect(polls, 2);
    expect(upload.url, contains('46-c3d4.m4a'));
    // 时长 / 大小以服务端实测为准(不是客户端声明的 12500)
    expect(upload.durationMs, 11800);
    expect(upload.size, 47000);
    // 轮询是 GET,不该带幂等键;上传只打一次
    final posts = adapter.log.where((options) => options.method == 'POST');
    expect(posts, hasLength(1));
    expect(posts.single.headers[idempotencyKeyHeader], isNotNull);
    expect(
        adapter.log
            .where((options) => options.method == 'GET')
            .every((options) => !options.headers.containsKey(idempotencyKeyHeader)),
        isTrue);
  });

  test('202 → failed:抛 VoiceTranscodeException,带上业务码与中文提示', () async {
    adapter.routes['POST /im/voices'] = (options) =>
        ok({'id': 46, 'status': 'pending', 'retry_after': 5}, status: 202);
    adapter.routes['GET /im/voices/46'] = (options) => ok({
          'id': 46,
          'status': 'failed',
          'url': null,
          'duration_ms': null,
          'size': null,
          'code': '41301',
          'message': '存储空间已满,请先删除部分照片',
        });

    await expectLater(
      uploader.upload(filePath, 12500),
      throwsA(isA<VoiceTranscodeException>()
          .having((e) => e.code, 'code', '41301')
          .having((e) => e.message, 'message', '存储空间已满,请先删除部分照片')),
    );
  });

  test('轮询本身 5xx:退避重试后成功,不一次性判死', () async {
    adapter.routes['POST /im/voices'] = (options) =>
        ok({'id': 46, 'status': 'pending', 'retry_after': 1}, status: 202);
    var polls = 0;
    adapter.routes['GET /im/voices/46'] = (options) {
      polls++;
      if (polls == 1) return jsonError(502, '网关超时');
      return ok({
        'id': 46,
        'status': 'ready',
        'url': 'http://test/media/chat/voices/2026/11/46-e5f6.m4a',
        'duration_ms': 9000,
        'size': 30000,
        'code': null,
        'message': null,
      });
    };

    final upload = await uploader.upload(filePath, 9000);
    expect(polls, 2);
    expect(upload.url, contains('46-e5f6.m4a'));
  });

  test('轮询 404:立刻抛 ApiException(不重试到次数用尽)', () async {
    adapter.routes['POST /im/voices'] = (options) =>
        ok({'id': 46, 'status': 'pending', 'retry_after': 1}, status: 202);
    var polls = 0;
    adapter.routes['GET /im/voices/46'] = (options) {
      polls++;
      return jsonError(404, '语音不存在');
    };

    await expectLater(
      uploader.upload(filePath, 3000),
      throwsA(isA<ApiException>().having((e) => e.statusCode, 'statusCode', 404)),
    );
    expect(polls, 1);
  });

  test('201 但响应里没有 url:按转码失败处理,不让空地址流进 WS 帧', () async {
    adapter.routes['POST /im/voices'] = (options) =>
        ok({'id': 47, 'status': 'ready'}, status: 201);

    await expectLater(
      uploader.upload(filePath, 3000),
      throwsA(isA<VoiceTranscodeException>()),
    );
  });

  group('幂等键 + 上传退避', () {
    test('断网重试:所有重试复用同一个 key,第三次成功', () async {
      adapter.routes['POST /im/voices'] = (options) {
        if (adapter.log.length < 3) return offline(options);
        return ok({
          'id': 46,
          'status': 'ready',
          'url': 'http://test/media/chat/voices/46-aa.m4a',
          'duration_ms': 9000,
          'size': 30000,
        }, status: 201);
      };

      final upload = await uploader.upload(filePath, 9000);

      expect(upload.id, 46);
      final keys = sentKeys();
      expect(keys.length, 3);
      expect(keys.toSet().length, 1, reason: '同一次上传的重试必须复用同一个 key');
      expect(sleeps, [const Duration(milliseconds: 500), const Duration(seconds: 1)]);
    });

    test('409 + 40901 退避后同 key 重试成功', () async {
      var calls = 0;
      adapter.routes['POST /im/voices'] = (options) {
        calls++;
        return calls == 1
            ? jsonErrorWithHeaders(409,
                code: idempotencyConflictCode, message: '上一次上传还在处理,请勿重复提交')
            : ok({
                'id': 46,
                'status': 'ready',
                'url': 'http://test/media/chat/voices/46-bb.m4a',
                'duration_ms': 9000,
                'size': 30000,
              }, status: 201);
      };

      final upload = await uploader.upload(filePath, 9000);

      expect(upload.id, 46);
      expect(calls, 2);
      expect(sentKeys().toSet().length, 1);
      expect(sleeps.single.inMilliseconds, inInclusiveRange(1000, 2000));
    });

    test('5xx 退避重试,同 key;重试用尽则抛最后一次错误', () async {
      adapter.routes['POST /im/voices'] =
          (options) => jsonErrorWithHeaders(503, code: 50302, message: '转码服务忙,请稍后再试');

      await expectLater(
        uploader.upload(filePath, 12500),
        throwsA(isA<ApiException>()
            .having((error) => error.code, 'code', 50302)
            .having((error) => error.message, 'message', '转码服务忙,请稍后再试')),
      );
      final keys = sentKeys();
      expect(keys.length, 3, reason: '3 次尝试(含第一次)');
      expect(keys.toSet().length, 1);
      expect(sleeps, [const Duration(milliseconds: 500), const Duration(seconds: 1)]);
    });

    test('400 时长不符立刻冒泡:不重试', () async {
      adapter.routes['POST /im/voices'] = (options) => jsonError(400, '语音时长与声明不符');

      await expectLater(
        uploader.upload(filePath, 3000),
        throwsA(isA<ApiException>().having((error) => error.message, 'message', '语音时长与声明不符')),
      );
      expect(adapter.log.length, 1);
      expect(sleeps, isEmpty);
    });
  });
}
