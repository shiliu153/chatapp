import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/features/settings/blocked_users_page.dart';

import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

void main() {
  late ScriptedAdapter adapter;

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    adapter = ScriptedAdapter({});
  });

  Future<void> pumpBlocked(WidgetTester tester) async {
    final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
    final container = ProviderContainer(overrides: [
      baseDioProvider.overrideWithValue(dio),
      refreshDioProvider.overrideWithValue(dio),
    ]);
    addTearDown(container.dispose);
    await tester.pumpWidget(UncontrolledProviderScope(
      container: container,
      child: const MaterialApp(home: BlockedUsersPage()),
    ));
    await tester.pumpAndSettle();
  }

  testWidgets('空态', (tester) async {
    adapter.routes['GET /blocks'] = (options) => ok(pageJson([]));
    await pumpBlocked(tester);
    expect(find.text('还没有拉黑任何人'), findsOneWidget);
  });

  testWidgets('列表 + 解除拉黑', (tester) async {
    // 可变列表:解除后 reload 能拿到空列表,和真实后端行为一致
    var blocked = [blockedUserJson(userId: 9, nickname: '小红')];
    adapter.routes['GET /blocks'] = (options) => ok(pageJson(blocked));
    adapter.routes['DELETE /blocks/9'] = (options) {
      blocked = [];
      return ok({}, status: 204);
    };
    await pumpBlocked(tester);

    expect(find.text('小红'), findsOneWidget);
    await tester.tap(find.byKey(const Key('unblock.9')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('unblock.confirm')));
    await tester.pumpAndSettle();

    // reload 的 GET 会排在 DELETE 后面,别用 last(项目老坑)
    final delete = adapter.log.lastWhere((r) => r.method == 'DELETE');
    expect(delete.path, '/blocks/9');
    expect(find.text('还没有拉黑任何人'), findsOneWidget);   // reload 后空了
    expect(find.text('已解除拉黑'), findsOneWidget);
  });
}
