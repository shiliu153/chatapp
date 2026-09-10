import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';

class LoginResult {
  const LoginResult({
    required this.access,
    required this.refresh,
    required this.userId,
    required this.isNewUser,
  });

  factory LoginResult.fromJson(Map<String, dynamic> json) => LoginResult(
        access: json['access'] as String,
        refresh: json['refresh'] as String,
        userId: json['user_id'] as int,
        isNewUser: json['is_new_user'] as bool,
      );

  final String access;
  final String refresh;
  final int userId;
  final bool isNewUser;
}

class AuthRepository {
  AuthRepository(this._api);

  final ApiClient _api;

  Future<void> sendSms(String phone) async {
    await _api.post('/auth/sms/send', data: {'phone': phone});
  }

  Future<LoginResult> verifySms(String phone, String code) async {
    final data = await _api.post('/auth/sms/verify', data: {'phone': phone, 'code': code});
    return LoginResult.fromJson(data as Map<String, dynamic>);
  }
}

final authRepositoryProvider =
    Provider<AuthRepository>((ref) => AuthRepository(ref.watch(apiClientProvider)));
