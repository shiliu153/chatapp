import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/features/profile/widgets/completion_ring.dart';

Widget wrap(Widget child) => MaterialApp(home: Scaffold(body: Center(child: child)));

void main() {
  testWidgets('渲染 done/total 文案', (tester) async {
    await tester.pumpWidget(wrap(const CompletionRing(done: 4, total: 6)));
    expect(find.text('4/6'), findsOneWidget);
  });

  testWidgets('done=0 不崩且显示 0/6', (tester) async {
    await tester.pumpWidget(wrap(const CompletionRing(done: 0, total: 6)));
    expect(find.text('0/6'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('done=total(满弧)不崩', (tester) async {
    await tester.pumpWidget(wrap(const CompletionRing(done: 6, total: 6)));
    expect(find.text('6/6'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('total=0 不除零', (tester) async {
    await tester.pumpWidget(wrap(const CompletionRing(done: 0, total: 0)));
    expect(tester.takeException(), isNull);
  });

  testWidgets('尺寸可覆盖', (tester) async {
    await tester.pumpWidget(wrap(const CompletionRing(done: 1, total: 6, size: 64)));
    final box = tester.getSize(find.byType(CompletionRing));
    expect(box.width, 64);
  });
}
