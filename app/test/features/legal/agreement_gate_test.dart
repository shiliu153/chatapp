import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/features/legal/legal_texts.dart';

import '../../support/harness.dart';
import '../../support/scripted_adapter.dart';

void main() {
  // 协议弹窗期间启动页在转圈(无限动画),pumpAndSettle 会超时;只用有限次 pump。
  Future<void> pumpUntilDialog(WidgetTester tester) async {
    await tester.pump();                                    // 跑 _start 的 prefs 读取
    await tester.pump(const Duration(milliseconds: 300));   // 弹窗动画
  }

  // harness 默认把 legal.agreed_version 设为当前版本;传 0 模拟「首次启动未同意」
  testWidgets('首次启动 → 弹协议;同意后进登录页并记下版本', (tester) async {
    await pumpApp(tester, ScriptedAdapter({}), prefs: {'legal.agreed_version': 0});
    await pumpUntilDialog(tester);

    expect(find.text('同意并继续'), findsOneWidget);
    await tester.tap(find.byKey(const Key('agreement.accept')));
    await tester.pumpAndSettle();

    expect(find.text('获取验证码'), findsOneWidget);   // 已到登录页
    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getInt('legal.agreed_version'), legalVersion);
  });

  testWidgets('不同意 → 停在提示页,不启动', (tester) async {
    await pumpApp(tester, ScriptedAdapter({}), prefs: {'legal.agreed_version': 0});
    await pumpUntilDialog(tester);

    await tester.tap(find.byKey(const Key('agreement.decline')));
    await tester.pumpAndSettle();

    expect(find.text('需要同意《用户协议》与《隐私政策》才能使用本应用'), findsOneWidget);
    expect(find.text('获取验证码'), findsNothing);
  });

  testWidgets('已同意当前版本 → 不弹窗,直接进登录页', (tester) async {
    await pumpApp(tester, ScriptedAdapter({}), prefs: {'legal.agreed_version': legalVersion});
    await tester.pumpAndSettle();

    expect(find.text('同意并继续'), findsNothing);
    expect(find.text('获取验证码'), findsOneWidget);
  });
}
