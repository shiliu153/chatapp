import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/features/square/square_controller.dart';

import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

/// 广场动态流的分页协议:游标(`?before=`),不再是 offset(backlog D-1)。
void main() {
  late ScriptedAdapter adapter;
  late ProviderContainer container;

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    adapter = ScriptedAdapter({});
    final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))
      ..httpClientAdapter = adapter;
    container = ProviderContainer(overrides: [
      baseDioProvider.overrideWithValue(dio),
      refreshDioProvider.overrideWithValue(dio),
    ]);
    addTearDown(container.dispose);
  });

  test('首屏不带游标,也不带 offset', () async {
    adapter.routes['GET /posts'] = (options) =>
        ok(cursorPageJson([postJson(id: 1)], hasMore: true, cursor: 'page-2'));

    final posts = await container.read(squareProvider.future);

    expect(posts.map((post) => post.id), [1]);
    expect(adapter.log.last.queryParameters, {'limit': 20});
  });

  test('loadMore 把 next_cursor 放回 before,并去重追加', () async {
    var calls = 0;
    adapter.routes['GET /posts'] = (options) {
      calls += 1;
      return calls == 1
          ? ok(cursorPageJson([postJson(id: 1)],
              hasMore: true, count: 2, cursor: 'page-2'))
          : ok(cursorPageJson([postJson(id: 1), postJson(id: 2)], count: 2));
    };
    // autoDispose 的 provider 必须先挂一个监听,否则 read 完就被回收
    final subscription =
        container.listen(squareProvider, (_, _) {}, fireImmediately: true);
    addTearDown(subscription.close);
    await container.read(squareProvider.future);

    await container.read(squareProvider.notifier).loadMore();

    final posts = container.read(squareProvider).value!;
    expect(posts.map((post) => post.id), [1, 2]);   // 重复的 id 1 被去掉
    expect(adapter.log.last.queryParameters, {'limit': 20, 'before': 'page-2'});
  });
}
