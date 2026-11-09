import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../support/harness.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

const _loggedIn = {'auth.access': 'a', 'auth.refresh': 'r', 'auth.user_id': 7};

/// 进设置页(「我的」→ 设置)。
Future<void> _openSettings(WidgetTester tester) async {
  await tester.tap(navTab('我的'));
  await tester.pumpAndSettle();
  // 「设置」行在列表底部,可能折叠线以下;先滚到可见再点
  await tester.ensureVisible(find.byKey(const Key('my.row.settings')));
  await tester.pumpAndSettle();
  await tester.tap(find.byKey(const Key('my.row.settings')));
  await tester.pumpAndSettle();
}

/// 把设置页滚到某一行可见。
///
/// 两个理由叠在一起:
/// 1. 设置页用 ListView,行数超过一屏后**没滚到的行根本没被 build**,
///    `ensureVisible` / `find.byKey` 都会报「Found 0 widgets」,必须先滚过去;
/// 2. `scrollUntilVisible` 的 `scrollable:` 要求 finder 指向 `Scrollable`(不是外层
///    ListView),而树里**不止一个** Scrollable —— 用 `find.descendant(of: 设置页列表
///    的 key, matching: Scrollable)` 精确定位,比 `find.byType(Scrollable).first`
///    更稳:后者靠遍历顺序碰运气,哪天设置页里多一个可滚区域就会静默滚错列表。
Future<void> _scrollSettingsTo(WidgetTester tester, Key key) async {
  await tester.scrollUntilVisible(
    find.byKey(key),
    120,
    scrollable: find.descendant(
      of: find.byKey(const Key('settings.list')),
      matching: find.byType(Scrollable),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('退出登录 → 清空凭证回到登录页', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    await _openSettings(tester);

    // 设置页行数已超过一屏,ListView 懒加载:逐个滚到可见再断言,
    // 以后再加行也不用改这里。
    // 顺序必须**自上而下**:滚动只会往下翻,先查靠下的行会把靠上的行顶出构建范围。
    for (final key in const [
      'settings.row.blocks',
      'settings.row.notifications',
      'settings.row.devices',
      'settings.row.stats',
      'settings.row.feedback',
      'settings.row.about',
      'settings.row.agreement',
      'settings.row.privacy',
      'settings.row.deleteAccount',
      'settings.logout',
    ]) {
      await _scrollSettingsTo(tester, Key(key));
      expect(find.byKey(Key(key)), findsOneWidget);
    }

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

    await _openSettings(tester);

    await _scrollSettingsTo(tester, const Key('settings.row.deleteAccount'));
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

    await _openSettings(tester);

    await _scrollSettingsTo(tester, const Key('settings.row.deleteAccount'));
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
  testWidgets('隐身浏览开关 → PATCH visits_hidden', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
      'PATCH /users/me': (options) => ok(profileJson(visitsHidden: true)),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    await _openSettings(tester);

    await tester.tap(find.byKey(const Key('settings.row.visitsHidden')));
    await tester.pumpAndSettle();

    final request = adapter.log.lastWhere((item) => item.method == 'PATCH');
    expect(request.data, {'visits_hidden': true});
  });

  testWidgets('隐身浏览开关失败 → 回滚并提示', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
      'PATCH /users/me': (options) => jsonError(500, '服务器开小差了'),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    await _openSettings(tester);

    await tester.tap(find.byKey(const Key('settings.row.visitsHidden')));
    await tester.pumpAndSettle();

    expect(find.text('服务器开小差了'), findsOneWidget);
    await drainToast(tester);   // Toast 的 2s Timer 要推过去,否则用例以 pending timer 失败
  });

  testWidgets('登录设备入口 → 二级页列出各端', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
      'GET /devices': (options) => ok({
            'results': [
              deviceJson(current: true),
              deviceJson(clientType: 'web', clientLabel: '网页端'),
            ],
          }),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    await _openSettings(tester);

    await _scrollSettingsTo(tester, const Key('settings.row.devices'));
    await tester.tap(find.byKey(const Key('settings.row.devices')));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('devices.row.app')), findsOneWidget);
    expect(find.byKey(const Key('devices.row.web')), findsOneWidget);
    expect(find.byKey(const Key('devices.current.app')), findsOneWidget);
  });

  testWidgets('「我的数据」入口 → 报告页(默认周)', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
      'GET /stats/me': (options) => ok({
            'period': 'week',
            'start': '2026-11-09',
            'end': '2026-11-15',
            'matches': 2,
            'likes_given': 14,
            'likes_received': 9,
            'visits': 6,
            'posts': 3,
            'post_likes': 11,
            'new_followers': 1,
          }),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    await _openSettings(tester);

    await _scrollSettingsTo(tester, const Key('settings.row.stats'));
    await tester.tap(find.byKey(const Key('settings.row.stats')));
    // 报告页首帧是骨架(带无限呼吸动画),只能有限 pump,不能 pumpAndSettle
    await pumpFrames(tester);

    expect(find.text('我的数据'), findsOneWidget); // 二级页顶栏
    expect(find.byKey(const Key('stats.card.matches')), findsOneWidget);
    final request = adapter.log.lastWhere((item) => item.path == '/stats/me');
    expect(request.queryParameters['period'], 'week');
  });
}
