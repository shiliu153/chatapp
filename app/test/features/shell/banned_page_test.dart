import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/harness.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

const _loggedIn = {'auth.access': 'a', 'auth.refresh': 'r', 'auth.user_id': 7};

void main() {
  testWidgets('重封禁用户:主框架换成封禁页,可退出登录', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) =>
          ok(profileJson(status: 'banned_heavy', banReason: '骚扰他人')),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    expect(find.text('账号已被封禁'), findsOneWidget);
    expect(find.text('原因:骚扰他人'), findsOneWidget);
    expect(find.text('发现'), findsNothing);   // 底部 Tab 被整屏替换

    await tester.tap(find.byKey(const Key('banned.logout')));
    await tester.pumpAndSettle();

    expect(find.text('获取验证码'), findsOneWidget);   // 回登录页
  });
}
