import 'package:dio/dio.dart';

import '../im/im_client.dart';
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

    String? newToken;
    // 单设备登录:账号已在别处登录,刷新救不了
    final body = err.response?.data;
    if (body is Map && body['code'] == singleDeviceCode) {
      final rejected = options.headers['Authorization'];
      final current = await tokenStore.accessToken;
      if (current != null && rejected != 'Bearer $current') {
        // 本机已经换了新令牌(顶号/登录的竞态):这是旧令牌的在途请求,换新令牌重试
        newToken = current;
      } else {
        await tokenStore.forceLogout(kickedOfflineMessage);
        return handler.next(err);
      }
    } else if (await tokenStore.accessToken == null) {
      // 本机凭证已空(会话已被终结,如被顶号后清过):这个 401 是「没有身份」,
      // 刷新救不了也不能当普通网络错误 —— 收尾为被顶号强退,让提示说清原因
      await tokenStore.forceLogout(kickedOfflineMessage);
      return handler.next(err);
    } else {
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
