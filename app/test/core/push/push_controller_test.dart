import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/core/push/push_controller.dart';
import 'package:chatapp_app/features/auth/session.dart';
import 'package:chatapp_app/features/presence/presence_controller.dart';
import 'package:chatapp_app/im/im_manager.dart';

import '../../support/fake_im_client.dart';
import '../../support/fake_push_service.dart';
import '../../support/scripted_adapter.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late ScriptedAdapter adapter;
  late FakeImClient fakeIm;
  late FakePushService fakePush;
  late ProviderContainer container;
  late List<String> opened;

  void buildContainer() {
    final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
    final refreshDio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))
      ..httpClientAdapter = adapter;
    container = ProviderContainer(overrides: [
      baseDioProvider.overrideWithValue(dio),
      refreshDioProvider.overrideWithValue(refreshDio),
      imClientProvider.overrideWithValue(fakeIm),
      pushServiceProvider.overrideWithValue(fakePush),
      pushDeeplinkHandlerProvider.overrideWithValue(opened.add),
      heartbeatIntervalProvider.overrideWithValue(null),
      presenceRefreshIntervalProvider.overrideWithValue(null),
    ]);
    addTearDown(container.dispose);
  }

  Future<void> login() async {
    SharedPreferences.setMockInitialValues(
        {'auth.access': 'a', 'auth.refresh': 'r', 'auth.user_id': '1'});
    adapter.routes['POST /auth/token/refresh'] =
        (options) => ok({'access': 'a2', 'refresh': 'r2'});
    await container.read(sessionProvider.notifier).bootstrap();
  }

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    adapter = ScriptedAdapter({});
    fakeIm = FakeImClient();
    fakePush = FakePushService();
    opened = [];
    addTearDown(fakeIm.dispose);
  });

  test('登录后启动推送并上报 registration_id', () async {
    adapter.routes['POST /push/devices'] =
        (options) => ok({'registration_id': 'rid-test', 'platform': 'android'});
    buildContainer();
    await login();
    container.read(pushControllerProvider);
    await pumpEventQueue();

    expect(fakePush.startCalls, 1);
    final register = adapter.log
        .where((r) => r.method == 'POST' && r.path == '/push/devices')
        .toList();
    expect(register, hasLength(1));
    expect((register.single.data as Map)['registration_id'], 'rid-test');
  });

  test('登出时解绑并停止推送', () async {
    adapter.routes['POST /push/devices'] =
        (options) => ok({'registration_id': 'rid-test', 'platform': 'android'});
    adapter.routes['DELETE /push/devices/rid-test'] = (options) => ok({}, status: 204);
    buildContainer();
    await login();
    container.read(pushControllerProvider);
    await pumpEventQueue();

    await container.read(sessionProvider.notifier).logout();
    await pumpEventQueue();

    expect(fakePush.stopCalls, 1);
    expect(adapter.log.any((r) => r.method == 'DELETE' && r.path == '/push/devices/rid-test'),
        isTrue);
  });

  test('重新登录后再次启动推送', () async {
    adapter.routes['POST /push/devices'] =
        (options) => ok({'registration_id': 'rid-test', 'platform': 'android'});
    adapter.routes['DELETE /push/devices/rid-test'] = (options) => ok({}, status: 204);
    adapter.routes['POST /auth/sms/verify'] = (options) => ok({
          'access': 'a3',
          'refresh': 'r3',
          'is_new_user': false,
          'user_id': 1,
        });
    buildContainer();
    await login();
    container.read(pushControllerProvider);
    await pumpEventQueue();
    expect(fakePush.startCalls, 1);

    await container.read(sessionProvider.notifier).logout();
    await pumpEventQueue();
    await container.read(sessionProvider.notifier).login('13800138000', '123456');
    await pumpEventQueue();

    expect(fakePush.startCalls, 2);
    final registers = adapter.log
        .where((r) => r.method == 'POST' && r.path == '/push/devices')
        .toList();
    expect(registers, hasLength(2));
  });

  test('registration_id 为空时不上报', () async {
    fakePush = FakePushService(registrationIdValue: null);
    buildContainer();
    await login();
    container.read(pushControllerProvider);
    await pumpEventQueue();

    expect(adapter.log.any((r) => r.path == '/push/devices'), isFalse);
  });

  test('点击通知交给 deeplink 处理器', () async {
    adapter.routes['POST /push/devices'] =
        (options) => ok({'registration_id': 'rid-test', 'platform': 'android'});
    buildContainer();
    await login();
    container.read(pushControllerProvider);
    await pumpEventQueue();

    fakePush.tap('/likes');
    await pumpEventQueue();

    expect(opened, ['/likes']);
  });
}
