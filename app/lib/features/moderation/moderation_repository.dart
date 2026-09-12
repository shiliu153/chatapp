import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import 'models.dart';

class ModerationRepository {
  ModerationRepository(this._api);

  final ApiClient _api;

  Future<UserProfile> fetchUserProfile(int userId) async =>
      UserProfile.fromJson(await _api.get('/users/$userId') as Map<String, dynamic>);

  Future<void> report({required int targetUserId, required String type, String detail = ''}) async {
    await _api.post('/reports', data: {
      'target_user_id': targetUserId,
      'type': type,
      'detail': detail,
    });
  }

  Future<void> block(int userId) async {
    await _api.post('/blocks', data: {'target_user_id': userId});
  }

  Future<void> unblock(int userId) async {
    await _api.delete('/blocks/$userId');
  }

  Future<List<BlockedUser>> fetchBlockedUsers() async {
    final data = await _api.getAllPages('/blocks');
    return data.map((item) => BlockedUser.fromJson(item as Map<String, dynamic>)).toList();
  }
}

final moderationRepositoryProvider =
    Provider<ModerationRepository>((ref) => ModerationRepository(ref.watch(apiClientProvider)));
