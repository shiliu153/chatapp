import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/im/im_client.dart';
import 'package:chatapp_app/im/im_manager.dart';

import '../support/fake_im_client.dart';
import '../support/scripted_adapter.dart';

void main() {
  late ScriptedAdapter adapter;
  late FakeImClient fake;

  ProviderContainer makeContainer() {
    final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
    final container = ProviderContainer(overrides: [
      baseDioProvider.overrideWithValue(dio),
      refreshDioProvider.overrideWithValue(dio),
      imClientProvider.overrideWithValue(fake),
    ]);
    addTearDown(container.dispose);
    return container;
  }

  void stubUserSig() {
    adapter.routes['POST /im/user_sig'] = (options) => ok({
          'user_sig': 'sig-abc',
          'sdkappid': '1600161711',
          'im_user_id': 'u3',
          'expire': 604800,
        });
  }

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    adapter = ScriptedAdapter({});
    fake = FakeImClient();
    addTearDown(fake.dispose);
  });

  test('login 成功:init → login → 已登录', () async {
    stubUserSig();
    final container = makeContainer();

    await container.read(imStatusProvider.notifier).login();

    expect(container.read(imStatusProvider), isA<ImLoggedIn>());
    expect(fake.log, ['init:1600161711', 'login:u3']);
  });

  test('拿 userSig 失败(403 封禁)→ ImFailed 带后端中文提示', () async {
    adapter.routes['POST /im/user_sig'] = (options) => jsonError(403, '账号已被封禁');
    final container = makeContainer();

    await container.read(imStatusProvider.notifier).login();

    final status = container.read(imStatusProvider);
    expect(status, isA<ImFailed>());
    expect((status as ImFailed).message, '账号已被封禁');
    expect(fake.log, isEmpty); // 没签名就不该碰 SDK
  });

  test('SDK 登录报错 → ImFailed 带错误码', () async {
    stubUserSig();
    fake.loginError = const ImException(6206, 'sig expired');
    final container = makeContainer();

    await container.read(imStatusProvider.notifier).login();

    expect((container.read(imStatusProvider) as ImFailed).message, contains('6206'));
  });

  test('logout:调 SDK 登出 → 未登录', () async {
    stubUserSig();
    final container = makeContainer();
    await container.read(imStatusProvider.notifier).login();

    await container.read(imStatusProvider.notifier).logout();

    expect(container.read(imStatusProvider), isA<ImLoggedOut>());
    expect(fake.log, ['init:1600161711', 'login:u3', 'logout']);
  });

  test('userSig 过期事件 → 自动重新拉签名登录', () async {
    stubUserSig();
    final container = makeContainer();
    await container.read(imStatusProvider.notifier).login();

    fake.emit(const ImSigExpired());
    await pumpEventQueue();

    expect(container.read(imStatusProvider), isA<ImLoggedIn>());
    expect(fake.log, ['init:1600161711', 'login:u3', 'login:u3']);
  });

  test('被踢下线 → ImFailed 提示', () async {
    stubUserSig();
    final container = makeContainer();
    await container.read(imStatusProvider.notifier).login();

    fake.emit(const ImKickedOffline());
    await pumpEventQueue();

    expect((container.read(imStatusProvider) as ImFailed).message, contains('其他设备'));
  });
}
