import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:phosphor_glyphs/phosphor_glyphs.dart';

import 'package:chatapp_app/core/theme/ember_colors.dart';
import 'package:chatapp_app/core/theme/tokens.g.dart' as tokens;
import 'package:chatapp_app/core/ui/ember_chip.dart';
import 'package:chatapp_app/core/ui/ember_component_sizes.dart';

import 'ember_test_kit.dart';

/// `EmberChip` 单测:逐格对照「余烬 Ember」§8.3 的 **Chip** 行 + §8.4 触控口径。
Widget chip({bool selected = false, VoidCallback? onTap}) => EmberChip(
      label: '筛选',
      icon: PhosphorIconsRegular.slidersHorizontal,
      selected: selected,
      onTap: onTap ?? () {},
    );

/// 胶囊本体(带装饰的那个 `Container`)。
BoxDecoration capsuleDecoration(WidgetTester tester) =>
    tester
        .widget<Container>(
          find.descendant(of: find.byType(EmberChip), matching: find.byType(Container)).first,
        )
        .decoration! as BoxDecoration;

/// 胶囊上的文案。
Text labelOf(WidgetTester tester) => tester.widget<Text>(
      find.descendant(of: find.byType(EmberChip), matching: find.byType(Text)).first,
    );

void main() {
  group('EmberChip · 取值(§8.3 Chip 行)', () {
    testWidgets('default:底 surface.sunken + 字 text.secondary', (tester) async {
      await pumpEmber(tester, chip());
      expect(capsuleDecoration(tester).color, EmberColors.light.surfaceSunken);
      expect(labelOf(tester).style!.color, EmberColors.light.textSecondary);
      expect(labelOf(tester).style!.fontSize, tokens.fontSizeCaption);
    });

    testWidgets('selected:底 brand.default + 字 brand.on', (tester) async {
      await pumpEmber(tester, chip(selected: true));
      expect(capsuleDecoration(tester).color, EmberColors.light.brandDefault);
      expect(labelOf(tester).style!.color, EmberColors.light.brandOn);
    });

    testWidgets('disabled(onTap = null):字退成 text.tertiary', (tester) async {
      await pumpEmber(
        tester,
        const EmberChip(label: '筛选'),
      );
      expect(labelOf(tester).style!.color, EmberColors.light.textTertiary);
    });

    testWidgets('图标取 16 档(§6 行内)', (tester) async {
      await pumpEmber(tester, chip());
      final icon = tester.widget<Icon>(
        find.descendant(of: find.byType(EmberChip), matching: find.byType(Icon)),
      );
      expect(icon.size, tokens.sizeIcon16);
    });

    testWidgets('胶囊高 36,热区补到 48×48(§8.4)', (tester) async {
      await pumpEmber(tester, chip());
      final capsule = tester.getSize(find.descendant(
        of: find.byType(EmberChip),
        matching: find.byType(Container),
      ).first);
      expect(capsule.height, EmberComponentSizes.chipHeight);
      expect(tester.getSize(find.byType(EmberChip)).height, tokens.sizeTouchApp);
      expect(
        tester.getSize(find.byType(EmberChip)).height,
        greaterThanOrEqualTo(tokens.sizeTouchApp),
      );
    });
  });

  group('EmberChip · 语义(§8.4)', () {
    testWidgets('读屏标签按选中态补「已选中」', (tester) async {
      await pumpEmber(tester, chip());
      expect(
        tester
            .widget<Semantics>(
              find.descendant(of: find.byType(EmberChip), matching: find.byType(Semantics)).first,
            )
            .properties
            .label,
        '筛选',
      );

      await pumpEmber(tester, chip(selected: true));
      expect(
        tester
            .widget<Semantics>(
              find.descendant(of: find.byType(EmberChip), matching: find.byType(Semantics)).first,
            )
            .properties
            .label,
        '筛选，已选中',
      );
    });

    testWidgets('点击回调生效;disabled 时不触发', (tester) async {
      var taps = 0;
      await pumpEmber(tester, chip(onTap: () => taps++));
      await tester.tap(find.byType(EmberChip));
      expect(taps, 1);

      await pumpEmber(tester, const EmberChip(label: '筛选'));
      await tester.tap(find.byType(EmberChip), warnIfMissed: false);
      expect(taps, 1);
    });
  });
}
