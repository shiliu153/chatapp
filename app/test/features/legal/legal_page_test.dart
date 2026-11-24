import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/features/legal/legal_page.dart';
import 'package:chatapp_app/features/legal/legal_texts.dart';
import '../../support/heart_theme.dart';

void main() {
  testWidgets('协议页:顶栏标题 + 返回键 + 正文全文', (tester) async {
    await tester.pumpWidget(MaterialApp(theme: heartTheme, home: LegalPage.agreement()));

    expect(find.text('用户协议'), findsOneWidget);
    expect(find.byKey(const Key('legal.back')), findsOneWidget);
    expect(find.textContaining('欢迎使用'), findsOneWidget);
    expect(userAgreementText.isNotEmpty, isTrue);
  });

  testWidgets('读屏:返回键读「返回」,标题按 header 播报(E-5.6a page spec §6)', (tester) async {
    final handle = tester.ensureSemantics();
    await tester.pumpWidget(MaterialApp(theme: heartTheme, home: LegalPage.agreement()));

    expect(tester.getSemantics(find.byKey(const Key('legal.back'))).label, '返回');
    expect(
      tester.getSemantics(find.text('用户协议')).getSemanticsData().flagsCollection.isHeader,
      isTrue,
    );
    handle.dispose();
  });

  testWidgets('隐私政策页标题正确', (tester) async {
    await tester.pumpWidget(MaterialApp(theme: heartTheme, home: LegalPage.privacy()));
    expect(find.text('隐私政策'), findsOneWidget);
    expect(find.byKey(const Key('legal.back')), findsOneWidget);
  });
}
