import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/features/presence/presence_controller.dart';

import '../../support/scripted_adapter.dart';

void main() {
  late ScriptedAdapter adapter;

  ProviderContainer makeContainer({Duration? interval}) {
    final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
    final container = ProviderContainer(overrides: [
      baseDioProvider.overrideWithValue(dio),
      presenceRefreshIntervalProvider.overrideWithValue(interval),
    ]);
    // autoDispose provider 没有监听者会被立刻回收;测试里挂一个空监听保持存活
    container.listen(presenceProvider, (_, _) {}, fireImmediately: true);
    addTearDown(container.dispose);
    return container;
  }

  int presenceRequests() => adapter.log.where((r) => r.path == '/presence').length;

  /// 轮询等条件成立(最多 ~1s):拉取走真实 dio,固定 sleep 在高负载下会 flake。
  Future<void> waitFor(bool Function() condition) async {
    for (var i = 0; i < 100 && !condition(); i++) {
      await Future<void>.delayed(const Duration(milliseconds: 10));
    }
    expect(condition(), isTrue, reason: '等待超时:条件未在 1s 内成立');
  }

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    adapter = ScriptedAdapter({
      'GET /presence': (options) => ok({
            'results': [
              {'user_id': 1, 'online': true, 'last_active_at': '2026-09-13T14:30:00+08:00'},
            ],
          }),
    });
  });

  test('多个页面登记的人合并去重成一次请求', () async {
    final container = makeContainer();
    final notifier = container.read(presenceProvider.notifier);

    notifier.track('chats', [1, 2]);
    notifier.track('chat:u3', [2, 3]);
    await waitFor(() => container.read(presenceProvider).containsKey(1));   // 等合并后的拉取跑完

    final requests = adapter.log.where((r) => r.path == '/presence').toList();
    expect(requests, hasLength(1));
    expect((requests.single.queryParameters['user_ids'] as String).split(','),
        containsAll(['1', '2', '3']));
    expect(container.read(presenceProvider)[1]!.online, isTrue);
  });

  test('track 同集合重复调用不重复发请求', () async {
    final container = makeContainer();
    final notifier = container.read(presenceProvider.notifier);
    notifier.track('chats', [1]);
    await waitFor(() => presenceRequests() >= 1);
    expect(presenceRequests(), 1);

    notifier.track('chats', [1]);   // 内容没变 → 无操作
    await Future<void>.delayed(const Duration(milliseconds: 50));
    expect(presenceRequests(), 1);
  });

  test('拉取失败保留旧值', () async {
    final container = makeContainer();
    final notifier = container.read(presenceProvider.notifier);
    notifier.track('chats', [1]);
    await waitFor(() => container.read(presenceProvider).containsKey(1));

    adapter.routes['GET /presence'] = offline;
    await notifier.refresh();   // 失败
    expect(container.read(presenceProvider)[1], isNotNull);   // 旧值还在
  });

  test('接口省略的人会被清掉(拉黑后不再显示)', () async {
    final container = makeContainer();
    final notifier = container.read(presenceProvider.notifier);
    notifier.track('chats', [1]);
    await waitFor(() => container.read(presenceProvider).containsKey(1));

    adapter.routes['GET /presence'] = (options) => ok({'results': []});
    await notifier.refresh();
    expect(container.read(presenceProvider).containsKey(1), isFalse);
  });

  test('周期定时器按间隔自动刷新', () async {
    final container = makeContainer(interval: const Duration(milliseconds: 30));
    container.read(presenceProvider.notifier).track('chats', [1]);
    await waitFor(() => presenceRequests() >= 3);   // 立即一次 + 周期 ≥2 次
  });

  test('超过 100 个 id 拆片请求并合并结果', () async {
    adapter.routes['GET /presence'] = (options) {
      final ids = (options.queryParameters['user_ids'] as String).split(',');
      return ok({
        'results': [
          for (final id in ids)
            {'user_id': int.parse(id), 'online': true, 'last_active_at': null},
        ],
      });
    };
    final container = makeContainer();
    final ids = List<int>.generate(150, (i) => i + 1);

    container.read(presenceProvider.notifier).track('square', ids);
    await waitFor(() => container.read(presenceProvider).length == 150);

    final requests = adapter.log.where((r) => r.path == '/presence').toList();
    expect(requests, hasLength(2));
    expect((requests[0].queryParameters['user_ids'] as String).split(','),
        hasLength(100));
    expect((requests[1].queryParameters['user_ids'] as String).split(','),
        hasLength(50));
  });

  test('分片中途失败:整轮放弃,保留旧值', () async {
    final container = makeContainer();
    final notifier = container.read(presenceProvider.notifier);
    adapter.routes['GET /presence'] = (options) => ok({
          'results': [
            {'user_id': 1, 'online': true, 'last_active_at': null},
          ],
        });
    notifier.track('chats', [1]);
    await waitFor(() => container.read(presenceProvider).containsKey(1));

    var calls = 0;
    adapter.routes['GET /presence'] = (options) {
      calls += 1;
      if (calls == 1) return ok({'results': []});   // 第 1 片成功
      return offline(options);                       // 第 2 片失败
    };
    notifier.track('square', List<int>.generate(150, (i) => i + 2));
    await waitFor(() => calls >= 2);
    await Future<void>.delayed(const Duration(milliseconds: 50));

    final state = container.read(presenceProvider);
    expect(state.containsKey(1), isTrue);    // 旧值还在
    expect(state.containsKey(2), isFalse);   // 没有分片结果半更新进去
  });
}
