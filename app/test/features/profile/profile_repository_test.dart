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

  test('fetchTags 解析标签池', () async {
    adapter.routes['GET /users/tags'] = (options) => ok([tagJson(1, '运动'), tagJson(2, '音乐')]);
    final tags = await repository.fetchTags();
    expect(tags.map((tag) => tag.name), ['运动', '音乐']);
  });
}
