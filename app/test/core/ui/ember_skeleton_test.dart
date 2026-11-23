import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/theme/ember_colors.dart';
import 'package:chatapp_app/core/ui/ember_skeleton.dart';

import 'ember_test_kit.dart';

double _opacity(WidgetTester tester) => tester
    .widget<Opacity>(
      find.descendant(of: find.byType(EmberSkeleton), matching: find.byType(Opacity)),
    )
    .opacity;

BoxDecoration _decoration(WidgetTester tester) => tester
    .widget<Container>(
      find.descendant(of: find.byType(EmberSkeleton), matching: find.byType(Container)),
    )
    .decoration! as BoxDecoration;

void main() {
  group('EmberSkeleton · default(§8.3 骨架表)', () {
    testWidgets('surface.sunken 色块,按给定宽高与圆角渲染', (tester) async {
      await pumpEmber(tester, const EmberSkeleton(width: 100, height: 12));
      expect(_decoration(tester).color, EmberColors.light.surfaceSunken);
      expect(tester.getSize(find.byType(EmberSkeleton)), const Size(100, 12));
      expect(_decoration(tester).borderRadius, BorderRadius.circular(8));
    });

    testWidgets('透明度在 .5↔1 之间呼吸(1.2s 循环)', (tester) async {
      await pumpEmber(tester, const EmberSkeleton(width: 100, height: 12));
      final first = _opacity(tester);
      await tester.pump(const Duration(milliseconds: 600));
      final second = _opacity(tester);
      expect(second, isNot(equals(first)));
      for (final value in [first, second]) {
        expect(value, inInclusiveRange(0.5, 1.0));
      }
    });

    testWidgets('深色下底色跟着换(不是硬编码的中性灰)', (tester) async {
      await pumpEmber(
        tester,
        const EmberSkeleton(width: 100, height: 12),
        brightness: Brightness.dark,
      );
      expect(_decoration(tester).color, EmberColors.dark.surfaceSunken);
    });
  });

  group('EmberSkeleton · 减弱动态效果', () {
    testWidgets('disableAnimations 为真时静止在中值(§8.4)', (tester) async {
      await pumpEmber(
        tester,
        const EmberSkeleton(width: 100, height: 12),
        disableAnimations: true,
      );
      final first = _opacity(tester);
      await tester.pump(const Duration(milliseconds: 600));
      expect(_opacity(tester), first);
      expect(first, 0.75);
    });
  });

  group('EmberSkeleton · 无障碍(§8.4)', () {
    testWidgets('纯装饰:骨架块整体 excludeSemantics,读屏不播报占位', (tester) async {
      final semantics = tester.ensureSemantics();
      await pumpEmber(tester, const EmberSkeleton(width: 100, height: 12));
      expect(
        find.descendant(
          of: find.byType(EmberSkeleton),
          matching: find.byType(ExcludeSemantics),
        ),
        findsOneWidget,
        reason: '§8.4:纯装饰图形必须标 excludeSemantics',
      );
      semantics.dispose();
    });
  });

  group('EmberSkeleton · 无 pressed / disabled / loading(§8.1)', () {
    test('骨架屏自己就是 loading 形态,不叠加别的状态', () {
      // §8.1 的「骨架屏」行只有 default —— 它本身就是别的组件的 loading 表现。
      const skeleton = EmberSkeleton();
      expect(skeleton.width, double.infinity);
    });
  });
}
