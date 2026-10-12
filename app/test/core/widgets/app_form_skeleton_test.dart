import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/widgets/app_form_skeleton.dart';
import 'package:chatapp_app/core/widgets/app_skeleton.dart';

void main() {
  testWidgets('fields=3 渲染 6 个骨架块(3 标签 + 3 输入框);只用有限 pump', (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: Scaffold(
        body: Padding(
          padding: EdgeInsets.all(16),
          child: AppFormSkeleton(key: Key('sk')),
        ),
      ),
    ));
    await tester.pump(); // AppSkeleton 是无限呼吸动画,禁 pumpAndSettle
    expect(find.byKey(const Key('sk')), findsOneWidget);
    expect(find.byType(AppSkeleton), findsNWidgets(6));
  });
}
