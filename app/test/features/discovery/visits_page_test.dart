import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/features/discovery/visits_page.dart';

import '../../support/harness.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

void main() {
  late ScriptedAdapter adapter;

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    adapter = ScriptedAdapter({});
  });

  Future<void> pumpPage(WidgetTester tester) async {
    final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
    final container = ProviderContainer(overrides: [
      baseDioProvider.overrideWithValue(dio),
      refreshDioProvider.overrideWithValue(dio),
    ]);
    addTearDown(container.dispose);
    await tester.pumpWidget(UncontrolledProviderScope(
      container: container,
      child: const MaterialApp(home: VisitsPage()),
    ));
    await pumpFrames(tester); // 骨架/空态涟漪都是无限动画,不能 pumpAndSettle
  }

  testWidgets('空态', (tester) async {
    adapter.routes['GET /discovery/visits'] = (options) => ok(pageJson([]));
    await pumpPage(tester);
    expect(find.byKey(const Key('visits.empty')), findsOneWidget);
    expect(find.text('还没有人看过你'), findsOneWidget);
  });

  testWidgets('列表渲染昵称/年龄/城市/访问时间', (tester) async {
    adapter.routes['GET /discovery/visits'] = (options) => ok(pageJson([
          visitJson(userId: 9, nickname: '小红', tags: [tagJson(1, '旅行')]),
        ]));
    await pumpPage(tester);
    expect(find.text('小红'), findsOneWidget);
    expect(find.textContaining('25 岁'), findsOneWidget);
    expect(find.textContaining('旅行'), findsOneWidget);
    expect(find.byKey(const Key('visits.accept.9')), findsOneWidget);
  });

  testWidgets('点「喜欢」→ 行移除并弹配对动效', (tester) async {
    adapter.routes['GET /discovery/visits'] = (options) => ok(pageJson([
          visitJson(userId: 9, nickname: '小红'),
          visitJson(userId: 10, nickname: '小刚'),
        ]));
    adapter.routes['GET /users/me'] = (options) => ok(profileJson());
    adapter.routes['POST /discovery/swipe'] = (options) => ok({'matched': true});
    await pumpPage(tester);

    await tester.tap(find.byKey(const Key('visits.accept.9')));
    await tester.pumpAndSettle();

    expect(find.text('你们已互相喜欢'), findsOneWidget);
    expect(find.byKey(const Key('visits.row.9')), findsNothing);
    final request = adapter.log.lastWhere((item) => item.method == 'POST');
    expect(request.data, {'target_user_id': 9, 'action': 'like'});
  });

  testWidgets('加载失败 → 错误态,重试成功', (tester) async {
    adapter.routes['GET /discovery/visits'] = offline;
    await pumpPage(tester);
    expect(find.byKey(const Key('visits.retry')), findsOneWidget);

    adapter.routes['GET /discovery/visits'] =
        (options) => ok(pageJson([visitJson(userId: 9, nickname: '小红')]));
    await tester.tap(find.byKey(const Key('visits.retry')));
    await pumpFrames(tester);
    expect(find.text('小红'), findsOneWidget);
  });
}
