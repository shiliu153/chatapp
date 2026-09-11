import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/im/im_client.dart';

import '../../support/fake_im_client.dart';
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
    expect(navTab('消息'), findsOneWidget);
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
    expect(find.text('第 1 步 / 共 3 步'), findsOneWidget);
  });

  testWidgets('消息 Tab 显示未读角标', (tester) async {
    final fake = FakeImClient()..conversations = [ImConversation(peerId: 'u9', unreadCount: 3)];
    final adapter = _adapter(profile: profileJson())
      ..routes['POST /im/user_sig'] = (options) => ok({
            'user_sig': 'sig',
            'sdkappid': '1600161711',
            'im_user_id': 'u7',
            'expire': 604800,
          });

    await pumpApp(tester, adapter, prefs: _loggedIn, imClient: fake);
    await tester.pumpAndSettle();

    expect(find.text('3'), findsWidgets); // 角标数字
    final badge = tester.widget<Badge>(find.byType(Badge));
    expect(badge.backgroundColor, const Color(0xFFFF2C55)); // 抖音红
  });
}
