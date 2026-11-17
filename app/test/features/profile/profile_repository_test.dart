import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/api_client.dart';
import 'package:chatapp_app/core/api_exception.dart';
import 'package:chatapp_app/features/profile/profile_repository.dart';
import 'package:chatapp_app/im/upload_idempotency.dart';
import 'package:chatapp_app/im/voice_transcode.dart';

import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

void main() {
  late ScriptedAdapter adapter;
  late Dio dio;
  late ProfileRepository repository;

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    adapter = ScriptedAdapter({});
    dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
    // 轮询等待换成 no-op:真等 5 秒会把单测拖成分钟级
    repository = ProfileRepository(ApiClient(dio), sleep: (delay) async {});
  });

  test('fetchMe 解析资料', () async {
    adapter.routes['GET /users/me'] =
        (options) => ok(profileJson(nickname: '小红', missing: ['photos']));
    final profile = await repository.fetchMe();
    expect(profile.nickname, '小红');
    expect(profile.isComplete, isFalse);
    expect(profile.missingFields, ['photos']);
  });

  test('update 发 PATCH 并回新资料', () async {
    adapter.routes['PATCH /users/me'] = (options) => ok(profileJson(nickname: '新昵称'));
    final profile = await repository.update({'nickname': '新昵称'});
    expect(profile.nickname, '新昵称');
    expect(adapter.log.last.method, 'PATCH');
    expect(adapter.log.last.data, {'nickname': '新昵称'});
  });

  test('fetchMe 解析 voice(没录过是 null)', () async {
    adapter.routes['GET /users/me'] = (options) => ok(profileJson());
    expect((await repository.fetchMe()).voice, isNull);

    adapter.routes['GET /users/me'] = (options) => ok(profileJson(voice: voiceJson()));
    final profile = await repository.fetchMe();
    expect(profile.voice?.url, 'http://test/media/voices/intro.m4a');
    expect(profile.voice?.durationMs, 18000);
    expect(profile.voice?.durationLabel, '0:18');
  });

  test('uploadVoice 以 multipart 打 POST /users/me/voice 并解析响应', () async {
    adapter.routes['POST /users/me/voice'] = (options) => ok(voiceJson(), status: 201);
    final voice = await repository.uploadVoice(Uint8List.fromList([1, 2, 3]), 'intro.m4a');

    expect(voice.url, 'http://test/media/voices/intro.m4a');
    expect(voice.durationMs, 18000);
    expect(adapter.log.last.method, 'POST');
    expect(adapter.log.last.path, '/users/me/voice');

    // 回归:P0(2026-11-09 真机实测)——`.m4a` 不在 mime 包里,不显式给 contentType
    // 会退化成 application/octet-stream,被服务端白名单拒成 400。ScriptedAdapter 看不到
    // multipart 头,只能在这里直接断言 part 的 contentType。
    final form = adapter.log.last.data as FormData;
    final part = form.files.first;
    expect(part.key, 'file');
    expect(part.value.filename, 'intro.m4a');
    expect(part.value.contentType?.mimeType, 'audio/mp4');
  });

  test('deleteVoice 打 DELETE /users/me/voice', () async {
    adapter.routes['DELETE /users/me/voice'] =
        (options) => ok(const <String, dynamic>{}, status: 204);
    await repository.deleteVoice();
    expect(adapter.log.last.method, 'DELETE');
    expect(adapter.log.last.path, '/users/me/voice');
  });

  test('fetchTags 解析标签池', () async {
    adapter.routes['GET /users/tags'] = (options) => ok([tagJson(1, '运动'), tagJson(2, '音乐')]);
    final tags = await repository.fetchTags();
    expect(tags.map((tag) => tag.name), ['运动', '音乐']);
  });

  test('uploadVoice 遇到 202:先回调「排队」,再轮询 GET /users/me/voice 直到 ready', () async {
    adapter.routes['POST /users/me/voice'] =
        (options) => ok({'id': 7, 'status': 'pending', 'retry_after': 2}, status: 202);
    var polls = 0;
    adapter.routes['GET /users/me/voice'] = (options) {
      polls++;
      return polls == 1
          ? ok({
              'id': 7,
              'status': 'pending',
              'url': null,
              'duration_ms': null,
              'size': null,
              'code': null,
              'message': null,
            })
          : ok({
              'id': 7,
              'status': 'ready',
              'url': 'http://test/media/voices/2026/11/7-a1b2.m4a?e=1&s=ab',
              'duration_ms': 18000,
              'size': 72000,
              'code': null,
              'message': null,
            });
    };

    final queued = <(int, Duration)>[];
    final voice = await repository.uploadVoice(
      Uint8List.fromList([1, 2, 3]),
      'intro.m4a',
      hook: VoiceTranscodeHook(onQueued: (id, retry) => queued.add((id, retry))),
    );

    expect(queued, [(7, const Duration(seconds: 2))], reason: '界面靠它打出「处理中」');
    expect(polls, 2);
    expect(voice.url, contains('7-a1b2.m4a'));
    expect(voice.durationMs, 18000);
    expect(voice.status, 'ready');
    expect(voice.id, 7);
    // 只打一次上传:轮询走的是 GET,不能重发 multipart
    expect(adapter.log.where((r) => r.method == 'POST'), hasLength(1));
  });

  test('uploadVoice 转码失败:抛 VoiceTranscodeException(带业务码)', () async {
    adapter.routes['POST /users/me/voice'] =
        (options) => ok({'id': 7, 'status': 'pending', 'retry_after': 1}, status: 202);
    adapter.routes['GET /users/me/voice'] = (options) => ok({
          'id': 7,
          'status': 'failed',
          'url': null,
          'duration_ms': null,
          'size': null,
          'code': '41301',
          'message': '存储空间已满,请先删除部分照片',
        });

    await expectLater(
      repository.uploadVoice(Uint8List.fromList([1]), 'intro.m4a'),
      throwsA(isA<VoiceTranscodeException>()
          .having((e) => e.code, 'code', '41301')
          .having((e) => e.message, 'message', '存储空间已满,请先删除部分照片')),
    );
  });

  test('fetchVoiceStatus:404 表示还没录过语音,不是错误', () async {
    adapter.routes['GET /users/me/voice'] = (options) => jsonError(404, '语音不存在');
    expect(await repository.fetchVoiceStatus(), isNull);
  });

  test('fetchVoiceStatus:解析三态与 url / 失败原因', () async {
    adapter.routes['GET /users/me/voice'] = (options) => ok({
          'id': 7,
          'status': 'ready',
          'url': 'http://test/media/voices/7.m4a',
          'duration_ms': 18000,
          'size': 72000,
          'code': null,
          'message': null,
        });
    final ready = await repository.fetchVoiceStatus();
    expect(ready!.isReady, isTrue);
    expect(ready.url, 'http://test/media/voices/7.m4a');

    adapter.routes['GET /users/me/voice'] = (options) => ok({
          'id': 7,
          'status': 'failed',
          'url': null,
          'duration_ms': null,
          'size': null,
          'code': '41301',
          'message': '存储空间已满',
        });
    final failed = await repository.fetchVoiceStatus();
    expect(failed!.isFailed, isTrue);
    expect(failed.code, '41301');
  });

  group('uploadVoice 幂等键', () {
    // 单测里不真等:退避等待全部记账(轮询等待仍是 no-op)
    late List<Duration> sleeps;
    late ProfileRepository retrying;

    setUp(() {
      sleeps = <Duration>[];
      retrying = ProfileRepository(ApiClient(dio), sleep: (delay) async {},
          retry: UploadRetry(sleep: (delay) async => sleeps.add(delay)));
    });

    List<String?> sentKeys() => adapter.log
        .map((options) => options.headers[idempotencyKeyHeader] as String?)
        .toList();

    test('带上合法 key;同一次录音(同一来源)复用同一个 key,重录才换', () async {
      adapter.routes['POST /users/me/voice'] = (options) => ok(voiceJson(), status: 201);
      final bytes = Uint8List.fromList([1, 2, 3]);
      final first = await repository.uploadVoice(bytes, 'intro.m4a', keySource: '/tmp/v1.m4a');
      await repository.uploadVoice(bytes, 'intro.m4a', keySource: '/tmp/v1.m4a');
      await repository.uploadVoice(bytes, 'intro.m4a', keySource: '/tmp/v2.m4a');

      expect(first.url, 'http://test/media/voices/intro.m4a');
      final keys = sentKeys();
      expect(keys.first, matches(RegExp(r'^[A-Za-z0-9._:-]{1,128}$')));
      expect(keys[1], keys[0], reason: '上传失败后再点一次「上传」仍是同一次上传');
      expect(keys[2], isNot(keys[0]), reason: '重录换了文件 → 换新 key');
    });

    test('没有来源时每次调用一个新 key', () async {
      adapter.routes['POST /users/me/voice'] = (options) => ok(voiceJson(), status: 201);
      final bytes = Uint8List.fromList([1, 2, 3]);
      await repository.uploadVoice(bytes, 'intro.m4a');
      await repository.uploadVoice(bytes, 'intro.m4a');
      final keys = sentKeys();
      expect(keys[1], isNot(keys[0]));
    });

    test('202 的轮询请求不带幂等键(只读接口)', () async {
      adapter.routes['POST /users/me/voice'] =
          (options) => ok({'id': 7, 'status': 'pending', 'retry_after': 1}, status: 202);
      adapter.routes['GET /users/me/voice'] = (options) => ok({
            'id': 7,
            'status': 'ready',
            'url': 'http://test/media/voices/7.m4a',
            'duration_ms': 18000,
            'size': 72000,
            'code': null,
            'message': null,
          });

      await repository.uploadVoice(Uint8List.fromList([1]), 'intro.m4a',
          keySource: '/tmp/v1.m4a');

      final polls = adapter.log.where((options) => options.method == 'GET');
      expect(polls, hasLength(1));
      expect(polls.single.headers.containsKey(idempotencyKeyHeader), isFalse);
      expect(adapter.log.first.headers[idempotencyKeyHeader], isNotNull);
    });

    test('409 + 40901 退避后同 key 重试成功', () async {
      var calls = 0;
      adapter.routes['POST /users/me/voice'] = (options) {
        calls++;
        return calls == 1
            ? jsonErrorWithHeaders(409,
                code: idempotencyConflictCode, message: '上一次上传还在处理,请勿重复提交')
            : ok(voiceJson(), status: 201);
      };

      final voice = await retrying.uploadVoice(Uint8List.fromList([1, 2, 3]), 'intro.m4a',
          keySource: '/tmp/v1.m4a');

      expect(voice.durationMs, 18000);
      expect(calls, 2);
      expect(sentKeys().toSet().length, 1);
      expect(sleeps.single.inMilliseconds, inInclusiveRange(1000, 2000));
    });

    test('400 时长超限立刻冒泡,不重试', () async {
      adapter.routes['POST /users/me/voice'] =
          (options) => jsonError(400, '语音时长与声明不符');
      await expectLater(
        retrying.uploadVoice(Uint8List.fromList([1, 2, 3]), 'intro.m4a', keySource: '/tmp/v1.m4a'),
        throwsA(isA<ApiException>().having((error) => error.message, 'message', '语音时长与声明不符')),
      );
      expect(adapter.log.length, 1);
      expect(sleeps, isEmpty);
    });
  });
}
