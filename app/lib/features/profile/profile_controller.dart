import 'dart:typed_data';

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

  /// 上传语音自我介绍;成功后把响应里的 `voice` 原地写回资料(不必整页 reload)。
  ///
  /// 失败原样抛出,由录音卡弹提示(400 时长超限 / 413 配额满 的 message 都是中文)。
  Future<VoiceIntro> uploadVoice(Uint8List bytes, String filename) async {
    final voice = await ref.read(profileRepositoryProvider).uploadVoice(bytes, filename);
    final current = state.value;
    if (current != null) state = AsyncValue.data(current.withVoice(voice));
    return voice;
  }

  /// 删除语音自我介绍;成功后把资料里的 `voice` 置空。
  Future<void> deleteVoice() async {
    await ref.read(profileRepositoryProvider).deleteVoice();
    final current = state.value;
    if (current != null) state = AsyncValue.data(current.withVoice(null));
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
