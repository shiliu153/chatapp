import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/theme/app_colors.dart';
import 'package:chatapp_app/core/theme/app_gradients.dart';
import 'package:chatapp_app/core/widgets/app_progress_bar.dart';

void main() {
  testWidgets('3 段;第 0 段填充、其余 divider;高 4', (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: Scaffold(body: AppProgressBar(steps: 3, current: 0)),
    ));

    final bars = find.descendant(
        of: find.byType(AppProgressBar),
        matching: find.byType(AnimatedContainer));
    expect(bars, findsNWidgets(3));

    BoxDecoration decorationAt(int index) =>
        tester.widget<AnimatedContainer>(bars.at(index)).decoration!
            as BoxDecoration;

    expect(decorationAt(0).gradient, AppGradients.heart);
    expect(decorationAt(1).gradient, isNull);
    expect(decorationAt(1).color, AppColors.divider);
    expect(tester.getSize(bars.at(0)).height, 4);
  });

  testWidgets('current=2 时三段全填充', (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: Scaffold(body: AppProgressBar(steps: 3, current: 2)),
    ));
    final bars = find.descendant(
        of: find.byType(AppProgressBar),
        matching: find.byType(AnimatedContainer));
    for (var i = 0; i < 3; i++) {
      expect(
        (tester.widget<AnimatedContainer>(bars.at(i)).decoration!
                as BoxDecoration)
            .gradient,
        AppGradients.heart,
      );
    }
  });
}
