import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/widgets/gradient_icon.dart';

void main() {
  testWidgets('渲染为 ShaderMask 包裹的图标', (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: Scaffold(body: GradientIcon(Icons.favorite_rounded, size: 24)),
    ));
    expect(find.byType(GradientIcon), findsOneWidget);
    expect(find.byType(ShaderMask), findsOneWidget);
    expect(find.byIcon(Icons.favorite_rounded), findsOneWidget);
  });
}
