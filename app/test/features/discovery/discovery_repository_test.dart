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

    final result = await repository.swipe(targetUserId: 9, like: true);

    expect(result.matched, isTrue);
    expect(result.sharedTags, isEmpty);
    expect(adapter.log.last.data, {'target_user_id': 9, 'action': 'like'});
  });

  test('pass → POST 动作是 pass', () async {
    adapter.routes['POST /discovery/swipe'] = (options) => ok({'matched': false});

    final result = await repository.swipe(targetUserId: 10, like: false);

    expect(result.matched, isFalse);
    expect(result.sharedTags, isEmpty);
    expect(adapter.log.last.data, {'target_user_id': 10, 'action': 'pass'});
  });

  test('undoSwipe → 无 body 的 POST,返回被撤销的目标 userId', () async {
    adapter.routes['POST /discovery/swipe/undo'] =
        (options) => ok({'undone': true, 'target_user_id': 30});

    final targetUserId = await repository.undoSwipe();

    expect(targetUserId, 30);
    expect(adapter.log.last.method, 'POST');
    expect(adapter.log.last.path, '/discovery/swipe/undo');
    expect(adapter.log.last.data, isNull);
  });

  test('fetchQuota 解析额度快照;like_limit=0 时 likes_remaining 为 null', () async {
    adapter.routes['GET /discovery/quota'] =
        (options) => ok({'like_limit': 10, 'likes_used': 3, 'likes_remaining': 7});

    final quota = await repository.fetchQuota();

    expect(quota.likeLimit, 10);
    expect(quota.likesUsed, 3);
    expect(quota.likesRemaining, 7);
    expect(quota.limited, isTrue);

    adapter.routes['GET /discovery/quota'] =
        (options) => ok({'like_limit': 0, 'likes_used': 0, 'likes_remaining': null});

    final unlimited = await repository.fetchQuota();

    expect(unlimited.limited, isFalse);
    expect(unlimited.likesRemaining, isNull);
  });

  test('配对成功 → 解析响应里的共同标签(破冰文案用)', () async {
    adapter.routes['POST /discovery/swipe'] = (options) => ok({
          'matched': true,
          'shared_tags': [tagJson(1, '运动'), tagJson(3, '电影')],
        });

    final result = await repository.swipe(targetUserId: 9, like: true);

    expect(result.matched, isTrue);
    expect(result.sharedTags.map((tag) => tag.name), ['运动', '电影']);
  });
}
