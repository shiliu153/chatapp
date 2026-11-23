import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/theme/ember_colors.dart';
import 'package:chatapp_app/core/ui/ember_avatar.dart';
import 'package:chatapp_app/core/ui/ember_component_sizes.dart';
import 'package:chatapp_app/core/ui/ember_glow.dart';
import 'package:chatapp_app/core/ui/ember_skeleton.dart';

import 'ember_test_kit.dart';

void main() {
  group('EmberAvatar · default(§8.3 头像表)', () {
    testWidgets('六档尺寸都渲染成正方形圆形,无照片时用首字', (tester) async {
      for (final size in EmberAvatar.allowedSizes) {
        await pumpEmber(tester, EmberAvatar(name: '小明', size: size));
        expect(tester.getSize(find.byType(EmberAvatar)), Size(size, size));
        expect(find.text('小'), findsOneWidget);
      }
    });

    testWidgets('空昵称回落成「?」,不留空圈', (tester) async {
      await pumpEmber(tester, const EmberAvatar());
      expect(find.text('?'), findsOneWidget);
    });

    testWidgets('不合规尺寸直接断言失败(只能取 §8.2 的六档)', (tester) async {
      await pumpEmber(tester, const EmberAvatar(size: 37));
      expect(tester.takeException(), isAssertionError);
    });

    testWidgets('柔色底取 surface.sunken,首字取 text.secondary', (tester) async {
      await pumpEmber(tester, const EmberAvatar(name: '小明'));
      final container = tester.widget<Container>(
        find.descendant(of: find.byType(EmberAvatar), matching: find.byType(Container)).first,
      );
      final decoration = container.decoration! as BoxDecoration;
      expect(decoration.color, EmberColors.light.surfaceSunken);
      expect(decoration.shape, BoxShape.circle);
      expect(
        tester.widget<Text>(find.text('小')).style!.color,
        EmberColors.light.textSecondary,
      );
    });
  });

  group('EmberAvatar · selected(在线 / 新配对)', () {
    testWidgets('在线点 status.success,常规头像直径 11、小头像 8', (tester) async {
      await pumpEmber(
        tester,
        const EmberAvatar(name: '小明', size: EmberComponentSizes.avatarMd, online: true),
      );
      final dot = tester
          .widgetList<Container>(find.byType(Container))
          .firstWhere((c) =>
              (c.decoration as BoxDecoration?)?.color ==
              EmberColors.light.statusSuccess);
      expect(tester.getSize(find.byWidget(dot)), const Size(11, 11));

      await pumpEmber(
        tester,
        const EmberAvatar(name: '小明', size: EmberComponentSizes.avatarSm, online: true),
      );
      final small = tester
          .widgetList<Container>(find.byType(Container))
          .firstWhere((c) =>
              (c.decoration as BoxDecoration?)?.color ==
              EmberColors.light.statusSuccess);
      expect(tester.getSize(find.byWidget(small)), const Size(8, 8));
    });

    testWidgets('新配对接 emberGlow 环(2.5px),不画渐变', (tester) async {
      await pumpEmber(tester, const EmberAvatar(name: '小明', isNewMatch: true));
      final glow = tester.widget<EmberGlow>(find.byType(EmberGlow));
      expect(glow.shape, EmberGlowShape.circle);
      expect(glow.spread, EmberComponentSizes.newMatchRing);
    });

    testWidgets('读屏标签带上「在线」「新配对」(颜色不是唯一线索,§8.4)', (tester) async {
      final handle = tester.ensureSemantics();
      await pumpEmber(
        tester,
        const EmberAvatar(name: '小明', online: true, isNewMatch: true),
      );
      final data = semanticsOf(tester, find.byType(EmberAvatar));
      expect(data.label, contains('小明'));
      expect(data.label, contains('在线'));
      expect(data.label, contains('新配对'));
      handle.dispose();
    });
  });

  group('EmberAvatar · loading', () {
    testWidgets('加载态是圆形骨架,不显示首字', (tester) async {
      await pumpEmber(tester, const EmberAvatar(name: '小明', loading: true));
      final skeleton = tester.widget<EmberSkeleton>(find.byType(EmberSkeleton));
      expect(skeleton.shape, BoxShape.circle);
      expect(find.text('小'), findsNothing);
    });
  });

  group('EmberAvatar · disabled(§8.1 头像无此状态)', () {
    testWidgets('头像不是可点控件:没有按压层、没有按钮语义', (tester) async {
      final handle = tester.ensureSemantics();
      await pumpEmber(tester, const EmberAvatar(name: '小明'));
      expectSemanticallyButton(tester, find.byType(EmberAvatar), isButton: false);
      // §8.1 的头像行只有 default / loading / selected 三态 —— 没有 pressed/disabled,
      // 所以组件也不提供这两种参数。
      handle.dispose();
    });
  });
}
