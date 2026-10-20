import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api_client.dart';
import '../providers.dart';

/// 三类通知开关(账号级,与后端 `NotificationPreference` 一一对应)。
class PushPreferences {
  const PushPreferences({required this.likes, required this.matches, required this.system});

  factory PushPreferences.fromJson(Map<String, dynamic> json) => PushPreferences(
        likes: json['likes'] as bool,
        matches: json['matches'] as bool,
        system: json['system'] as bool,
      );

  final bool likes;
  final bool matches;
  final bool system;

  PushPreferences copyWith({bool? likes, bool? matches, bool? system}) => PushPreferences(
        likes: likes ?? this.likes,
        matches: matches ?? this.matches,
        system: system ?? this.system,
      );
}

/// 推送相关的后端调用:设备上报/解绑与偏好读写。
class PushRepository {
  PushRepository(this._api);

  final ApiClient _api;

  Future<PushPreferences> fetchPreferences() async {
    final data = await _api.get('/push/preferences') as Map<String, dynamic>;
    return PushPreferences.fromJson(data);
  }

  Future<PushPreferences> updatePreferences({bool? likes, bool? matches, bool? system}) async {
    final data = await _api.patch('/push/preferences', data: {
      'likes': ?likes,
      'matches': ?matches,
      'system': ?system,
    }) as Map<String, dynamic>;
    return PushPreferences.fromJson(data);
  }

  Future<void> registerDevice(String registrationId,
      {String platform = 'android', String? appVersion}) async {
    await _api.post('/push/devices', data: {
      'registration_id': registrationId,
      'platform': platform,
      'app_version': ?appVersion,
    });
  }

  Future<void> unregisterDevice(String registrationId) async {
    await _api.delete('/push/devices/$registrationId');
  }
}

final pushRepositoryProvider =
    Provider<PushRepository>((ref) => PushRepository(ref.watch(apiClientProvider)));
