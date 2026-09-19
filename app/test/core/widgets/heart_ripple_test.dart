import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/widgets/heart_ripple.dart';

double _pingOpacity(WidgetTester tester, int index) => tester
    .widget<Opacity>(
      find.ancestor(
        of: find.byKey(Key('ripple.ping$index')),
        matching: find.byType(Opacity),
      ).first,
    )
    .opacity;

void main() {
  testWidgets('三圈同心环 + 中心光点 + 双波扩散(有限 pump,禁 pumpAndSettle)', (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: Scaffold(body: Center(child: HeartRipple())),
    ));

    expect(find.byType(HeartRipple), findsOneWidget);
    expect(
      find.descendant(of: find.byType(HeartRipple), matching: find.byType(Container)),
      findsNWidgets(4), // 3 环 + 中心点(波纹用 DecoratedBox,不算 Container)
    );
    expect(find.byKey(const Key('ripple.ping0')), findsOneWidget);
    expect(find.byKey(const Key('ripple.ping1')), findsOneWidget);

    // 波纹在动:有限推进后不透明度变化
    final before = _pingOpacity(tester, 0);
    await tester.pump(const Duration(milliseconds: 600));
    expect(_pingOpacity(tester, 0), isNot(before));
  });

  testWidgets('减弱动态效果 → 波纹静止(不渲染)', (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: MediaQuery(
        data: MediaQueryData(disableAnimations: true),
        child: Scaffold(body: Center(child: HeartRipple())),
      ),
    ));

    expect(find.byType(HeartRipple), findsOneWidget);
    expect(find.byKey(const Key('ripple.ping0')), findsNothing);
    expect(find.byKey(const Key('ripple.ping1')), findsNothing);
  });

  testWidgets('尺寸参数生效', (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: Scaffold(body: Center(child: HeartRipple(size: 120))),
    ));
    expect(tester.getSize(find.byType(HeartRipple)), const Size(120, 120));
  });
}
