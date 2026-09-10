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
    AsyncNotifierProvider<ProfileController, Profile>(ProfileController.new);

final tagsProvider =
    FutureProvider<List<Tag>>((ref) => ref.watch(profileRepositoryProvider).fetchTags());
