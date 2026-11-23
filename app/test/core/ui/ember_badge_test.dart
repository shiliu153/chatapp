import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/theme/ember_colors.dart';
import 'package:chatapp_app/core/theme/tokens.g.dart' as tokens;
import 'package:chatapp_app/core/ui/ember_badge.dart';

import 'ember_test_kit.dart';

BoxDecoration _badgeDecoration(WidgetTester tester) {
  final container = tester.widget<Container>(
    find.descendant(of: find.byType(EmberBadge), matching: find.byType(Container)).first,
  );
  return container.decoration! as BoxDecoration;
}

void main() {
  group('EmberBadge · default(§8.3 角标表)', () {
    testWidgets('brand.default 底 + brand.on 11/w700 字 + 胶囊圆角 + min 18×18', (tester) async {
      await pumpEmber(tester, const EmberBadge(count: 3));
      final decoration = _badgeDecoration(tester);
      expect(decoration.color, EmberColors.light.brandDefault);
      expect(
        decoration.borderRadius,
        BorderRadius.circular(tokens.radiusPill),
      );

      final text = tester.widget<Text>(find.text('3'));
      expect(text.style!.color, EmberColors.light.brandOn);
      expect(text.style!.fontSize, tokens.fontSizeMicro);
      expect(text.style!.fontWeight, FontWeight.w700);
      // §8.4:角标不跟随系统字号缩放
      expect(text.textScaler, TextScaler.noScaling);
      expect(
        tester.getSize(find.byType(EmberBadge)).height,
        greaterThanOrEqualTo(18),
      );
    });

    testWidgets('≥100 显示 99+,可换成别的上限', (tester) async {
      await pumpEmber(tester, const EmberBadge(count: 120));
      expect(find.text('99+'), findsOneWidget);

      await pumpEmber(tester, const EmberBadge(count: 120, maxCount: 9));
      expect(find.text('9+'), findsOneWidget);
    });

    testWidgets('count ≤ 0 不渲染(未读清零后的常态)', (tester) async {
      await pumpEmber(tester, const EmberBadge(count: 0));
      expect(find.byType(Text), findsNothing);
      expect(find.byType(Container), findsNothing);
    });

    testWidgets('圆点形态:直径 8 的 brand.default 圆', (tester) async {
      await pumpEmber(tester, const EmberBadge(count: 1, dot: true));
      final decoration = _badgeDecoration(tester);
      expect(decoration.color, EmberColors.light.brandDefault);
      expect(decoration.shape, BoxShape.circle);
      expect(find.byType(Text), findsNothing);
    });

    testWidgets('读屏标签说清楚是「几条未读」', (tester) async {
      final handle = tester.ensureSemantics();
      await pumpEmber(tester, const EmberBadge(count: 7));
      expect(semanticsOf(tester, find.byType(EmberBadge)).label, contains('7 条未读'));
      handle.dispose();
    });
  });

  group('EmberBadge · 无 pressed / disabled / loading(§8.1 明确没有)', () {
    test('角标只承担「显示数量」,不提供交互态与忙碌态', () {
      // §8.1 的「Badge / Chip」行只勾了 default / focus / selected;
      // 角标本身不接收点击(点击由外层列表行承担),所以这里也不造 pressed/loading。
      const badge = EmberBadge(count: 1);
      expect(badge.count, 1);
      expect(badge.dot, isFalse);
    });
  });
}
