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
      // id 是 profile 主键(6),账号 ID 是 7:ID 行必须显示后者
      'GET /users/me': (options) => ok(profileJson(
          id: 6,
          userId: 7,
          nickname: '小雨',
          gender: 'female',
          city: '杭州',
          tags: [tagJson(1, '运动')])),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();
    await tester.tap(navTab('我的'));
    await tester.pumpAndSettle();

    expect(find.text('ID:u7'), findsOneWidget); // 身份卡里 ID 自带前缀
    expect(find.text('u6'), findsNothing); // 不能拿 profile 主键冒充账号 ID
    expect(find.text('小雨'), findsOneWidget);
    expect(find.text('女'), findsOneWidget);
    expect(find.byKey(const Key('my.card.identity')), findsOneWidget);
    expect(find.byKey(const Key('my.row.preference')), findsOneWidget);
    expect(find.byKey(const Key('my.row.posts')), findsOneWidget);   // 我的动态入口
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

  testWidgets('资料不完整 → 完成度环 + 还差 + 去完善跳引导页', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson(
          nickname: '小雨', city: '', bio: '', missing: ['city', 'bio', 'photos'])),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    // 资料不完整时,IndexedStack 里活着的发现页会渲染 HeartRipple(无限动画),
    // 故这一整段只能用有限 pump(home_shell_test 同款处理)
    await pumpFrames(tester);
    await tester.tap(navTab('我的'));
    await pumpFrames(tester);

    expect(find.byKey(const Key('my.ring')), findsOneWidget);
    expect(find.text('3/6'), findsOneWidget); // 6 - 3 缺项
    expect(find.text('还差:城市、简介、照片'), findsOneWidget);

    await tester.tap(find.byKey(const Key('my.goOnboarding')));
    // 已离开主框架(涟漪随之销毁),这里可以 settle
    await tester.pumpAndSettle();
    expect(find.text('第 1 步 / 共 3 步'), findsOneWidget);
  });

  testWidgets('资料完整 → 不显示完成度区', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson(nickname: '小雨')),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();
    await tester.tap(navTab('我的'));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('my.ring')), findsNothing);
    expect(find.byKey(const Key('my.goOnboarding')), findsNothing);
    expect(find.textContaining('还差'), findsNothing);
  });

  testWidgets('点身份卡 → 进编辑资料页', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
      'GET /users/tags': (options) => ok([tagJson(1, '运动')]),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();
    await tester.tap(navTab('我的'));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('my.card.identity')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('edit.nickname')), findsOneWidget);
  });
}
