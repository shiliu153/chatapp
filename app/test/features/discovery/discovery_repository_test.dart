import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/api_client.dart';
import 'package:chatapp_app/features/discovery/discovery_repository.dart';

import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

void main() {
  late ScriptedAdapter adapter;
  late DiscoveryRepository repository;

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    adapter = ScriptedAdapter({});
    final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
    repository = DiscoveryRepository(ApiClient(dio));
  });

  test('fetchCandidates 解析候选列表并带上 limit', () async {
    adapter.routes['GET /discovery/candidates'] = (options) => ok([
          candidateJson(userId: 9, nickname: '小红', tags: [tagJson(1, '运动')]),
          candidateJson(userId: 10, nickname: '小刚'),
        ]);

    final candidates = await repository.fetchCandidates();

    expect(candidates.map((item) => item.nickname), ['小红', '小刚']);
    expect(candidates.first.userId, 9);
    expect(candidates.first.tags.map((tag) => tag.name), ['运动']);
    expect(candidates.first.photos, hasLength(1));
    expect(adapter.log.last.queryParameters, {'limit': 10});
  });

  test('like → POST 动作是 like,matched 原样返回', () async {
    adapter.routes['POST /discovery/swipe'] = (options) => ok({'matched': true});

    final matched = await repository.swipe(targetUserId: 9, like: true);

    expect(matched, isTrue);
    expect(adapter.log.last.data, {'target_user_id': 9, 'action': 'like'});
  });

  test('pass → POST 动作是 pass', () async {
    adapter.routes['POST /discovery/swipe'] = (options) => ok({'matched': false});

    final matched = await repository.swipe(targetUserId: 10, like: false);

    expect(matched, isFalse);
    expect(adapter.log.last.data, {'target_user_id': 10, 'action': 'pass'});
  });
}
