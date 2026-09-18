import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/features/shell/app_bottom_bar.dart';
import 'package:chatapp_app/im/im_client.dart';

import '../../support/harness.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

const _loggedIn = {'auth.access': 'a', 'auth.refresh': 'r', 'auth.user_id': 7};

void main() {
  testWidgets('被其他设备顶下线 → 强制退出回登录页并提示原因', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
      'POST /im/user_sig': (options) => ok({
            'user_sig': 'sig',
            'sdkappid': '1600161711',
            'im_user_id': 'u7',
            'expire': 604800,
          }),
    });
    final fake = await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();
    expect(find.byType(AppBottomBar), findsOneWidget); // 已在主框架

    // 另一台设备登录同账号 → 腾讯踢下线事件
    fake.emit(const ImKickedOffline());
    await tester.pumpAndSettle();

    expect(find.byType(AppBottomBar), findsNothing); // 已退出主框架
    expect(find.byKey(const Key('login.phone')), findsOneWidget); // 回登录页
    expect(find.textContaining('其他设备'), findsOneWidget); // 告知被踢原因
  });

  testWidgets('冷启动时本地令牌已被作废(40101)→ 回登录页并提示', (tester) async {
    final adapter = ScriptedAdapter({
      // 启动鉴权只走 refresh;单设备冲突时后端就在这里拒
      'POST /auth/token/refresh': (options) =>
          ok({'code': 40101, 'message': '账号已在其他设备登录,请重新登录'}, status: 401),
      'GET /users/me': (options) => ok(profileJson()),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('login.phone')), findsOneWidget);
    expect(find.textContaining('其他设备'), findsOneWidget);
  });
}
