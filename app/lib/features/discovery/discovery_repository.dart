import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import 'models.dart';

class DiscoveryRepository {
  DiscoveryRepository(this._api);

  final ApiClient _api;

  Future<List<Candidate>> fetchCandidates({int limit = 10}) async {
    final data =
        await _api.get('/discovery/candidates', query: {'limit': limit}) as List<dynamic>;
    return data.map((item) => Candidate.fromJson(item as Map<String, dynamic>)).toList();
  }

  /// 滑一张卡;返回是否配对成功。
  Future<bool> swipe({required int targetUserId, required bool like}) async {
    final data = await _api.post('/discovery/swipe',
        data: {'target_user_id': targetUserId, 'action': like ? 'like' : 'pass'});
    return (data as Map<String, dynamic>)['matched'] == true;
  }

  /// 喜欢我的人(分页);返回本页条目与后端总数。
  Future<({List<LikeReceived> items, int count})> fetchLikesReceived(
      {int limit = 20, int offset = 0}) async {
    final data = await _api.get('/discovery/likes',
        query: {'limit': limit, 'offset': offset}) as Map<String, dynamic>;
    final items = (data['results'] as List<dynamic>)
        .map((item) => LikeReceived.fromJson(item as Map<String, dynamic>))
        .toList();
    return (items: items, count: data['count'] as int);
  }

  /// 入口角标:只查数量。
  Future<int> fetchLikesReceivedCount() async {
    final data = await _api.get('/discovery/likes/count') as Map<String, dynamic>;
    return data['count'] as int;
  }
}

final discoveryRepositoryProvider = Provider<DiscoveryRepository>(
    (ref) => DiscoveryRepository(ref.watch(apiClientProvider)));
