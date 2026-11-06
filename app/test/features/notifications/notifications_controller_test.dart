import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/api_exception.dart';
import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/features/notifications/notifications_controller.dart';

import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

void main() {
  late ScriptedAdapter adapter;

  ProviderContainer makeContainer() {
    final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
    final refreshDio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))
      ..httpClientAdapter = adapter;
    return ProviderContainer(overrides: [
      baseDioProvider.overrideWithValue(dio),
      refreshDioProvider.overrideWithValue(refreshDio),
    ]);
  }

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    adapter = ScriptedAdapter({});
  });

  test('build 拉第一页并带分页参数', () async {
    adapter.routes['GET /notifications'] = (options) => ok(cursorPageJson([
          notificationJson(id: 2),
          notificationJson(id: 1, isRead: true),
        ]));
    final container = makeContainer();
    addTearDown(container.dispose);

    final state = await container.read(notificationsProvider.future);

    expect(state.items.map((item) => item.id), [2, 1]);
    expect(state.count, 2);
    expect(state.hasMore, isFalse);
    expect(state.nextCursor, isNull);
    expect(state.hasUnread, isTrue);
    expect(adapter.log.last.queryParameters, {'limit': 20});
  });

  test('loadMore 追加下一页(带上一页的 next_cursor)', () async {
    var calls = 0;
    adapter.routes['GET /notifications'] = (options) {
      calls += 1;
      return calls == 1
          ? ok(cursorPageJson([notificationJson(id: 2)],
              hasMore: true, count: 2, cursor: 'page-2'))
          : ok(cursorPageJson([notificationJson(id: 1)], count: 2));
    };
    final container = makeContainer();
    addTearDown(container.dispose);
    await container.read(notificationsProvider.future);

    await container.read(notificationsProvider.notifier).loadMore();

    final after = container.read(notificationsProvider).value!;
    expect(after.items.map((item) => item.id), [2, 1]);
    expect(after.hasMore, isFalse);
    expect(adapter.log.last.queryParameters, {'limit': 20, 'before': 'page-2'});
  });

  test('markRead 只标单条,并刷新未读角标', () async {
    adapter.routes['GET /notifications'] = (options) => ok(cursorPageJson([
          notificationJson(id: 2),
          notificationJson(id: 1),
        ]));
    adapter.routes['POST /notifications/read'] = (options) => ok(const <String, dynamic>{}, status: 204);
    var unreadCalls = 0;
    adapter.routes['GET /notifications/unread_count'] = (options) {
      unreadCalls += 1;
      return ok({'unread': unreadCalls == 1 ? 2 : 1});
    };
    final container = makeContainer();
    addTearDown(container.dispose);
    final state = await container.read(notificationsProvider.future);
    expect(await container.read(notificationsUnreadCountProvider.future), 2);

    await container.read(notificationsProvider.notifier).markRead(state.items.first);

    final after = container.read(notificationsProvider).value!;
    expect(after.items.map((item) => item.isRead), [true, false]);
    final request = adapter.log.lastWhere((item) => item.method == 'POST');
    expect(request.path, '/notifications/read');
    expect(request.data, {
      'ids': [2],
    });
    // 角标被 invalidate:再读一次会重新请求并拿到新值
    expect(await container.read(notificationsUnreadCountProvider.future), 1);
    expect(unreadCalls, 2);
  });

  test('markRead 对已读条目不发请求', () async {
    adapter.routes['GET /notifications'] = (options) =>
        ok(cursorPageJson([notificationJson(id: 1, isRead: true)]));
    final container = makeContainer();
    addTearDown(container.dispose);
    final state = await container.read(notificationsProvider.future);

    await container.read(notificationsProvider.notifier).markRead(state.items.first);

    expect(adapter.log.where((item) => item.method == 'POST'), isEmpty);
  });

  test('markAllRead 发 all=true 并把已加载条目全标已读', () async {
    adapter.routes['GET /notifications'] = (options) => ok(cursorPageJson([
          notificationJson(id: 2),
          notificationJson(id: 1, isRead: true),
        ]));
    adapter.routes['POST /notifications/read'] = (options) => ok(const <String, dynamic>{}, status: 204);
    adapter.routes['GET /notifications/unread_count'] = (options) => ok({'unread': 0});
    final container = makeContainer();
    addTearDown(container.dispose);
    await container.read(notificationsProvider.future);

    await container.read(notificationsProvider.notifier).markAllRead();

    final after = container.read(notificationsProvider).value!;
    expect(after.items.every((item) => item.isRead), isTrue);
    expect(after.hasUnread, isFalse);
    expect(adapter.log.lastWhere((item) => item.method == 'POST').data, {'all': true});
  });

  test('markRead 失败 → 抛 ApiException,状态保持未读', () async {
    adapter.routes['GET /notifications'] = (options) =>
        ok(cursorPageJson([notificationJson(id: 2)]));
    adapter.routes['POST /notifications/read'] = (options) => jsonError(500, '服务不可用');
    final container = makeContainer();
    addTearDown(container.dispose);
    final state = await container.read(notificationsProvider.future);

    await expectLater(
      container.read(notificationsProvider.notifier).markRead(state.items.first),
      throwsA(isA<ApiException>()),
    );
    expect(container.read(notificationsProvider).value!.items.first.isRead, isFalse);
  });

  test('reload 重新拉第一页', () async {
    var calls = 0;
    adapter.routes['GET /notifications'] = (options) {
      calls += 1;
      return ok(cursorPageJson([notificationJson(id: calls)]));
    };
    final container = makeContainer();
    addTearDown(container.dispose);
    await container.read(notificationsProvider.future);

    await container.read(notificationsProvider.notifier).reload();

    final after = container.read(notificationsProvider).value!;
    expect(after.items.map((item) => item.id), [2]);
    expect(adapter.log.last.queryParameters, {'limit': 20});
  });
}
