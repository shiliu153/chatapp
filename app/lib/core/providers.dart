import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'api_client.dart';
import 'auth_interceptor.dart';
import 'config.dart';
import 'token_refresher.dart';
import 'token_store.dart';

final tokenStoreProvider = Provider<TokenStore>((ref) => TokenStore());

Dio _newDio() => Dio(BaseOptions(
      baseUrl: apiBase,
      connectTimeout: const Duration(seconds: 10),
      receiveTimeout: const Duration(seconds: 10),
    ));

/// 业务请求用的 Dio(带拦截器);测试里 override 成挂了 ScriptedAdapter 的实例。
final baseDioProvider = Provider<Dio>((ref) => _newDio());

/// 裸 Dio,只给 TokenRefresher 用。
final refreshDioProvider = Provider<Dio>((ref) => _newDio());

final tokenRefresherProvider = Provider<TokenRefresher>((ref) => TokenRefresher(
      dio: ref.watch(refreshDioProvider),
      tokenStore: ref.watch(tokenStoreProvider),
    ));

final apiClientProvider = Provider<ApiClient>((ref) {
  final dio = ref.watch(baseDioProvider);
  dio.interceptors.add(AuthInterceptor(
    tokenStore: ref.watch(tokenStoreProvider),
    refresher: ref.watch(tokenRefresherProvider),
  ));
  return ApiClient(dio);
});
