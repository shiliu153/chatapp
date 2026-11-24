import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/features/discovery/widgets/deck_skeleton.dart';
import '../../support/heart_theme.dart';

void main() {
  testWidgets('渲染卡片骨架并呼吸(有限 pump,禁 pumpAndSettle)', (tester) async {
    await tester.pumpWidget(MaterialApp(theme: heartTheme, 
      home: Scaffold(body: DeckSkeleton()),
    ));
    await tester.pump();

    expect(find.byType(DeckSkeleton), findsOneWidget);

    // 骨架块有多个(卡面 1 + 文字 4 + 操作钮 2),取第一个的呼吸相位即可
    final opacityBefore = tester
        .widget<Opacity>(
            find.descendant(of: find.byType(DeckSkeleton), matching: find.byType(Opacity)).first)
        .opacity;
    await tester.pump(const Duration(milliseconds: 600));
    final opacityAfter = tester
        .widget<Opacity>(
            find.descendant(of: find.byType(DeckSkeleton), matching: find.byType(Opacity)).first)
        .opacity;
    expect(opacityAfter, isNot(opacityBefore)); // 呼吸中
  });
}
