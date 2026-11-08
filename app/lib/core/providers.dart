import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'api_client.dart';
import 'auth_interceptor.dart';
import 'client_header.dart';
import 'config.dart';
import 'pinned_tls.dart';
import 'token_refresher.dart';
import 'token_store.dart';

final tokenStoreProvider = Provider<TokenStore>((ref) => TokenStore());

/// 生产用的 Dio 模板:证书绑定 + 统一 `X-Client: app`。
///
/// 头挂在拦截器上而不是 BaseOptions:请求发出前才决定要不要补,调用方已显式
/// 设了同名头就保留(见 [ClientHeaderInterceptor])。
Dio _newDio() => Dio(BaseOptions(
      baseUrl: apiBase,
      connectTimeout: const Duration(seconds: 10),
      receiveTimeout: const Duration(seconds: 10),
    ))
      ..httpClientAdapter = PinnedTls.adapter()
      ..interceptors.add(const ClientHeaderInterceptor());

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
