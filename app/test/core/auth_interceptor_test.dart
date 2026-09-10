import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/api_client.dart';
import 'package:chatapp_app/core/api_exception.dart';
import 'package:chatapp_app/core/auth_interceptor.dart';
import 'package:chatapp_app/core/token_refresher.dart';
import 'package:chatapp_app/core/token_store.dart';

import '../support/scripted_adapter.dart';

void main() {
  late TokenStore store;
  late ScriptedAdapter adapter;
  late ApiClient client;

  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    store = TokenStore();
    await store.save(access: 'old-access', refresh: 'refresh-1', userId: 1);
    adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'new-access', 'refresh': 'refresh-2'}),
    });
    final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
    final refreshDio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
    dio.interceptors.add(AuthInterceptor(
      tokenStore: store,
      refresher: TokenRefresher(dio: refreshDio, tokenStore: store),
    ));
    client = ApiClient(dio);
  });

  test('请求自动带上 Authorization', () async {
    adapter.routes['GET /users/me'] = (options) => ok({'nickname': '小明'});
    expect(await client.get('/users/me'), {'nickname': '小明'});
    expect(adapter.log.last.headers['Authorization'], 'Bearer old-access');
  });

  test('401 → 静默刷新 → 用新 token 重放一次', () async {
    var attempts = 0;
    adapter.routes['GET /users/me'] = (options) {
      attempts++;
      if (options.headers['Authorization'] == 'Bearer new-access') {
        return ok({'nickname': '小明'});
      }
      return jsonError(401, '身份认证信息未提供');
    };
    expect(await client.get('/users/me'), {'nickname': '小明'});
    expect(attempts, 2);
    expect(await store.accessToken, 'new-access');
    expect(await store.refreshToken, 'refresh-2');
  });

  test('刷新也被拒 → 清空凭证并抛原始错误', () async {
    adapter.routes['POST /auth/token/refresh'] = (options) => jsonError(401, 'Token 无效或已过期');
    adapter.routes['GET /users/me'] = (options) => jsonError(401, '身份认证信息未提供');
    await expectLater(client.get('/users/me'), throwsA(isA<ApiException>()));
    expect(await store.accessToken, isNull);
    expect(await store.refreshToken, isNull);
  });

  test('非 401 错误原样抛出,不触发刷新', () async {
    adapter.routes['GET /users/me'] = (options) => jsonError(500, '服务器开小差了');
    await expectLater(
      client.get('/users/me'),
      throwsA(predicate((error) => error is ApiException && error.message == '服务器开小差了')),
    );
    expect(adapter.log.where((r) => r.path == '/auth/token/refresh'), isEmpty);
  });
}
