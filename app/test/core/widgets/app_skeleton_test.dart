import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/widgets/app_skeleton.dart';

void main() {
  testWidgets('渲染骨架块,呼吸动画随时间变化(有限 pump,禁 pumpAndSettle)', (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: Scaffold(body: Center(child: AppSkeleton(width: 100, height: 12))),
    ));
    expect(find.byType(AppSkeleton), findsOneWidget);

    double opacity() => tester
        .widget<Opacity>(
          find.descendant(of: find.byType(AppSkeleton), matching: find.byType(Opacity)),
        )
        .opacity;

    final first = opacity();
    await tester.pump(const Duration(milliseconds: 600));
    expect(opacity(), isNot(equals(first)));
  });
}
