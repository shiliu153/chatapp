import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/api_client.dart';
import 'package:chatapp_app/core/api_exception.dart';
import 'package:chatapp_app/im/self_voice_uploader.dart';
import 'package:chatapp_app/im/voice_transcode.dart';

import '../support/scripted_adapter.dart';

void main() {
  late ScriptedAdapter adapter;
  late ApiVoiceUploader uploader;
  late Directory tempDir;
  late String filePath;

  setUp(() async {
    adapter = ScriptedAdapter({});
    final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
    // 轮询等待换成 no-op:5 秒真等会把单测拖成分钟级
    uploader = ApiVoiceUploader(ApiClient(dio), sleep: (delay) async {});
    tempDir = await Directory.systemTemp.createTemp('voice-uploader-test');
    filePath = '${tempDir.path}/voice.m4a';
    await File(filePath).writeAsBytes([0, 1, 2, 3]);
  });

  tearDown(() async {
    if (await tempDir.exists()) await tempDir.delete(recursive: true);
  });

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
}
