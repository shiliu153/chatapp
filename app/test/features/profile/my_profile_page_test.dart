import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/harness.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

const _loggedIn = {'auth.access': 'a', 'auth.refresh': 'r', 'auth.user_id': 7};

void main() {
  testWidgets('行版式:ID/昵称/性别等取值渲染', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson(
          nickname: '小雨', gender: 'female', city: '杭州', tags: [tagJson(1, '运动')])),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();
    await tester.tap(navTab('我的'));
    await tester.pumpAndSettle();

    expect(find.text('u7'), findsOneWidget); // ID 行用 u{id}
    expect(find.text('小雨'), findsOneWidget);
    expect(find.text('女'), findsOneWidget);
    expect(find.byKey(const Key('my.row.id')), findsOneWidget);
    expect(find.byKey(const Key('my.row.preference')), findsOneWidget);
    expect(find.text('编辑资料'), findsNothing); // 独立入口已删
    // 纯入口行(头像/想找的人/设置)没有取值概念,不能显示「未填」
    expect(find.text('未填'), findsNothing);
  });

  testWidgets('空值显示「未填」', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson(
          nickname: '', gender: null, birthday: null, city: '', bio: '')),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();
    await tester.tap(navTab('我的'));
    await tester.pumpAndSettle();

    expect(find.text('未填'), findsWidgets);
  });

  testWidgets('点资料行 → 进编辑资料页', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
      'GET /users/tags': (options) => ok([tagJson(1, '运动')]),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();
    await tester.tap(navTab('我的'));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('my.row.city')));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('edit.nickname')), findsOneWidget);
  });
}
