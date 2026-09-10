import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/harness.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

void main() {
  testWidgets('获取验证码 → 按钮进入 60 秒倒计时', (tester) async {
    final adapter = ScriptedAdapter({'POST /auth/sms/send': (options) => ok({'status': 'ok'})});
    await pumpApp(tester, adapter);
    await tester.pumpAndSettle();

    await tester.enterText(find.byKey(const Key('login.phone')), '13800138000');
    await tester.tap(find.byKey(const Key('login.sendCode')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(adapter.log.where((r) => r.path == '/auth/sms/send'), hasLength(1));
    expect(find.text('60 秒后重发'), findsOneWidget);

    // 卸载页面以取消倒计时 Timer,否则测试结束会报 pending timer
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('手机号格式不对 → 不发请求', (tester) async {
    final adapter = ScriptedAdapter({});
    await pumpApp(tester, adapter);
    await tester.pumpAndSettle();

    await tester.enterText(find.byKey(const Key('login.phone')), '123');
    await tester.tap(find.byKey(const Key('login.sendCode')));
    await tester.pump();

    expect(find.text('请输入正确的手机号'), findsOneWidget);
    expect(adapter.log, isEmpty);
  });

  testWidgets('老用户登录成功 → 进入主框架', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/sms/verify': (options) =>
          ok({'access': 'a', 'refresh': 'r', 'is_new_user': false, 'user_id': 7}),
      'GET /users/me': (options) => ok(profileJson()),
      'POST /auth/token/refresh': (options) => ok({'access': 'a', 'refresh': 'r'}),
    });
    await pumpApp(tester, adapter);
    await tester.pumpAndSettle();

    await tester.enterText(find.byKey(const Key('login.phone')), '13800138000');
    await tester.enterText(find.byKey(const Key('login.code')), '123456');
    await tester.tap(find.byKey(const Key('login.submit')));
    await tester.pumpAndSettle();

    expect(adapter.log.where((r) => r.path == '/auth/sms/verify'), hasLength(1));
    expect(find.byType(NavigationBar), findsOneWidget); // 进主框架了
  });
}
