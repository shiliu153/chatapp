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
    await tester.tap(find.text('退出登录'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('退出'));
    await tester.pumpAndSettle();

    expect(find.text('获取验证码'), findsOneWidget); // 回到登录页
    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getString('auth.refresh'), isNull);
  });
}
