import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/theme/app_gradients.dart';
import 'package:chatapp_app/core/widgets/app_brand_mark.dart';

void main() {
  testWidgets('72 圆角方 + 心跳渐变 + 白心形图标', (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: Scaffold(body: Center(child: AppBrandMark(key: Key('brand')))),
    ));

    final box = tester.widget<Container>(
      find.descendant(
          of: find.byKey(const Key('brand')), matching: find.byType(Container)),
    );
    final decoration = box.decoration! as BoxDecoration;
    expect(decoration.gradient, AppGradients.heart);
    expect(tester.getSize(find.byKey(const Key('brand'))), const Size(72, 72));
    expect(find.byIcon(Icons.favorite_rounded), findsOneWidget);
  });

  testWidgets('品牌 mark 静态:连推数帧后仍无待处理帧', (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: Scaffold(body: Center(child: AppBrandMark(key: Key('brand')))),
    ));
    await tester.pump(const Duration(milliseconds: 100));
    await tester.pump(const Duration(milliseconds: 100));
    expect(tester.binding.hasScheduledFrame, isFalse);
  });
}
