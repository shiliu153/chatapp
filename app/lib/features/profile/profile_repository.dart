import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/api_exception.dart';
import '../../core/providers.dart';
import 'models.dart';

class ProfileRepository {
  ProfileRepository(this._api);

  final ApiClient _api;

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

  /// 上传语音自我介绍(multipart 字段 `file`;覆盖式,一人一条)。
  ///
  /// 响应里的 `url` 已经是公开绝对地址,直接用,别再拼 `API_BASE`。
  Future<VoiceIntro> uploadVoice(Uint8List bytes, String filename) async {
    final data = await _api.post('/users/me/voice',
        data: FormData.fromMap({'file': MultipartFile.fromBytes(bytes, filename: filename)}));
    final voice = VoiceIntro.parse(data);
    if (voice == null) throw ApiException('语音上传失败,请重试');
    return voice;
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
