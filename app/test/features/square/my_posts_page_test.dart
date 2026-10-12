import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/harness.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

const _loggedIn = {'auth.access': 'a', 'auth.refresh': 'r', 'auth.user_id': 7};

void main() {
  testWidgets('从「我的」进我的动态,删除后行消失', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson(nickname: '小明')),
      'GET /posts': (options) => ok(pageJson([])),
      'GET /posts/mine': (options) => ok(pageJson([
            postJson(id: 7, authorId: 7, nickname: '小明', text: '我发的'),
          ])),
      'DELETE /posts/7': (options) => ok({}, status: 204),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await pumpFrames(tester); // 广场空态涟漪在 IndexedStack 隐藏页一直跑,禁 settle
    await tester.tap(navTab('我的'));
    await pumpFrames(tester);

    await tester.tap(find.byKey(const Key('my.row.posts')));
    await tester.pumpAndSettle();
    expect(find.text('我发的'), findsOneWidget);

    await tester.tap(find.byKey(const Key('post.more.7')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('post.menu.delete')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('post.delete.confirm')));
    await tester.pumpAndSettle();
    await tester.pump(const Duration(seconds: 3)); // AppToast「已删除」Timer 收尾

    expect(adapter.log.where((r) => r.method == 'DELETE' && r.path == '/posts/7'),
        hasLength(1));
    expect(find.text('我发的'), findsNothing);
    await drainToast(tester); // 删除成功弹 AppToast「已删除」
  });

  testWidgets('顶栏:标题与返回键存在', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson(nickname: '小明')),
      'GET /posts': (options) => ok(pageJson([])),
      'GET /posts/mine': (options) => ok(pageJson([
            postJson(id: 7, authorId: 7, nickname: '小明', text: '我发的'),
          ])),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await pumpFrames(tester); // 广场空态涟漪在隐藏页一直跑
    await tester.tap(navTab('我的'));
    await pumpFrames(tester);
    await tester.tap(find.byKey(const Key('my.row.posts')));
    await tester.pumpAndSettle();

    expect(find.text('我的动态'), findsOneWidget);
    expect(find.byKey(const Key('myPosts.back')), findsOneWidget);
  });

  testWidgets('空列表:提示 + 去发布按钮进发布页', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson(nickname: '小明')),
      'GET /posts': (options) => ok(pageJson([])),
      'GET /posts/mine': (options) => ok(pageJson([])),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await pumpFrames(tester); // 广场空态涟漪在 IndexedStack 隐藏页一直跑,禁 settle
    await tester.tap(navTab('我的'));
    await pumpFrames(tester);

    await tester.tap(find.byKey(const Key('my.row.posts')));
    await tester.pumpAndSettle();
    expect(find.text('还没发过动态'), findsOneWidget);

    await tester.tap(find.byKey(const Key('myPosts.compose')));
    await tester.pumpAndSettle();
    expect(find.text('发布动态'), findsOneWidget);
  });
}
