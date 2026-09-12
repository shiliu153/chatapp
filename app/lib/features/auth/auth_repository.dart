import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/api_exception.dart';
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
    try {
      return await _verify(phone, code);
    } on ApiException catch (error) {
      // 网络级失败(无 HTTP 状态码)自动重试一次:服务端有 60 秒幂等重放窗口,同码安全
      if (error.statusCode != null) rethrow;
      return _verify(phone, code);
    }
  }

  Future<LoginResult> _verify(String phone, String code) async {
    final data = await _api.post('/auth/sms/verify', data: {'phone': phone, 'code': code});
    return LoginResult.fromJson(data as Map<String, dynamic>);
  }
}

final authRepositoryProvider =
    Provider<AuthRepository>((ref) => AuthRepository(ref.watch(apiClientProvider)));
