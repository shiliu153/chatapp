import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/features/profile/user_profile_page.dart';
import 'package:chatapp_app/features/square/post_detail_page.dart';

import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

Future<void> pumpDetail(WidgetTester tester, ScriptedAdapter adapter,
    {required int postId}) async {
  SharedPreferences.setMockInitialValues({});
  final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
  final router = GoRouter(
    initialLocation: '/posts/$postId',
    routes: [
      GoRoute(
        path: '/posts/:id',
        builder: (context, state) =>
            PostDetailPage(postId: int.parse(state.pathParameters['id']!)),
      ),
      GoRoute(
        path: '/users/:id',
        builder: (context, state) =>
            UserProfilePage(userId: int.parse(state.pathParameters['id']!)),
      ),
    ],
  );
  await tester.pumpWidget(ProviderScope(
    overrides: [
      baseDioProvider.overrideWithValue(dio),
      refreshDioProvider.overrideWithValue(dio),
    ],
    child: MaterialApp.router(routerConfig: router),
  ));
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
      'GET /presence': (options) => ok({'results': []}),
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

  testWidgets('点评论者头像打开公开资料页', (tester) async {
    final adapter = ScriptedAdapter({
      'GET /posts/1': (options) =>
          ok(postJson(id: 1, authorId: 9, nickname: 'Alice', text: '正文')),
      'GET /posts/1/comments': (options) =>
          ok(pageJson([commentJson(id: 5, authorId: 11, nickname: 'Bob', text: '好漂亮')])),
      'GET /users/11': (options) => ok(publicProfileJson(userId: 11, nickname: 'Bob')),
      'GET /presence': (options) => ok({'results': []}),
    });
    await pumpDetail(tester, adapter, postId: 1);
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('post.comment.avatar.5')));
    await tester.pumpAndSettle();

    expect(find.text('详细资料'), findsOneWidget);
    expect(find.text('ID:u11'), findsOneWidget);
  });

  testWidgets('点评论者昵称打开公开资料页', (tester) async {
    final adapter = ScriptedAdapter({
      'GET /posts/1': (options) =>
          ok(postJson(id: 1, authorId: 9, nickname: 'Alice', text: '正文')),
      'GET /posts/1/comments': (options) =>
          ok(pageJson([commentJson(id: 5, authorId: 11, nickname: 'Bob', text: '好漂亮')])),
      'GET /users/11': (options) => ok(publicProfileJson(userId: 11, nickname: 'Bob')),
      'GET /presence': (options) => ok({'results': []}),
    });
    await pumpDetail(tester, adapter, postId: 1);
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('post.comment.nickname.5')));
    await tester.pumpAndSettle();

    expect(find.text('详细资料'), findsOneWidget);
  });

  testWidgets('点自己的评论不打开资料页', (tester) async {
    final adapter = ScriptedAdapter({
      'GET /users/me': (options) => ok(profileJson(nickname: '小明', userId: 7)),
      'GET /posts/1': (options) =>
          ok(postJson(id: 1, authorId: 9, nickname: 'Alice', text: '正文')),
      'GET /posts/1/comments': (options) =>
          ok(pageJson([commentJson(id: 5, authorId: 7, nickname: '小明', text: '我评的')])),
      'GET /presence': (options) => ok({'results': []}),
    });
    await pumpDetail(tester, adapter, postId: 1);
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('post.comment.avatar.5')));
    await tester.pumpAndSettle();

    expect(find.text('详细资料'), findsNothing);
  });
}
