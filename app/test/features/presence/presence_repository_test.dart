import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/api_client.dart';
import 'package:chatapp_app/features/presence/models.dart';
import 'package:chatapp_app/features/presence/presence_repository.dart';

import '../../support/scripted_adapter.dart';

void main() {
  late ScriptedAdapter adapter;
  late PresenceRepository repository;

  setUp(() {
    adapter = ScriptedAdapter({});
    final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
    repository = PresenceRepository(ApiClient(dio));
  });

  test('fetchPresence 解析 results 并按逗号拼 user_ids', () async {
    adapter.routes['GET /presence'] = (options) => ok({
          'results': [
            {'user_id': 9, 'online': true, 'last_active_at': '2026-09-13T14:30:00+08:00'},
            {'user_id': 10, 'online': false, 'last_active_at': '2026-09-13T11:02:10+08:00'},
            {'user_id': 11, 'online': false, 'last_active_at': null},
          ],
        });

    final map = await repository.fetchPresence([9, 10, 11]);

    expect(map.keys, containsAll([9, 10, 11]));
    expect(map[9]!.online, isTrue);
    expect(map[10]!.online, isFalse);
    expect(map[10]!.lastActiveAt, DateTime.parse('2026-09-13T11:02:10+08:00'));
    expect(map[11]!.lastActiveAt, isNull);
    expect(adapter.log.last.queryParameters, {'user_ids': '9,10,11'});
  });

  test('空列表不发请求', () async {
    expect(await repository.fetchPresence(const []), isEmpty);
    expect(adapter.log, isEmpty);
  });

  test('presenceLabel:在线 / 离线带时间 / 未知三种形态', () {
    final now = DateTime(2026, 9, 13, 14, 0);
    expect(presenceLabel(const Presence(online: true), now: now), '● 在线');
    expect(
        presenceLabel(
            Presence(online: false, lastActiveAt: now.subtract(const Duration(minutes: 5))),
            now: now),
        '5 分钟前在线');
    expect(presenceLabel(const Presence(online: false), now: now), isNull);
    expect(presenceLabel(null), isNull);
  });
}
