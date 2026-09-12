import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'models.dart';
import 'profile_repository.dart';

class ProfileController extends AsyncNotifier<Profile> {
  @override
  Future<Profile> build() => ref.watch(profileRepositoryProvider).fetchMe();

  Future<void> reload() async {
    state = const AsyncValue.loading();
    state = await AsyncValue.guard(() => ref.read(profileRepositoryProvider).fetchMe());
  }

  /// 保存资料;失败原样抛出,由页面弹提示。
  Future<void> save(Map<String, dynamic> patch) async {
    final updated = await ref.read(profileRepositoryProvider).update(patch);
    state = AsyncValue.data(updated);
  }
}

final profileProvider =
    AsyncNotifierProvider<ProfileController, Profile>(
  ProfileController.new,
  // 我的页有手动「重试」;关掉 Riverpod 3 自动重试(聊天页也读它取自己头像)
  retry: (retryCount, error) => null,
);

final tagsProvider =
    FutureProvider<List<Tag>>((ref) => ref.watch(profileRepositoryProvider).fetchTags());
