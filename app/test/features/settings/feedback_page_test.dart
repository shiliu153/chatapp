import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/core/widgets/app_button.dart';
import 'package:chatapp_app/features/settings/feedback_page.dart';

import '../../support/harness.dart';
import '../../support/scripted_adapter.dart';

void main() {
  late ScriptedAdapter adapter;

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    adapter = ScriptedAdapter({});
  });

  Future<void> pumpPage(WidgetTester tester) async {
    final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))
      ..httpClientAdapter = adapter;
    final container = ProviderContainer(overrides: [
      baseDioProvider.overrideWithValue(dio),
      refreshDioProvider.overrideWithValue(dio),
    ]);
    addTearDown(container.dispose);
    await tester.pumpWidget(UncontrolledProviderScope(
      container: container,
      child: const MaterialApp(home: FeedbackPage()),
    ));
    await tester.pumpAndSettle();
  }

  testWidgets('内容不足 10 字时提交按钮禁用', (tester) async {
    await pumpPage(tester);

    final button = tester.widget<AppButton>(find.byKey(const Key('feedback.submit')));
    expect(button.onPressed, isNull);

    await tester.enterText(find.byKey(const Key('feedback.content')), '太短了');
    await tester.pumpAndSettle();

    final stillDisabled =
        tester.widget<AppButton>(find.byKey(const Key('feedback.submit')));
    expect(stillDisabled.onPressed, isNull);
  });

  testWidgets('选择类型并提交,成功后弹 Toast', (tester) async {
    adapter.routes['POST /feedback'] = (options) => ok({'id': 1}, status: 201);
    await pumpPage(tester);

    await tester.tap(find.text('问题反馈'));
    await tester.pumpAndSettle();
    await tester.enterText(
        find.byKey(const Key('feedback.content')), '消息偶尔重复出现两次');
    await tester.enterText(find.byKey(const Key('feedback.contact')), 'a@b.com');
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('feedback.submit')));
    await tester.pumpAndSettle();

    expect(find.text('反馈已提交,谢谢你'), findsOneWidget);
    final request = adapter.log.single;
    expect(request.path, '/feedback');
    expect(request.data, {
      'type': 'bug',
      'content': '消息偶尔重复出现两次',
      'contact': 'a@b.com',
    });

    await drainToast(tester);
  });

  testWidgets('提交失败保留输入并弹后端文案', (tester) async {
    adapter.routes['POST /feedback'] =
        (options) => jsonError(429, '操作太快了,休息一下吧');
    await pumpPage(tester);

    await tester.enterText(
        find.byKey(const Key('feedback.content')), '消息偶尔重复出现两次');
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('feedback.submit')));
    await tester.pumpAndSettle();

    expect(find.text('操作太快了,休息一下吧'), findsOneWidget);
    expect(find.text('消息偶尔重复出现两次'), findsOneWidget);

    await drainToast(tester);
  });
}

