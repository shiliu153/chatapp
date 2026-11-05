import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import '../profile/models.dart';
import 'models.dart';

class DiscoveryRepository {
  DiscoveryRepository(this._api);

  final ApiClient _api;

  Future<List<Candidate>> fetchCandidates({int limit = 10}) async {
    final data =
        await _api.get('/discovery/candidates', query: {'limit': limit}) as List<dynamic>;
    return data.map((item) => Candidate.fromJson(item as Map<String, dynamic>)).toList();
  }

  /// 滑一张卡;返回是否配对成功,以及配对成功时后端直接给出的共同标签。
  ///
  /// 共同标签只用来渲染「配对那一刻」的破冰文案,不要为了它再拉一次对方资料 ——
  /// 那会被记成一次访客访问(discovery.md §3.2)。
  Future<({bool matched, List<Tag> sharedTags})> swipe({
    required int targetUserId,
    required bool like,
  }) async {
    final data = await _api.post('/discovery/swipe',
            data: {'target_user_id': targetUserId, 'action': like ? 'like' : 'pass'})
        as Map<String, dynamic>;
    return (
      matched: data['matched'] == true,
      sharedTags: ((data['shared_tags'] ?? const []) as List<dynamic>)
          .map((item) => Tag.fromJson(item as Map<String, dynamic>))
          .toList(),
    );
  }

  /// 喜欢我的人(游标分页);返回本页条目、后端总数与下一页游标。
  Future<({List<LikeReceived> items, int count, String? nextCursor})> fetchLikesReceived(
      {int limit = 20, String? cursor}) async {
    final data = await _api.get('/discovery/likes', query: {
      'limit': limit,
      'before': ?cursor,
    }) as Map<String, dynamic>;
    final items = (data['results'] as List<dynamic>)
        .map((item) => LikeReceived.fromJson(item as Map<String, dynamic>))
        .toList();
    return (items: items, count: data['count'] as int,
        nextCursor: data['next_cursor'] as String?);
  }

  /// 入口角标:只查数量。
  Future<int> fetchLikesReceivedCount() async {
    final data = await _api.get('/discovery/likes/count') as Map<String, dynamic>;
    return data['count'] as int;
  }

  /// 谁看过我(游标分页);返回本页条目、后端总数与下一页游标。
  Future<({List<Visit> items, int count, String? nextCursor})> fetchVisits(
      {int limit = 20, String? cursor}) async {
    final data = await _api.get('/discovery/visits', query: {
      'limit': limit,
      'before': ?cursor,
    }) as Map<String, dynamic>;
    final items = (data['results'] as List<dynamic>)
        .map((item) => Visit.fromJson(item as Map<String, dynamic>))
        .toList();
    return (items: items, count: data['count'] as int,
        nextCursor: data['next_cursor'] as String?);
  }

  /// 访客入口角标:只查数量。
  Future<int> fetchVisitsCount() async {
    final data = await _api.get('/discovery/visits/count') as Map<String, dynamic>;
    return data['count'] as int;
  }
}

final discoveryRepositoryProvider = Provider<DiscoveryRepository>(
    (ref) => DiscoveryRepository(ref.watch(apiClientProvider)));
