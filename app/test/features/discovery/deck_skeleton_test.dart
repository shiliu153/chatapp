import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/features/discovery/widgets/deck_skeleton.dart';

void main() {
  testWidgets('渲染卡片骨架并呼吸(有限 pump,禁 pumpAndSettle)', (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: Scaffold(body: DeckSkeleton()),
    ));
    await tester.pump();

    expect(find.byType(DeckSkeleton), findsOneWidget);

    final opacityBefore = tester
        .widget<Opacity>(find.descendant(of: find.byType(DeckSkeleton), matching: find.byType(Opacity)))
        .opacity;
    await tester.pump(const Duration(milliseconds: 600));
    final opacityAfter = tester
        .widget<Opacity>(find.descendant(of: find.byType(DeckSkeleton), matching: find.byType(Opacity)))
        .opacity;
    expect(opacityAfter, isNot(opacityBefore)); // 呼吸中
  });
}
