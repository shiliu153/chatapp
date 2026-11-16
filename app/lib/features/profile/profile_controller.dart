import 'dart:typed_data';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../im/voice_transcode.dart';
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
  /// 转码排队(202)期间**先把旧语音下线**:服务端受理时就已经把旧文件删了、`GET /users/me`
  /// 的 `voice` 变回 null(`docs/api/users.md` §2.11),本地不跟着清会显示一条已经听不到的语音。
  ///
  /// Args:
  ///   bytes: 本地录音字节。
  ///   filename: multipart 文件名。
  ///   hook: 转码进度回调(录音卡据此把状态切成「处理中」)。
  ///
  /// Returns:
  ///   可播放的资料语音。
  ///
  /// Throws:
  ///   [ApiException]:400 时长超限 / 413 配额满 等,message 都是中文可直接展示;
  ///   [VoiceTranscodeException]:转码失败或轮询超时。
  Future<VoiceIntro> uploadVoice(Uint8List bytes, String filename,
      {VoiceTranscodeHook? hook}) async {
    final voice = await ref.read(profileRepositoryProvider).uploadVoice(
          bytes,
          filename,
          // 受理即下线旧语音:服务端在 202 时已经把旧文件删掉了(覆盖语义),
          // 本地不跟着清会让资料页继续显示一条已经听不到的语音。
          hook: VoiceTranscodeHook(
            onQueued: (id, retryAfter) {
              dropVoiceWhileTranscoding();
              hook?.onQueued?.call(id, retryAfter);
            },
            cancelled: hook?.cancelled,
          ),
        );
    final current = state.value;
    if (current != null) state = AsyncValue.data(current.withVoice(voice));
    return voice;
  }

  /// 转码受理时把资料里的旧语音清掉(异步路径的覆盖语义,见 [uploadVoice])。
  void dropVoiceWhileTranscoding() {
    final current = state.value;
    if (current?.voice == null) return;
    state = AsyncValue.data(current!.withVoice(null));
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
