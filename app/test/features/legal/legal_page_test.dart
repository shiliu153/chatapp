import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/features/legal/legal_page.dart';
import 'package:chatapp_app/features/legal/legal_texts.dart';

void main() {
  testWidgets('协议页:顶栏标题 + 返回键 + 正文全文', (tester) async {
    await tester.pumpWidget(const MaterialApp(home: LegalPage.agreement()));

    expect(find.text('用户协议'), findsOneWidget);
    expect(find.byKey(const Key('legal.back')), findsOneWidget);
    expect(find.textContaining('欢迎使用'), findsOneWidget);
    expect(userAgreementText.isNotEmpty, isTrue);
  });

  testWidgets('隐私政策页标题正确', (tester) async {
    await tester.pumpWidget(const MaterialApp(home: LegalPage.privacy()));
    expect(find.text('隐私政策'), findsOneWidget);
    expect(find.byKey(const Key('legal.back')), findsOneWidget);
  });
}
