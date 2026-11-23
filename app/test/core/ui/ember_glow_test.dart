import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/theme/ember_colors.dart';
import 'package:chatapp_app/core/ui/ember_glow.dart';

import 'ember_test_kit.dart';

/// 光晕画在内容外侧的叠加层上(`Stack` + `Positioned` + `DecoratedBox`),
/// 这样它不占布局 —— 测试也按这个结构取。
BoxDecoration _decoration(WidgetTester tester) {
  final boxes = tester
      .widgetList<DecoratedBox>(
        find.descendant(of: find.byType(EmberGlow), matching: find.byType(DecoratedBox)),
      )
      .map((d) => d.decoration)
      .whereType<BoxDecoration>()
      .where((d) => d.gradient is RadialGradient);
  return boxes.first;
}

void main() {
  group('EmberGlow · default(spec §2 品牌签名元素)', () {
    testWidgets('径向光晕:brand.default @12% 向外透明,不是 box-shadow', (tester) async {
      await pumpEmber(
        tester,
        const EmberGlow(child: SizedBox(width: 40, height: 40)),
      );
      final decoration = _decoration(tester);
      expect(decoration.boxShadow, isNull, reason: '光晕不是投影');
      final gradient = decoration.gradient! as RadialGradient;
      final brand = EmberColors.light.brandDefault;
      expect(gradient.colors.first.a, closeTo(0.12, 1e-9));
      expect(gradient.colors.first.r, closeTo(brand.r, 1e-9));
      expect(gradient.colors.last.a, 0, reason: '边缘必须完全透明,否则会看出圆角方块');
    });

    testWidgets('深色下用亮朱砂(§3.4:深色 brand 更亮)', (tester) async {
      await pumpEmber(
        tester,
        const EmberGlow(child: SizedBox(width: 40, height: 40)),
        brightness: Brightness.dark,
      );
      final gradient = _decoration(tester).gradient! as RadialGradient;
      expect(
        gradient.colors.first.r,
        closeTo(EmberColors.dark.brandDefault.r, 1e-9),
      );
    });

    testWidgets('圆形形态给头像环用', (tester) async {
      await pumpEmber(
        tester,
        const EmberGlow(
          shape: EmberGlowShape.circle,
          child: SizedBox(width: 40, height: 40),
        ),
      );
      expect(_decoration(tester).shape, BoxShape.circle);
    });

    testWidgets('按压时降到 50% 由调用方传 opacity(§8.3)', (tester) async {
      await pumpEmber(
        tester,
        const EmberGlow(
          opacity: 0.06,
          child: SizedBox(width: 40, height: 40),
        ),
      );
      final gradient = _decoration(tester).gradient! as RadialGradient;
      expect(gradient.colors.first.a, closeTo(0.06, 1e-9));
    });
  });
}
