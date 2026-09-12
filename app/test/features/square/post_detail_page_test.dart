import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/features/square/post_detail_page.dart';

import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

Future<void> pumpDetail(WidgetTester tester, ScriptedAdapter adapter,
    {required int postId}) async {
  SharedPreferences.setMockInitialValues({});
  final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
  final refreshDio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))
    ..httpClientAdapter = adapter;
  final navigatorKey = GlobalKey<NavigatorState>();
  await tester.pumpWidget(ProviderScope(
    overrides: [
      baseDioProvider.overrideWithValue(dio),
      refreshDioProvider.overrideWithValue(refreshDio),
    ],
    child: MaterialApp(navigatorKey: navigatorKey, home: const Scaffold()),
  ));
  navigatorKey.currentState!
      .push(MaterialPageRoute(builder: (_) => PostDetailPage(postId: postId)));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('渲染动态与评论,发送后清空并刷新', (tester) async {
    final adapter = ScriptedAdapter({
      'GET /posts/1': (options) =>
          ok(postJson(id: 1, nickname: 'Alice', text: '正文', commentCount: 1)),
      'GET /posts/1/comments': (options) =>
          ok(pageJson([commentJson(id: 5, nickname: 'Bob', text: '好漂亮')])),
      'POST /posts/1/comments': (options) =>
          ok(commentJson(id: 6, nickname: '我', text: '谢谢'), status: 201),
    });
    await pumpDetail(tester, adapter, postId: 1);
    await tester.pumpAndSettle();

    expect(find.text('正文'), findsOneWidget);
    expect(find.text('好漂亮'), findsOneWidget);

    await tester.enterText(find.byKey(const Key('post.comment.input')), '谢谢');
    await tester.tap(find.byKey(const Key('post.comment.send')));
    await tester.pumpAndSettle();
    expect(adapter.log.where((r) => r.method == 'POST' && r.path == '/posts/1/comments'),
        hasLength(1));
    expect(
        tester
            .widget<TextField>(find.byKey(const Key('post.comment.input')))
            .controller!
            .text,
        '');
  });

  testWidgets('动态不存在 → 显示错误态', (tester) async {
    final adapter = ScriptedAdapter({
      'GET /posts/404': (options) => jsonError(404, '动态不存在'),
    });
    await pumpDetail(tester, adapter, postId: 404);
    await tester.pumpAndSettle();
    expect(find.text('动态不存在'), findsOneWidget);
  });
}
