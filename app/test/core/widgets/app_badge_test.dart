import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/widgets/app_badge.dart';

Widget wrap(Widget child) => MaterialApp(home: Scaffold(body: Center(child: child)));

void main() {
  testWidgets('显示数字;≥100 显示 99+', (tester) async {
    await tester.pumpWidget(wrap(const AppBadge(count: 3)));
    expect(find.text('3'), findsOneWidget);

    await tester.pumpWidget(wrap(const AppBadge(count: 120)));
    expect(find.text('99+'), findsOneWidget);
  });

  testWidgets('count≤0 不渲染内容', (tester) async {
    await tester.pumpWidget(wrap(const AppBadge(count: 0)));
    expect(find.byType(Text), findsNothing);
  });
}
