import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:phosphor_glyphs/phosphor_glyphs.dart';

import 'package:chatapp_app/core/theme/ember_colors.dart';
import 'package:chatapp_app/core/theme/tokens.g.dart' as tokens;
import 'package:chatapp_app/core/ui/ember_action_button.dart';
import 'package:chatapp_app/core/ui/ember_component_sizes.dart';
import 'package:chatapp_app/core/ui/ember_glow.dart';

import 'ember_test_kit.dart';

/// `EmberActionButton` 单测:逐格对照 E-5.2 page spec §4 的操作钮状态表。
///
/// 三件套的判据分别是:圆形本体(带装饰的 `DecoratedBox`)、光晕(`EmberGlow` 是否在场)、
/// 图标色(前景色)。
Widget actionButton({
  EmberActionButtonVariant variant = EmberActionButtonVariant.neutral,
  EmberActionButtonSize size = EmberActionButtonSize.small,
  VoidCallback? onPressed,
  bool loading = false,
}) =>
    EmberActionButton(
      icon: PhosphorIconsFill.heart,
      semanticLabel: '喜欢',
      variant: variant,
      size: size,
      loading: loading,
      onPressed: onPressed,
    );

BoxDecoration circleDecoration(WidgetTester tester) {
  final box = tester.widgetList<DecoratedBox>(find.byType(DecoratedBox)).firstWhere(
        (box) => (box.decoration as BoxDecoration).shape == BoxShape.circle,
      );
  return box.decoration as BoxDecoration;
}

Icon iconOf(WidgetTester tester) => tester.widget<Icon>(
      find.descendant(of: find.byType(EmberActionButton), matching: find.byType(Icon)),
    );

void main() {
  group('EmberActionButton · 几何', () {
    testWidgets('两档直径 56 / 64(E-5.2 §3「圆形 56 / 64」)', (tester) async {
      await pumpEmber(tester, actionButton(onPressed: () {}));
      expect(
        tester.getSize(find.byType(EmberActionButton)),
        const Size(EmberComponentSizes.actionButtonSmall, EmberComponentSizes.actionButtonSmall),
      );

      await pumpEmber(
        tester,
        actionButton(size: EmberActionButtonSize.large, onPressed: () {}),
      );
      expect(
        tester.getSize(find.byType(EmberActionButton)),
        const Size(EmberComponentSizes.actionButtonLarge, EmberComponentSizes.actionButtonLarge),
      );
    });

    testWidgets('圆形(BoxShape.circle),图标 24 档', (tester) async {
      await pumpEmber(tester, actionButton(onPressed: () {}));
      expect(circleDecoration(tester).shape, BoxShape.circle);
      expect(iconOf(tester).size, tokens.sizeIcon24);
    });
  });

  group('EmberActionButton · 主操作(喜欢)', () {
    testWidgets('default:brand.default 实底 + brand.on 图标 + emberGlow', (tester) async {
      await pumpEmber(
        tester,
        actionButton(variant: EmberActionButtonVariant.primary, onPressed: () {}),
      );
      expect(circleDecoration(tester).color, EmberColors.light.brandDefault);
      expect(iconOf(tester).color, EmberColors.light.brandOn);
      expect(find.byType(EmberGlow), findsOneWidget);
    });

    testWidgets('disabled(额度用完):sunken 底 + tertiary 图标 + divider 描边,无光晕', (tester) async {
      await pumpEmber(
        tester,
        actionButton(variant: EmberActionButtonVariant.primary),
      );
      final decoration = circleDecoration(tester);
      expect(decoration.color, EmberColors.light.surfaceSunken);
      expect(iconOf(tester).color, EmberColors.light.textTertiary);
      expect((decoration.border! as Border).top.color, EmberColors.light.borderDivider);
      expect(find.byType(EmberGlow), findsNothing);
    });
  });

  group('EmberActionButton · 次操作(跳过)', () {
    testWidgets('default:surface.card 底 + border.divider 1px + text.tertiary 图标', (tester) async {
      await pumpEmber(tester, actionButton(onPressed: () {}));
      final decoration = circleDecoration(tester);
      expect(decoration.color, EmberColors.light.surfaceCard);
      expect((decoration.border! as Border).top.color, EmberColors.light.borderDivider);
      expect(iconOf(tester).color, EmberColors.light.textTertiary);
      // 光晕只属于主操作(§2「一屏最多一处」)
      expect(find.byType(EmberGlow), findsNothing);
    });

    testWidgets('深色不用阴影,只靠描边分层(§5.3)', (tester) async {
      await pumpEmber(tester, actionButton(onPressed: () {}), brightness: Brightness.dark);
      final decoration = circleDecoration(tester);
      expect(decoration.boxShadow, anyOf(isNull, isEmpty));
      expect((decoration.border! as Border).top.color, EmberColors.dark.borderDivider);
    });
  });

  group('EmberActionButton · loading / 语义', () {
    testWidgets('loading:尾随 16 转圈,禁点击(§8.3 按钮 loading 行)', (tester) async {
      await pumpEmber(
        tester,
        actionButton(
          variant: EmberActionButtonVariant.primary,
          loading: true,
          onPressed: () {},
        ),
      );
      final spinner = tester.widget<CircularProgressIndicator>(
        find.byType(CircularProgressIndicator),
      );
      expect(spinner.strokeWidth, 2);
      expect(tester.getSize(find.byType(CircularProgressIndicator)),
          const Size(tokens.sizeIcon16, tokens.sizeIcon16));
      // 底与图标都还在(loading 不是 disabled)
      expect(circleDecoration(tester).color, EmberColors.light.brandDefault);

      var taps = 0;
      await pumpEmber(
        tester,
        actionButton(loading: true, onPressed: () => taps++),
      );
      await tester.tap(find.byType(EmberActionButton), warnIfMissed: false);
      expect(taps, 0);
    });

    testWidgets('读屏标签:默认取传入的 label,loading 时补「处理中」', (tester) async {
      String semanticLabel() => tester
          .widget<Semantics>(
            find
                .descendant(of: find.byType(EmberActionButton), matching: find.byType(Semantics))
                .first,
          )
          .properties
          .label!;

      await pumpEmber(tester, actionButton(onPressed: () {}));
      expect(semanticLabel(), '喜欢');

      await pumpEmber(tester, actionButton(loading: true, onPressed: () {}));
      expect(semanticLabel(), '喜欢，处理中');
    });
  });
}
