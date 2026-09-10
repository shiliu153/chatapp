import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/api_exception.dart';
import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/features/discovery/discovery_controller.dart';

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

  test('build 拉第一车候选', () async {
    adapter.routes['GET /discovery/candidates'] =
        (options) => ok([candidateJson(userId: 9), candidateJson(userId: 10)]);
    final container = makeContainer();
    addTearDown(container.dispose);

    final candidates = await container.read(discoveryProvider.future);

    expect(candidates.map((item) => item.userId), [9, 10]);
    expect(adapter.log.last.queryParameters, {'limit': 10});
  });

  test('decide like → 提交后端并移除卡;matched 原样返回', () async {
    var calls = 0;
    adapter.routes['GET /discovery/candidates'] = (options) {
      calls += 1;
      return calls == 1
          ? ok([candidateJson(userId: 9), candidateJson(userId: 10)])
          : ok([]);
    };
    adapter.routes['POST /discovery/swipe'] = (options) => ok({'matched': true});
    final container = makeContainer();
    addTearDown(container.dispose);
    final candidates = await container.read(discoveryProvider.future);

    final matched = await container
        .read(discoveryProvider.notifier)
        .decide(candidates.first, like: true);

    expect(matched, isTrue);
    expect(container.read(discoveryProvider).value!.map((item) => item.userId), [10]);
    final request = adapter.log.lastWhere((item) => item.method == 'POST');
    expect(request.data, {'target_user_id': 9, 'action': 'like'});
  });

  test('decide 失败 → 卡放回队首并抛 ApiException', () async {
    adapter.routes['GET /discovery/candidates'] =
        (options) => ok([candidateJson(userId: 9)]);
    adapter.routes['POST /discovery/swipe'] =
        (options) => jsonError(429, '操作太快了,休息一下吧');
    final container = makeContainer();
    addTearDown(container.dispose);
    final candidates = await container.read(discoveryProvider.future);

    await expectLater(
      container.read(discoveryProvider.notifier).decide(candidates.first, like: true),
      throwsA(isA<ApiException>()),
    );

    expect(container.read(discoveryProvider).value!.map((item) => item.userId), [9]);
  });

  test('滑到剩 3 张自动续拉', () async {
    var calls = 0;
    adapter.routes['GET /discovery/candidates'] = (options) {
      calls += 1;
      return calls == 1
          ? ok(List.generate(4, (index) => candidateJson(userId: 9 + index)))
          : ok([candidateJson(userId: 20)]);
    };
    adapter.routes['POST /discovery/swipe'] = (options) => ok({'matched': false});
    final container = makeContainer();
    addTearDown(container.dispose);
    final candidates = await container.read(discoveryProvider.future);

    await container.read(discoveryProvider.notifier).decide(candidates.first, like: false);
    await pumpEventQueue(); // 续拉是 fire-and-forget,等它跑完

    expect(calls, 2);
    expect(container.read(discoveryProvider).value!.map((item) => item.userId),
        [10, 11, 12, 20]);
  });

  test('续拉去重:后端把卡组里已有的人又发回来时,不出现重复卡', () async {
    var calls = 0;
    adapter.routes['GET /discovery/candidates'] = (options) {
      calls += 1;
      return calls == 1
          ? ok([candidateJson(userId: 9), candidateJson(userId: 10)])
          // 后端只排除「已划过」的:10 还在卡组里没划,会被再发一次
          : ok([candidateJson(userId: 10), candidateJson(userId: 20)]);
    };
    adapter.routes['POST /discovery/swipe'] = (options) => ok({'matched': false});
    final container = makeContainer();
    addTearDown(container.dispose);
    final candidates = await container.read(discoveryProvider.future);

    await container.read(discoveryProvider.notifier).decide(candidates.first, like: true);
    await pumpEventQueue();

    expect(container.read(discoveryProvider).value!.map((item) => item.userId), [10, 20]);
  });

  test('卡还多的时候不续拉', () async {
    var calls = 0;
    adapter.routes['GET /discovery/candidates'] = (options) {
      calls += 1;
      return ok(List.generate(10, (index) => candidateJson(userId: 9 + index)));
    };
    adapter.routes['POST /discovery/swipe'] = (options) => ok({'matched': false});
    final container = makeContainer();
    addTearDown(container.dispose);
    final candidates = await container.read(discoveryProvider.future);

    await container.read(discoveryProvider.notifier).decide(candidates.first, like: false);
    await pumpEventQueue();

    expect(calls, 1);
    expect(container.read(discoveryProvider).value, hasLength(9));
  });
}
