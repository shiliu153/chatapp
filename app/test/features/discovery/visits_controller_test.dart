import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/features/discovery/visits_controller.dart';

import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

void main() {
  late ScriptedAdapter adapter;
  late ProviderContainer container;

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    adapter = ScriptedAdapter({});
    final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
    container = ProviderContainer(overrides: [
      baseDioProvider.overrideWithValue(dio),
      refreshDioProvider.overrideWithValue(dio),
    ]);
    addTearDown(container.dispose);
  });

  test('拉取访客列表与总数', () async {
    adapter.routes['GET /discovery/visits'] = (options) => ok(pageJson([
          visitJson(userId: 9, nickname: '小红'),
        ]));
    final state = await container.read(visitsProvider.future);
    expect(state.items.single.candidate.nickname, '小红');
    expect(state.count, 1);
    expect(state.hasMore, isFalse);
  });

  test('回喜欢 → 行移除、计数 -1、返回候选人', () async {
    adapter.routes['GET /discovery/visits'] = (options) => ok(pageJson([
          visitJson(userId: 9, nickname: '小红'),
          visitJson(userId: 10, nickname: '小刚'),
        ]));
    adapter.routes['POST /discovery/swipe'] = (options) => ok({'matched': true});
    await container.read(visitsProvider.future);

    final matched = await container.read(visitsProvider.notifier).accept(
          container.read(visitsProvider).value!.items.first,
        );

    expect(matched?.candidate.userId, 9);
    final state = container.read(visitsProvider).value!;
    expect(state.items.single.candidate.userId, 10);
    expect(state.count, 1);
    final request = adapter.log.lastWhere((item) => item.method == 'POST');
    expect(request.data, {'target_user_id': 9, 'action': 'like'});
  });

  test('角标只查数量', () async {
    adapter.routes['GET /discovery/visits/count'] = (options) => ok({'count': 7});
    expect(await container.read(visitsCountProvider.future), 7);
  });
}
