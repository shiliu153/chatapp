import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/api_client.dart';
import 'package:chatapp_app/features/moderation/moderation_repository.dart';

import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

void main() {
  late ScriptedAdapter adapter;
  late ModerationRepository repository;

  setUp(() {
    adapter = ScriptedAdapter({});
    final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
    repository = ModerationRepository(ApiClient(dio));
  });

  test('fetchUserProfile 解析公开资料', () async {
    adapter.routes['GET /users/9'] = (options) => ok(publicProfileJson());
    final profile = await repository.fetchUserProfile(9);
    expect(profile.nickname, '小红');
    expect(profile.age, 25);
    expect(profile.photos, hasLength(1));
  });

  test('report 发 POST /reports 带三个字段', () async {
    adapter.routes['POST /reports'] =
        (options) => ok({'id': 1, 'type': 'harassment', 'status': 'pending'}, status: 201);
    await repository.report(targetUserId: 9, type: 'harassment', detail: '骚扰');
    expect(adapter.log.last.path, '/reports');
    expect(adapter.log.last.data, {'target_user_id': 9, 'type': 'harassment', 'detail': '骚扰'});
  });

  test('block / unblock 发对应请求', () async {
    adapter.routes['POST /blocks'] = (options) => ok({'user_id': 9}, status: 201);
    adapter.routes['DELETE /blocks/9'] = (options) => ok({}, status: 204);
    await repository.block(9);
    expect(adapter.log.last.data, {'target_user_id': 9});
    await repository.unblock(9);
    expect(adapter.log.last.method, 'DELETE');
    expect(adapter.log.last.path, '/blocks/9');
  });

  test('fetchBlockedUsers 解析列表', () async {
    adapter.routes['GET /blocks'] = (options) => ok(pageJson([blockedUserJson()]));
    final users = await repository.fetchBlockedUsers();
    expect(users.single.nickname, '小红');
    expect(users.single.userId, 9);
  });
}
