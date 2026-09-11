import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'models.dart';
import 'moderation_repository.dart';

/// 对方资料卡;404(不存在/被封禁/有拉黑关系)由页面按 ApiException 展示。
final userProfileProvider = FutureProvider.family<UserProfile, int>(
  (ref, userId) => ref.watch(moderationRepositoryProvider).fetchUserProfile(userId),
  retry: (retryCount, error) => null,   // 页面有手动「重试」,关掉自动重试免得错误态一闪而过
);

class BlockedUsersController extends AsyncNotifier<List<BlockedUser>> {
  @override
  Future<List<BlockedUser>> build() =>
      ref.watch(moderationRepositoryProvider).fetchBlockedUsers();

  Future<void> reload() async {
    state = const AsyncValue.loading();
    state = await AsyncValue.guard(
        () => ref.read(moderationRepositoryProvider).fetchBlockedUsers());
  }
}

final blockedUsersProvider =
    AsyncNotifierProvider<BlockedUsersController, List<BlockedUser>>(
  BlockedUsersController.new,
  retry: (retryCount, error) => null,
);
