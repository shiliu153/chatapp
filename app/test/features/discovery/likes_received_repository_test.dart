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

  test('fetchLikesReceived 解析分页、liked_at 并带上 limit/offset', () async {
    adapter.routes['GET /discovery/likes'] = (options) => ok(pageJson([
          likeReceivedJson(userId: 9, nickname: '小红'),
          likeReceivedJson(userId: 10, nickname: '小刚'),
        ]));

    final page = await repository.fetchLikesReceived(limit: 20, offset: 0);

    expect(page.count, 2);
    expect(page.items.map((item) => item.candidate.nickname), ['小红', '小刚']);
    expect(page.items.first.likedAt.year, 2026);
    expect(adapter.log.last.queryParameters, {'limit': 20, 'offset': 0});
  });

  test('fetchLikesReceivedCount 解析 count', () async {
    adapter.routes['GET /discovery/likes/count'] = (options) => ok({'count': 7});

    expect(await repository.fetchLikesReceivedCount(), 7);
  });
}
