import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../support/harness.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

const _loggedIn = {'auth.access': 'a', 'auth.refresh': 'r', 'auth.user_id': 7};

void main() {
  testWidgets('退出登录 → 清空凭证回到登录页', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    await tester.tap(navTab('我的'));
    await tester.pumpAndSettle();
    // 「设置」行在列表底部,可能折叠线以下;先滚到可见再点
    await tester.ensureVisible(find.byKey(const Key('my.row.settings')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('my.row.settings')));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('settings.row.blocks')), findsOneWidget);
    expect(find.byKey(const Key('settings.row.agreement')), findsOneWidget);
    expect(find.byKey(const Key('settings.row.privacy')), findsOneWidget);
    expect(find.byKey(const Key('settings.logout')), findsOneWidget);

    await tester.tap(find.text('退出登录'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('退出'));
    await tester.pumpAndSettle();

    expect(find.text('获取验证码'), findsOneWidget); // 回到登录页
    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getString('auth.refresh'), isNull);
  });

  testWidgets('注销账号:两步确认 → 清空凭证回到登录页', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
      'DELETE /users/me': (options) => ok({}, status: 204),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    await tester.tap(navTab('我的'));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('my.row.settings')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('my.row.settings')));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('settings.row.deleteAccount')), findsOneWidget);

    // 第一步:后果说明
    await tester.tap(find.byKey(const Key('settings.row.deleteAccount')));
    await tester.pumpAndSettle();
    expect(find.text('注销账号?'), findsOneWidget);
    await tester.tap(find.text('继续'));
    await tester.pumpAndSettle();

    // 第二步:输入手机号
    await tester.enterText(find.byKey(const Key('deleteAccount.phone')), '13800138000');
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('deleteAccount.confirm')));
    await tester.pumpAndSettle();

    expect(find.text('获取验证码'), findsOneWidget); // 回到登录页
    final delete = adapter.log.lastWhere((r) => r.method == 'DELETE');
    expect(delete.path, '/users/me');
    expect(delete.data, {'phone': '13800138000'});
    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getString('auth.refresh'), isNull);

    await drainToast(tester); // 注销成功 Toast 的 2s Timer 必须推过去
  });

  testWidgets('注销失败(手机号不匹配)留在设置页', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
      'DELETE /users/me': (options) => jsonError(400, '手机号与当前账号不一致'),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    await tester.tap(navTab('我的'));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('my.row.settings')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('my.row.settings')));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('settings.row.deleteAccount')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('继续'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('deleteAccount.phone')), '13900139000');
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('deleteAccount.confirm')));
    await tester.pumpAndSettle();

    expect(find.text('手机号与当前账号不一致'), findsOneWidget); // 失败 Toast
    expect(find.byKey(const Key('settings.row.deleteAccount')), findsOneWidget); // 仍在设置页
    final prefs = await SharedPreferences.getInstance();
    // 凭证未被清(启动时 bootstrap 会静默刷新一次,所以这里只断言「还在」,不断言具体值)
    expect(prefs.getString('auth.refresh'), isNotNull);

    await drainToast(tester);
  });
}
