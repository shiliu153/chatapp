import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/features/settings/about_page.dart';

void main() {
  testWidgets('展示应用名、版本与协议入口', (tester) async {
    await tester.pumpWidget(const MaterialApp(home: AboutPage()));

    expect(find.text('心跳'), findsOneWidget);
    expect(find.byKey(const Key('about.version')), findsOneWidget);
    expect(find.text('版本 1.0.1'), findsOneWidget);
    expect(find.byKey(const Key('about.agreement')), findsOneWidget);
    expect(find.byKey(const Key('about.privacy')), findsOneWidget);
  });
}
