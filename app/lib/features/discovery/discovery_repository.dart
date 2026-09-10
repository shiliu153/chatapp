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
}

final discoveryRepositoryProvider = Provider<DiscoveryRepository>(
    (ref) => DiscoveryRepository(ref.watch(apiClientProvider)));
