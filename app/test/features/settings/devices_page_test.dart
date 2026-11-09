import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/client_header.dart';
import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/features/settings/devices_page.dart';

import '../../support/harness.dart';
import '../../support/heart_theme.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

void main() {
  late ScriptedAdapter adapter;

  setUp(() {
    // apiClientProvider 会挂 AuthInterceptor,它读凭证要走 SharedPreferences
    SharedPreferences.setMockInitialValues({});
    adapter = ScriptedAdapter({});
  });

  Future<void> pumpDevices(WidgetTester tester) async {
    // 与生产同一条路径:端类型头由 ClientHeaderInterceptor 统一补,页面不手写
    final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))
      ..httpClientAdapter = adapter
      ..interceptors.add(const ClientHeaderInterceptor());
    final container = ProviderContainer(overrides: [
      baseDioProvider.overrideWithValue(dio),
      refreshDioProvider.overrideWithValue(dio),
    ]);
    addTearDown(container.dispose);
    await tester.pumpWidget(UncontrolledProviderScope(
      container: container,
      child: MaterialApp(theme: heartTheme, home: const DevicesPage()),
    ));
    await tester.pumpAndSettle();
  }

  testWidgets('两行渲染:当前端标「本机」且无下线按钮,另一行有', (tester) async {
    adapter.routes['GET /devices'] = (options) => ok({
          'results': [
            deviceJson(
              current: true,
              lastActiveAt: DateTime.now().subtract(const Duration(minutes: 5)),
            ),
            deviceJson(clientType: 'web', clientLabel: '网页端'),
          ],
        });
    await pumpDevices(tester);

    expect(find.text('App'), findsOneWidget);
    expect(find.text('网页端'), findsOneWidget);
    expect(find.textContaining('最近活跃 5 分钟前'), findsOneWidget);
    expect(find.textContaining('首次登录 2026-11-09'), findsNWidgets(2));

    // 当前端:有「本机」,没有下线按钮
    expect(find.byKey(const Key('devices.current.app')), findsOneWidget);
    expect(find.byKey(const Key('devices.logout.app')), findsNothing);
    // 另一端:可以下线
    expect(find.byKey(const Key('devices.current.web')), findsNothing);
    expect(find.byKey(const Key('devices.logout.web')), findsOneWidget);

    // 端类型上报走全局拦截器(X-Client: app),页面里没有手写头
    expect(adapter.log.first.headers[ClientHeaderInterceptor.headerName], 'app');
  });

  testWidgets('last_active_at 为 null → 显示「尚未在此端刷新过」', (tester) async {
    adapter.routes['GET /devices'] = (options) => ok({
          'results': [deviceJson(current: true)],
        });
    await pumpDevices(tester);

    expect(find.textContaining('尚未在此端刷新过'), findsOneWidget);
    expect(find.textContaining('null'), findsNothing);
  });

  testWidgets('下线另一端:二次确认 → DELETE → 该行消失 + Toast', (tester) async {
    // 可变列表:下线后 reload 拿到只剩本机的一行,与真实后端行为一致
    var devices = [
      deviceJson(current: true),
      deviceJson(clientType: 'web', clientLabel: '网页端'),
    ];
    adapter.routes['GET /devices'] = (options) => ok({'results': devices});
    adapter.routes['DELETE /devices/web'] = (options) {
      devices = [deviceJson(current: true)];
      return ok({}, status: 204);
    };
    await pumpDevices(tester);

    await tester.tap(find.byKey(const Key('devices.logout.web')));
    await tester.pumpAndSettle();
    expect(find.text('下线「网页端」?'), findsOneWidget); // 二次确认

    await tester.tap(find.byKey(const Key('devices.confirm')));
    await tester.pumpAndSettle();

    final delete = adapter.log.lastWhere((request) => request.method == 'DELETE');
    expect(delete.path, '/devices/web');
    expect(find.byKey(const Key('devices.row.web')), findsNothing);
    expect(find.byKey(const Key('devices.row.app')), findsOneWidget);
    expect(find.text('已下线「网页端」'), findsOneWidget);
    await drainToast(tester); // Toast 的 2s Timer 要推过去
  });

  testWidgets('二次确认点「取消」→ 不发请求、行还在', (tester) async {
    adapter.routes['GET /devices'] = (options) => ok({
          'results': [
            deviceJson(current: true),
            deviceJson(clientType: 'web', clientLabel: '网页端'),
          ],
        });
    await pumpDevices(tester);

    await tester.tap(find.byKey(const Key('devices.logout.web')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('取消'));
    await tester.pumpAndSettle();

    expect(adapter.log.where((request) => request.method == 'DELETE'), isEmpty);
    expect(find.byKey(const Key('devices.row.web')), findsOneWidget);
  });

  testWidgets('下线失败 → Toast 提示错误、行仍在', (tester) async {
    adapter.routes['GET /devices'] = (options) => ok({
          'results': [
            deviceJson(current: true),
            deviceJson(clientType: 'web', clientLabel: '网页端'),
          ],
        });
    adapter.routes['DELETE /devices/web'] =
        (options) => jsonError(400, '客户端类型不合法');
    await pumpDevices(tester);

    await tester.tap(find.byKey(const Key('devices.logout.web')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('devices.confirm')));
    await tester.pumpAndSettle();

    expect(find.text('客户端类型不合法'), findsOneWidget);
    expect(find.byKey(const Key('devices.row.web')), findsOneWidget);
    await drainToast(tester);
  });

  testWidgets('加载失败 → AppErrorView,devices.retry 重试成功', (tester) async {
    adapter.routes['GET /devices'] = offline;
    await pumpDevices(tester);
    expect(find.byKey(const Key('devices.retry')), findsOneWidget);

    adapter.routes['GET /devices'] = (options) => ok({
          'results': [deviceJson(current: true)],
        });
    await tester.tap(find.byKey(const Key('devices.retry')));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('devices.row.app')), findsOneWidget);
  });
}
