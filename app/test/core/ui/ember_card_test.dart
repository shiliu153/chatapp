import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/theme/app_shadows.dart';
import 'package:chatapp_app/core/theme/ember_colors.dart';
import 'package:chatapp_app/core/theme/tokens.g.dart' as tokens;
import 'package:chatapp_app/core/ui/ember_card.dart';
import 'package:chatapp_app/core/ui/ember_pressable.dart';
import 'package:chatapp_app/core/ui/ember_skeleton.dart';

import 'ember_test_kit.dart';

BoxDecoration _decoration(WidgetTester tester) {
  final box = tester.widget<DecoratedBox>(
    find
        .descendant(
          of: find.byType(EmberCard),
          matching: find.byType(DecoratedBox),
        )
        .first,
  );
  return box.decoration as BoxDecoration;
}

void main() {
  group('EmberCard · default(§8.3 卡片表)', () {
    testWidgets('浅色:surface.card + radius.lg + elev.1 + 内边距 20', (tester) async {
      await pumpEmber(tester, const EmberCard(child: Text('卡片')));
      final decoration = _decoration(tester);
      expect(decoration.color, EmberColors.light.surfaceCard);
      expect(
        decoration.borderRadius,
        BorderRadius.circular(tokens.radiusLg),
      );
      expect(decoration.boxShadow, AppShadows.card);
      expect(decoration.border, isNull);

      final padding = tester.widget<Padding>(
        find.descendant(of: find.byType(EmberCard), matching: find.byType(Padding)).first,
      );
      expect(padding.padding, EdgeInsets.all(tokens.space20));
    });

    testWidgets('深色:不用阴影,改 border.divider 描边(§5.3)', (tester) async {
      await pumpEmber(
        tester,
        const EmberCard(child: Text('卡片')),
        brightness: Brightness.dark,
      );
      final decoration = _decoration(tester);
      expect(decoration.boxShadow, isNull, reason: '深色模式不允许套阴影');
      final border = decoration.border! as Border;
      expect(border.top.color, EmberColors.dark.borderDivider);
    });
  });

  group('EmberCard · pressed(scale .98,阴影不变)', () {
    testWidgets('按下缩小到 .98 附近,底色与阴影不变', (tester) async {
      await pumpEmber(
        tester,
        EmberCard(onTap: () {}, child: const Text('可点卡片')),
      );
      final finder = find.byType(EmberCard);
      final gesture = await tester.startGesture(tester.getCenter(finder));
      // onTapDown 要等手势竞技场判定(TapGestureRecognizer 的 kPressTimeout=100ms),
      // 之后弹簧还要若干帧才走到目标值,所以统一用 pumpFrames 推进。
      await pumpFrames(tester, frames: 8, step: const Duration(milliseconds: 32));
      expect(pressableScale(tester, finder), lessThan(1));
      expect(_decoration(tester).color, EmberColors.light.surfaceCard);
      expect(_decoration(tester).boxShadow, AppShadows.card);
      await gesture.up();
      await tester.pump();
    });
  });

  group('EmberCard · selected(2px brand 描边,不放大)', () {
    testWidgets('选中态描边 2px brand.default,尺寸与未选中一致', (tester) async {
      await pumpEmber(tester, const EmberCard(child: SizedBox(height: 40, width: 100)));
      final normal = tester.getSize(find.byType(EmberCard));
      await pumpEmber(
        tester,
        const EmberCard(selected: true, child: SizedBox(height: 40, width: 100)),
      );
      final ring = tester
          .widgetList<DecoratedBox>(
            find.descendant(of: find.byType(EmberCard), matching: find.byType(DecoratedBox)),
          )
          .map((d) => d.decoration)
          .whereType<BoxDecoration>()
          .map((d) => d.border)
          .whereType<Border>()
          .firstWhere((b) => b.top.color == EmberColors.light.brandDefault);
      expect(ring.top.width, 2);
      expect(tester.getSize(find.byType(EmberCard)), normal);
    });
  });

  group('EmberCard · loading(骨架)', () {
    testWidgets('内容换成骨架,且子内容不渲染', (tester) async {
      await pumpEmber(
        tester,
        const EmberCard(loading: true, child: Text('不该出现')),
      );
      expect(find.byType(EmberSkeleton), findsWidgets);
      expect(find.text('不该出现'), findsNothing);
    });
  });

  group('EmberCard · disabled(§8.1 卡片无此状态)', () {
    testWidgets('静态卡片不可点:不包按压层、点击不触发回调', (tester) async {
      final handle = tester.ensureSemantics();
      var taps = 0;
      await pumpEmber(tester, const EmberCard(child: Text('静态')));
      expect(find.byType(EmberPressable), findsNothing);
      await tester.tap(find.text('静态'));
      await tester.pump();
      expect(taps, 0);
      handle.dispose();
    });

    testWidgets('可点卡片带读屏标签,按「行」而不是「按钮」播报', (tester) async {
      final handle = tester.ensureSemantics();
      var taps = 0;
      await pumpEmber(
        tester,
        EmberCard(
          onTap: () => taps++,
          semanticsLabel: '小明的动态',
          child: const Text('小明的动态'),
        ),
      );
      final data = semanticsOf(tester, find.byType(EmberPressable).first);
      expect(data.label, contains('小明的动态'));
      expectSemanticallyButton(tester, find.byType(EmberPressable).first, isButton: false);
      await tester.tap(find.text('小明的动态'));
      await tester.pump();
      expect(taps, 1);
      handle.dispose();
    });
  });
}
