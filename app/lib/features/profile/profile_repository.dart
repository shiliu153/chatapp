import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/api_exception.dart';
import '../../core/providers.dart';
import '../../im/voice_transcode.dart';
import 'models.dart';

class ProfileRepository {
  ProfileRepository(this._api, {this.sleep});

  final ApiClient _api;

  /// 转码轮询的等待实现;测试里注入 no-op,免得真等 5 秒。
  final Future<void> Function(Duration delay)? sleep;

  Future<Profile> fetchMe() async =>
      Profile.fromJson(await _api.get('/users/me') as Map<String, dynamic>);

  Future<Profile> update(Map<String, dynamic> patch) async =>
      Profile.fromJson(await _api.patch('/users/me', data: patch) as Map<String, dynamic>);

  Future<List<Tag>> fetchTags() async {
    final data = await _api.get('/users/tags') as List<dynamic>;
    return data.map((item) => Tag.fromJson(item as Map<String, dynamic>)).toList();
  }

  Future<Photo> uploadPhoto(Uint8List bytes, String filename) async {
    final data = await _api.post('/users/me/photos',
        data: FormData.fromMap({'file': MultipartFile.fromBytes(bytes, filename: filename)}));
    return Photo.fromJson(data as Map<String, dynamic>);
  }

  Future<void> deletePhoto(int photoId) async {
    await _api.delete('/users/me/photos/$photoId');
  }

  /// 上传语音自我介绍(multipart 字段 `file`;覆盖式,一人一条),并等到转码完成。
  ///
  /// `contentType` **必须显式给**:`.m4a` 不在 `mime` 包里,Dio 会退化成
  /// `application/octet-stream`,而服务端白名单(`im/voice.py::ALLOWED_CONTENT_TYPES`)
  /// 只收 audio/mp4、audio/m4a、audio/x-m4a、audio/aac、audio/webm、audio/ogg ——
  /// 漏了它上传必然 400「只支持 M4A/AAC/WebM/OGG 音频」。
  /// 录音器输出固定是 AAC-LC 的 m4a(见 `im/voice_recorder.dart`),所以恒为 audio/mp4,
  /// 与聊天语音上传(`im/self_voice_uploader.dart`)同一条写法。
  ///
  /// 两条路径(`docs/api/users.md` §2.11):`201` 直接可播;`202`(转码槽被占)时文件已
  /// 落临时区、转码在 Celery 里排队,这里按 `retry_after` 轮询 §2.13 直到 `ready`。
  /// 转码失败抛 [VoiceTranscodeException],文案可直接展示。
  ///
  /// Args:
  ///   bytes: 本地录音字节。
  ///   filename: multipart 里的文件名。
  ///   hook: 转码进度回调(受理时通知卡片显示「处理中」,离开页面时让轮询收工)。
  ///
  /// Returns:
  ///   可播放的资料语音;`url` 是限时签名地址,直接用,别再拼 `API_BASE`。
  Future<VoiceIntro> uploadVoice(Uint8List bytes, String filename,
      {VoiceTranscodeHook? hook}) async {
    final data = await _api.post('/users/me/voice',
        data: FormData.fromMap({
          'file': MultipartFile.fromBytes(bytes,
              filename: filename, contentType: DioMediaType('audio', 'mp4')),
        })) as Map<String, dynamic>;

    // 202 与 201 的判别用响应体里的 `status`:契约里 202 恒为 pending、201 恒为 ready
    // (docs/api/users.md §2.11)。body 已经足够区分,不必再看 HTTP 状态码。
    final queued = data['status'] == 'pending' ? VoiceQueued.parse(data) : null;
    if (queued == null) {
      final voice = VoiceIntro.parse(data);
      if (voice == null) throw ApiException('语音上传失败,请重试');
      return voice;
    }

    hook?.onQueued?.call(queued.id, queued.retryAfter);
    final result = await VoiceTranscodePoller(
      fetch: fetchVoiceStatus,
      cancelled: hook?.cancelled,
      sleep: sleep,
    ).run(retryAfter: queued.retryAfter);
    final status = result.status;
    if (result.outcome == VoicePollOutcome.settled && status != null && status.isReady) {
      return VoiceIntro(
        url: status.url ?? '',
        durationMs: status.durationMs ?? 0,
        status: 'ready',
        id: status.id,
      );
    }
    throw VoiceTranscodeException(voicePollFailureText(result), code: status?.code);
  }

  /// 查资料语音转码状态(`GET /users/me/voice`,`docs/api/users.md` §2.13)。
  ///
  /// **404 = 还没录过语音,不是错误**(契约如此),返回 null;其它错误照常抛。
  ///
  /// Returns:
  ///   转码状态;没有语音时为 null。
  Future<VoiceTranscode?> fetchVoiceStatus() async {
    try {
      return VoiceTranscode.parse(await _api.get('/users/me/voice'));
    } on ApiException catch (error) {
      if (error.statusCode == 404) return null;
      rethrow;
    }
  }

  /// 删除语音自我介绍(幂等 204)。
  Future<void> deleteVoice() async {
    await _api.delete('/users/me/voice');
  }

  Future<Preference> fetchPreference() async =>
      Preference.fromJson(await _api.get('/users/me/preference') as Map<String, dynamic>);

  Future<Preference> updatePreference(Map<String, dynamic> patch) async => Preference.fromJson(
      await _api.patch('/users/me/preference', data: patch) as Map<String, dynamic>);
}

final profileRepositoryProvider =
    Provider<ProfileRepository>((ref) => ProfileRepository(ref.watch(apiClientProvider)));
