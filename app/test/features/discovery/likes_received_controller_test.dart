import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/api_exception.dart';
import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/features/discovery/likes_received_controller.dart';

import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

void main() {
  late ScriptedAdapter adapter;

  ProviderContainer makeContainer() {
    final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
    final refreshDio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
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
    adapter.routes['GET /discovery/likes'] = (options) =>
        ok(pageJson([likeReceivedJson(userId: 9), likeReceivedJson(userId: 10)]));
    final container = makeContainer();
    addTearDown(container.dispose);

    final state = await container.read(likesReceivedProvider.future);

    expect(state.items.map((item) => item.candidate.userId), [9, 10]);
    expect(state.count, 2);
    expect(state.hasMore, isFalse);
    expect(adapter.log.last.queryParameters, {'limit': 20, 'offset': 0});
  });

  test('accept → like 请求、移除该行、计数 -1、返回候选人', () async {
    adapter.routes['GET /discovery/likes'] = (options) =>
        ok(pageJson([likeReceivedJson(userId: 9), likeReceivedJson(userId: 10)]));
    adapter.routes['POST /discovery/swipe'] = (options) => ok({'matched': true});
    final container = makeContainer();
    addTearDown(container.dispose);
    final state = await container.read(likesReceivedProvider.future);

    final matched = await container
        .read(likesReceivedProvider.notifier)
        .accept(state.items.first);

    expect(matched?.userId, 9);
    final after = container.read(likesReceivedProvider).value!;
    expect(after.items.map((item) => item.candidate.userId), [10]);
    expect(after.count, 1);
    final request = adapter.log.lastWhere((item) => item.method == 'POST');
    expect(request.data, {'target_user_id': 9, 'action': 'like'});
  });

  test('accept 失败 → 行保留、抛 ApiException、重新拉取', () async {
    adapter.routes['GET /discovery/likes'] = (options) =>
        ok(pageJson([likeReceivedJson(userId: 9)]));
    adapter.routes['POST /discovery/swipe'] =
        (options) => jsonError(429, '操作太快了,休息一下吧');
    final container = makeContainer();
    addTearDown(container.dispose);
    final state = await container.read(likesReceivedProvider.future);

    await expectLater(
      container.read(likesReceivedProvider.notifier).accept(state.items.first),
      throwsA(isA<ApiException>()),
    );

    final after = container.read(likesReceivedProvider).value!;
    expect(after.items.map((item) => item.candidate.userId), [9]);
    expect(after.busyUserId, isNull);
  });

  test('loadMore 追加下一页', () async {
    var calls = 0;
    adapter.routes['GET /discovery/likes'] = (options) {
      calls += 1;
      return calls == 1
          ? ok({...pageJson([likeReceivedJson(userId: 9)]), 'count': 2})
          : ok({...pageJson([likeReceivedJson(userId: 10)]), 'count': 2});
    };
    final container = makeContainer();
    addTearDown(container.dispose);
    await container.read(likesReceivedProvider.future);

    await container.read(likesReceivedProvider.notifier).loadMore();

    final after = container.read(likesReceivedProvider).value!;
    expect(after.items.map((item) => item.candidate.userId), [9, 10]);
    expect(adapter.log.last.queryParameters, {'limit': 20, 'offset': 1});
  });
}
