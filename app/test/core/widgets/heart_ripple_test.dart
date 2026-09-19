import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/widgets/heart_ripple.dart';

void main() {
  testWidgets('三圈同心环 + 中心光点;纯静态(有限 pump 不变化)', (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: Scaffold(body: Center(child: HeartRipple())),
    ));

    expect(find.byType(HeartRipple), findsOneWidget);
    expect(
      find.descendant(of: find.byType(HeartRipple), matching: find.byType(Container)),
      findsNWidgets(4), // 3 环 + 中心点
    );

    // 静态:推进两帧后仍无变化(无动画控制器)
    await tester.pump(const Duration(milliseconds: 600));
    await tester.pump(const Duration(milliseconds: 600));
    expect(find.byType(HeartRipple), findsOneWidget);
  });

  testWidgets('尺寸参数生效', (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: Scaffold(body: Center(child: HeartRipple(size: 120))),
    ));
    expect(tester.getSize(find.byType(HeartRipple)), const Size(120, 120));
  });
}
