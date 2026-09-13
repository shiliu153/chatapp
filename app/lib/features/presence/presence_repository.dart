import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import 'models.dart';

/// 在线状态批量查询的纯 IO 封装。
class PresenceRepository {
  PresenceRepository(this._api);

  final ApiClient _api;

  /// 返回 user_id → Presence;接口省略的人(拉黑/不存在)没有条目。
  Future<Map<int, Presence>> fetchPresence(List<int> userIds) async {
    if (userIds.isEmpty) return const {};
    final data = await _api.get('/presence', query: {'user_ids': userIds.join(',')})
        as Map<String, dynamic>;
    return {
      for (final item in (data['results'] as List<dynamic>).cast<Map<String, dynamic>>())
        item['user_id'] as int: Presence.fromJson(item),
    };
  }
}

final presenceRepositoryProvider = Provider<PresenceRepository>(
    (ref) => PresenceRepository(ref.watch(apiClientProvider)));
