import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/api_client.dart';
import 'package:chatapp_app/features/profile/profile_repository.dart';

import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

void main() {
  late ScriptedAdapter adapter;
  late ProfileRepository repository;

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    adapter = ScriptedAdapter({});
    final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
    repository = ProfileRepository(ApiClient(dio));
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
    expect(adapter.log.last.data, isA<FormData>());
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
}
