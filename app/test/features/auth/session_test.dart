import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/features/auth/session.dart';
import 'package:chatapp_app/im/im_manager.dart';

import '../../support/fake_im_client.dart';
import '../../support/scripted_adapter.dart';

void main() {
  late ScriptedAdapter adapter;
  late FakeImClient fakeIm;

  ProviderContainer makeContainer() {
    final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
    final refreshDio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
    return ProviderContainer(overrides: [
      baseDioProvider.overrideWithValue(dio),
      refreshDioProvider.overrideWithValue(refreshDio),
      imClientProvider.overrideWithValue(fakeIm),
    ]);
  }

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    adapter = ScriptedAdapter({});
    fakeIm = FakeImClient();
    addTearDown(fakeIm.dispose);
  });

  test('没有 refresh token → 未登录', () async {
    final container = makeContainer();
    addTearDown(container.dispose);
    await container.read(sessionProvider.notifier).bootstrap();
    expect(container.read(sessionProvider), isA<SessionLoggedOut>());
  });

  test('有 refresh token → 静默刷新成功 → 已登录', () async {
    SharedPreferences.setMockInitialValues(
        {'auth.access': 'a', 'auth.refresh': 'r', 'auth.user_id': 7});
    adapter.routes['POST /auth/token/refresh'] = (options) => ok({'access': 'a2', 'refresh': 'r2'});
    final container = makeContainer();
    addTearDown(container.dispose);
    await container.read(sessionProvider.notifier).bootstrap();
    expect(container.read(sessionProvider), isA<SessionLoggedIn>());
  });

  test('refresh 被拒(401)→ 清空凭证并回登录页', () async {
    SharedPreferences.setMockInitialValues(
        {'auth.access': 'a', 'auth.refresh': 'r', 'auth.user_id': 7});
    adapter.routes['POST /auth/token/refresh'] = (options) => jsonError(401, 'Token 无效或已过期');
    final container = makeContainer();
    addTearDown(container.dispose);
    await container.read(sessionProvider.notifier).bootstrap();
    expect(container.read(sessionProvider), isA<SessionLoggedOut>());
    expect((await SharedPreferences.getInstance()).getString('auth.refresh'), isNull);
  });

  test('网络失败 → 启动失败,凭证保留可重试', () async {
    SharedPreferences.setMockInitialValues(
        {'auth.access': 'a', 'auth.refresh': 'r', 'auth.user_id': 7});
    adapter.routes['POST /auth/token/refresh'] = offline;
    final container = makeContainer();
    addTearDown(container.dispose);
    await container.read(sessionProvider.notifier).bootstrap();
    expect(container.read(sessionProvider), isA<SessionBootFailed>());
    expect((await SharedPreferences.getInstance()).getString('auth.refresh'), 'r');
  });

  test('登录成功 → 凭证落盘 + 已登录', () async {
    adapter.routes['POST /auth/sms/verify'] =
        (options) => ok({'access': 'a3', 'refresh': 'r3', 'is_new_user': true, 'user_id': 9});
    final container = makeContainer();
    addTearDown(container.dispose);
    final result = await container.read(sessionProvider.notifier).login('13800138000', '123456');
    expect(result.isNewUser, isTrue);
    expect(container.read(sessionProvider), isA<SessionLoggedIn>());
    expect(await container.read(tokenStoreProvider).userId, 9);
  });

  test('登出 → 凭证清空 + 未登录', () async {
    adapter.routes['POST /auth/sms/verify'] =
        (options) => ok({'access': 'a3', 'refresh': 'r3', 'is_new_user': false, 'user_id': 9});
    final container = makeContainer();
    addTearDown(container.dispose);
    await container.read(sessionProvider.notifier).login('13800138000', '123456');
    await container.read(sessionProvider.notifier).logout();
    expect(container.read(sessionProvider), isA<SessionLoggedOut>());
    expect(await container.read(tokenStoreProvider).refreshToken, isNull);
  });

  test('登录成功 → 触发 IM 登录', () async {
    adapter.routes['POST /auth/sms/verify'] =
        (options) => ok({'access': 'a3', 'refresh': 'r3', 'is_new_user': false, 'user_id': 9});
    adapter.routes['POST /im/user_sig'] = (options) => ok({
          'user_sig': 'sig',
          'sdkappid': '1600161711',
          'im_user_id': 'u9',
          'expire': 604800,
        });
    final container = makeContainer();
    addTearDown(container.dispose);

    await container.read(sessionProvider.notifier).login('13800138000', '123456');
    await pumpEventQueue();

    expect(fakeIm.log, contains('login:u9'));
  });

  test('登出 → 触发 IM 登出(防串号)', () async {
    adapter.routes['POST /auth/sms/verify'] =
        (options) => ok({'access': 'a3', 'refresh': 'r3', 'is_new_user': false, 'user_id': 9});
    adapter.routes['POST /im/user_sig'] = (options) => ok({
          'user_sig': 'sig',
          'sdkappid': '1600161711',
          'im_user_id': 'u9',
          'expire': 604800,
        });
    final container = makeContainer();
    addTearDown(container.dispose);
    await container.read(sessionProvider.notifier).login('13800138000', '123456');
    await pumpEventQueue();

    await container.read(sessionProvider.notifier).logout();
    await pumpEventQueue();

    expect(fakeIm.log, contains('logout'));
  });
}
