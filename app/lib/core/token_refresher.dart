import 'package:dio/dio.dart';

import '../im/im_client.dart';
import 'api_exception.dart';
import 'token_store.dart';

/// 用 refresh token 换新 access(服务端同时轮换 refresh)。
/// 单飞:并发的 401 只打一次刷新接口,大家共用同一个 Future。
class TokenRefresher {
  TokenRefresher({required this.dio, required this.tokenStore});

  /// 必须是**不带 AuthInterceptor** 的裸 Dio,否则刷新 401 会递归。
  final Dio dio;
  final TokenStore tokenStore;

  Future<String?>? _inFlight;

  /// 成功 → 新 access;没有 refresh token → null;刷新被拒/网络失败 → 抛 ApiException。
  Future<String?> refresh() => _inFlight ??= _refresh().whenComplete(() => _inFlight = null);

  Future<String?> _refresh() async {
    final refreshToken = await tokenStore.refreshToken;
    if (refreshToken == null) return null;

    final Response<dynamic> response;
    try {
      response = await dio.post<dynamic>('/auth/token/refresh', data: {'refresh': refreshToken});
    } on DioException catch (error) {
      final apiError = ApiException.from(error);
      if (apiError.code == singleDeviceCode) {
        // 单设备登录:refresh 也被判作废,清凭证并留下原因(登录页提示)
        await tokenStore.forceLogout(kickedOfflineMessage);
      }
      throw apiError;
    }

    final data = response.data as Map<String, dynamic>;
    final access = data['access'] as String;
    final rotated = data['refresh'] as String? ?? refreshToken;
    await tokenStore.saveTokens(access: access, refresh: rotated);
    return access;
  }
}
