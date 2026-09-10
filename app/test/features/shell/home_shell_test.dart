import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/harness.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

const _loggedIn = {'auth.access': 'a', 'auth.refresh': 'r', 'auth.user_id': 7};

ScriptedAdapter _adapter({required Map<String, dynamic> profile}) => ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profile),
    });

void main() {
  testWidgets('三个 Tab 都在;「我的」显示昵称与资料入口', (tester) async {
    final adapter = _adapter(profile: profileJson(nickname: '小明'));
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    expect(find.byType(NavigationBar), findsOneWidget);
    expect(navTab('发现'), findsOneWidget);
    expect(navTab('会话'), findsOneWidget);
    expect(navTab('我的'), findsOneWidget);

    await tester.tap(navTab('我的'));
    await tester.pumpAndSettle();
    expect(find.text('小明'), findsOneWidget);
    expect(find.text('编辑资料'), findsOneWidget);
    expect(find.text('想找的人'), findsOneWidget);
    expect(find.text('设置'), findsOneWidget);
  });

  testWidgets('资料未完善 → 发现页显示引导卡,点按钮去向导', (tester) async {
    final adapter = _adapter(profile: profileJson(missing: ['bio', 'photos']));
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    expect(find.text('完善资料后就能开始滑卡'), findsOneWidget);
    await tester.tap(find.byKey(const Key('discovery.goOnboarding')));
    await tester.pumpAndSettle();
    expect(find.text('资料引导施工中'), findsOneWidget);
  });
}
