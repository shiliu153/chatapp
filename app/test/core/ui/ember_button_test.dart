import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/theme/ember_colors.dart';
import 'package:chatapp_app/core/theme/tokens.g.dart' as tokens;
import 'package:chatapp_app/core/ui/ember_button.dart';
import 'package:chatapp_app/core/ui/ember_glow.dart';
import 'package:chatapp_app/core/ui/ember_pressable.dart';

import 'ember_test_kit.dart';

/// 取按钮的底色(主按钮外面套了 `EmberGlow`,所以按「最内层的 Container」找)。
Color _backgroundOf(WidgetTester tester) {
  final containers = tester
      .widgetList<Container>(find.byType(Container))
      .where((c) => c.decoration is BoxDecoration)
      .toList();
  final decoration = containers.last.decoration! as BoxDecoration;
  return decoration.color!;
}

Color _labelColor(WidgetTester tester, String label) =>
    tester.widget<Text>(find.text(label)).style!.color!;

BoxBorder? _borderOf(WidgetTester tester) {
  final containers = tester
      .widgetList<Container>(find.byType(Container))
      .where((c) => c.decoration is BoxDecoration)
      .toList();
  return (containers.last.decoration! as BoxDecoration).border;
}

void main() {
  group('EmberButton · default(§8.3 按钮表第一行)', () {
    testWidgets('主按钮:brand.default 实底 + brand.on 文字 + 高 52 + emberGlow', (tester) async {
      await pumpEmber(tester, EmberButton(label: '保存', onPressed: () {}));
      expect(_backgroundOf(tester), EmberColors.light.brandDefault);
      expect(_labelColor(tester, '保存'), EmberColors.light.brandOn);
      expect(tester.getSize(find.byType(EmberButton)).height, tokens.sizeControlHeight);
      // 主按钮才有光晕(§2 品牌签名元素)
      expect(find.byType(EmberGlow), findsOneWidget);
    });

    testWidgets('次按钮:surface.card 底 + 1px border.divider + text.primary 字', (tester) async {
      await pumpEmber(
        tester,
        EmberButton(
          label: '取消',
          variant: EmberButtonVariant.secondary,
          onPressed: () {},
        ),
      );
      expect(_backgroundOf(tester), EmberColors.light.surfaceCard);
      expect(_labelColor(tester, '取消'), EmberColors.light.textPrimary);
      expect((_borderOf(tester)! as Border).top.color, EmberColors.light.borderDivider);
      expect(find.byType(EmberGlow), findsNothing);
    });

    testWidgets('文字按钮:brand.default 字,无底', (tester) async {
      await pumpEmber(
        tester,
        EmberButton(
          label: '跳过',
          variant: EmberButtonVariant.text,
          onPressed: () {},
        ),
      );
      expect(_labelColor(tester, '跳过'), EmberColors.light.brandDefault);
      expect(_backgroundOf(tester), Colors.transparent);
    });

    testWidgets('危险按钮:status.danger 描边 + status.danger 字', (tester) async {
      await pumpEmber(
        tester,
        EmberButton(
          label: '删除',
          variant: EmberButtonVariant.danger,
          onPressed: () {},
        ),
      );
      expect(_labelColor(tester, '删除'), EmberColors.light.statusDanger);
      expect((_borderOf(tester)! as Border).top.color, EmberColors.light.statusDanger);
    });
  });

  group('EmberButton · pressed(spring .97 + 光晕降至 50%)', () {
    testWidgets('按下缩小、抬起复原,主按钮光晕透明度减半', (tester) async {
      await pumpEmber(tester, EmberButton(label: '保存', onPressed: () {}));
      final finder = find.byType(EmberButton);
      expect(pressableScale(tester, finder), closeTo(1, 0.001));

      final gesture = await tester.startGesture(tester.getCenter(finder));
      // onTapDown 要等手势竞技场判定(TapGestureRecognizer 的 kPressTimeout=100ms),
      // 之后弹簧还要若干帧才走到目标值,所以统一用 pumpFrames 推进。
      await pumpFrames(tester, frames: 8, step: const Duration(milliseconds: 32));
      expect(pressableScale(tester, finder), lessThan(1));
      final glowPressed = tester.widget<EmberGlow>(find.byType(EmberGlow)).opacity;
      expect(glowPressed, closeTo(0.06, 1e-9));

      await gesture.up();
      await pumpFrames(tester, frames: 12, step: const Duration(milliseconds: 32));
      expect(pressableScale(tester, finder), closeTo(1, 0.05));
    });

    testWidgets('次按钮按下改 surface.sunken 底', (tester) async {
      await pumpEmber(
        tester,
        EmberButton(
          label: '取消',
          variant: EmberButtonVariant.secondary,
          onPressed: () {},
        ),
      );
      final gesture =
          await tester.startGesture(tester.getCenter(find.byType(EmberButton)));
      await tester.pump();
      expect(_backgroundOf(tester), EmberColors.light.surfaceSunken);
      await gesture.up();
      await tester.pump();
    });

    testWidgets('危险按钮按下变实底 + status.onDanger 字', (tester) async {
      await pumpEmber(
        tester,
        EmberButton(
          label: '删除',
          variant: EmberButtonVariant.danger,
          onPressed: () {},
        ),
      );
      final gesture =
          await tester.startGesture(tester.getCenter(find.byType(EmberButton)));
      await tester.pump();
      expect(_backgroundOf(tester), EmberColors.light.statusDanger);
      expect(_labelColor(tester, '删除'), EmberColors.light.statusOnDanger);
      await gesture.up();
      await tester.pump();
    });
  });

  group('EmberButton · focus(外扩 2px + 2px 间隙)', () {
    testWidgets('键盘聚焦出现焦点环,颜色 brand.default', (tester) async {
      await pumpEmber(
        tester,
        EmberButton(label: '保存', onPressed: () {}, autofocus: true),
      );
      await tester.pump();
      expect(find.byType(EmberFocusRing), findsOneWidget);

      final box = tester.widget<DecoratedBox>(
        find
            .descendant(
              of: find.byType(EmberFocusRing),
              matching: find.byType(DecoratedBox),
            )
            .last,
      );
      final ring = (box.decoration as BoxDecoration).border! as Border;
      expect(ring.top.color, EmberColors.light.brandDefault);
      expect(ring.top.width, 2);
    });

    testWidgets('危险按钮的焦点环用 status.danger(§8.3)', (tester) async {
      await pumpEmber(
        tester,
        EmberButton(
          label: '删除',
          variant: EmberButtonVariant.danger,
          onPressed: () {},
          autofocus: true,
        ),
      );
      await tester.pump();
      final box = tester.widget<DecoratedBox>(
        find
            .descendant(
              of: find.byType(EmberFocusRing),
              matching: find.byType(DecoratedBox),
            )
            .last,
      );
      final ring = (box.decoration as BoxDecoration).border! as Border;
      expect(ring.top.color, EmberColors.light.statusDanger);
    });
  });

  group('EmberButton · disabled', () {
    testWidgets('底色 surface.sunken、字 text.tertiary、无光晕、读屏 isEnabled=false', (tester) async {
      final handle = tester.ensureSemantics();
      var tapped = 0;
      await pumpEmber(tester, EmberButton(label: '保存', onPressed: null));
      expect(_backgroundOf(tester), EmberColors.light.surfaceSunken);
      expect(_labelColor(tester, '保存'), EmberColors.light.textTertiary);
      expect(find.byType(EmberGlow), findsNothing);

      await tester.tap(find.byType(EmberButton));
      await tester.pump();
      expect(tapped, 0);

      expectSemanticallyEnabled(tester, find.byType(EmberButton).first, enabled: false);
      expectSemanticallyButton(tester, find.byType(EmberButton).first, isButton: true);
      handle.dispose();
    });
  });

  group('EmberButton · loading', () {
    testWidgets('保持底与字、尾随 16 转圈、点击无效', (tester) async {
      final handle = tester.ensureSemantics();
      var tapped = 0;
      await pumpEmber(
        tester,
        EmberButton(label: '保存', loading: true, onPressed: () => tapped++),
      );
      expect(find.byType(CircularProgressIndicator), findsOneWidget);
      expect(tester.getSize(find.byType(CircularProgressIndicator)),
          const Size(tokens.sizeIcon16, tokens.sizeIcon16));
      expect(_labelColor(tester, '保存'), EmberColors.light.brandOn);

      await tester.tap(find.byType(EmberButton));
      await tester.pump();
      expect(tapped, 0, reason: 'loading 时必须禁点击');

      expectSemanticallyEnabled(tester, find.byType(EmberButton).first, enabled: false);
      // 读屏要能听到「处理中」,而不是空白标签
      expect(
        tester
            .getSemantics(find.byType(EmberButton).first)
            .getSemanticsData()
            .label,
        contains('处理中'),
      );
      handle.dispose();
    });

    testWidgets('文字按钮 loading:转圈替换文字', (tester) async {
      await pumpEmber(
        tester,
        EmberButton(
          label: '重发',
          variant: EmberButtonVariant.text,
          loading: true,
          onPressed: () {},
        ),
      );
      expect(find.text('重发'), findsNothing);
      expect(find.byType(CircularProgressIndicator), findsOneWidget);
    });
  });
}
