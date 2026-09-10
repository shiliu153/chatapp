import 'package:dio/dio.dart';

import 'api_exception.dart';
import 'token_refresher.dart';
import 'token_store.dart';

/// 给请求带上 access token;401 时静默刷新一次并重放原请求。
/// 刷新彻底失败就清空凭证 —— TokenStore 的通知会把人踢回登录页。
class AuthInterceptor extends Interceptor {
  AuthInterceptor({required this.tokenStore, required this.refresher});

  static const _retriedFlag = 'auth.retried';

  final TokenStore tokenStore;
  final TokenRefresher refresher;

  @override
  Future<void> onRequest(RequestOptions options, RequestInterceptorHandler handler) async {
    final token = await tokenStore.accessToken;
    if (token != null) {
      options.headers['Authorization'] = 'Bearer $token';
    }
    handler.next(options);
  }

  @override
  Future<void> onError(DioException err, ErrorInterceptorHandler handler) async {
    final options = err.requestOptions;
    final expired = err.response?.statusCode == 401;
    if (!expired || options.extra[_retriedFlag] == true) {
      return handler.next(err);
    }

    final String? newToken;
    try {
      newToken = await refresher.refresh();
    } on ApiException catch (error) {
      if (error.statusCode == 401) {
        await tokenStore.clear(); // refresh 也过期了:真正掉线
      }
      return handler.next(err);
    }
    if (newToken == null) {
      await tokenStore.clear(); // 本地连 refresh token 都没有
      return handler.next(err);
    }

    options.extra[_retriedFlag] = true;
    options.headers['Authorization'] = 'Bearer $newToken';
    try {
      handler.resolve(await refresher.dio.fetch<dynamic>(options));
    } on DioException catch (error) {
      handler.next(error);
    }
  }
}
