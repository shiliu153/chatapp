import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/theme/app_colors.dart';
import 'package:chatapp_app/core/theme/app_theme.dart';
import 'package:chatapp_app/core/theme/heart_colors.dart';
import 'package:chatapp_app/core/theme/heart_theme_context.dart';

void main() {
  group('HeartColors 两套色板', () {
    test('字段齐全:两套的字段名集合一致,且覆盖 §2.1.1 全部 14 个语义色', () {
      const expected = {
        'bgPage',
        'bgCard',
        'divider',
        'text1',
        'text2',
        'text3',
        'brand',
        'heartOrange',
        'violet',
        'systemBlue',
        'green',
        'amber',
        'danger',
        'photoScrim',
      };
      expect(HeartColors.light.toMap().keys.toSet(), expected);
      expect(HeartColors.dark.toMap().keys.toSet(), expected);
      expect(expected.length, 14);
    });

    test('浅色板与 AppColors 逐字段相等(AppColors 仍是浅色事实来源)', () {
      final map = HeartColors.light.toMap();
      expect(map['bgPage'], AppColors.bgPage);
      expect(map['bgCard'], AppColors.bgCard);
      expect(map['divider'], AppColors.divider);
      expect(map['text1'], AppColors.text1);
      expect(map['text2'], AppColors.text2);
      expect(map['text3'], AppColors.text3);
      expect(map['brand'], AppColors.brand);
      expect(map['heartOrange'], AppColors.heartOrange);
      expect(map['violet'], AppColors.violet);
      expect(map['systemBlue'], AppColors.systemBlue);
      expect(map['green'], AppColors.green);
      expect(map['amber'], AppColors.amber);
      expect(map['danger'], AppColors.danger);
      expect(map['photoScrim'], AppColors.photoScrim);
    });

    test('success / warning 仍是 green / amber 的别名', () {
      expect(HeartColors.light.success, HeartColors.light.green);
      expect(HeartColors.light.warning, HeartColors.light.amber);
      expect(HeartColors.dark.success, HeartColors.dark.green);
    });

    test('深色与浅色在 6 个中性色上确实不同', () {
      const neutrals = ['bgPage', 'bgCard', 'divider', 'text1', 'text2', 'text3'];
      final light = HeartColors.light.toMap();
      final dark = HeartColors.dark.toMap();
      for (final name in neutrals) {
        expect(dark[name], isNot(equals(light[name])), reason: '中性色 $name 没有换值');
      }
    });

    test('品牌色不变,照片 scrim 不变(§2.1.1)', () {
      expect(HeartColors.dark.brand, HeartColors.light.brand);
      expect(HeartColors.dark.photoScrim, HeartColors.light.photoScrim);
    });

    test('of() 按亮度取板', () {
      expect(HeartColors.of(Brightness.light), same(HeartColors.light));
      expect(HeartColors.of(Brightness.dark), same(HeartColors.dark));
    });

    test('lerp 两端点取自身,other 为 null 时返回自身', () {
      final mid = HeartColors.light.lerp(HeartColors.dark, 0);
      expect(mid.bgPage, HeartColors.light.bgPage);
      final end = HeartColors.light.lerp(HeartColors.dark, 1);
      expect(end.bgPage, HeartColors.dark.bgPage);
      expect(HeartColors.light.lerp(null, 0.5).bgPage, HeartColors.light.bgPage);
    });
  });

  group('主题注册与 context.heart', () {
    testWidgets('Theme.of(context).extension<HeartColors>() 非空', (tester) async {
      late HeartColors fromTheme;
      await tester.pumpWidget(
        MaterialApp(
          theme: buildAppTheme(brightness: Brightness.light),
          home: Builder(builder: (context) {
            fromTheme = Theme.of(context).extension<HeartColors>()!;
            return const SizedBox.shrink();
          }),
        ),
      );
      expect(fromTheme, HeartColors.light);
    });

    testWidgets('context.heart 在浅/暗主题下分别取到对应色板', (tester) async {
      for (final entry in {
        Brightness.light: HeartColors.light,
        Brightness.dark: HeartColors.dark,
      }.entries) {
        late HeartColors colors;
        await tester.pumpWidget(
          MaterialApp(
            theme: buildAppTheme(brightness: entry.key),
            // AnimatedTheme 默认会 lerp 两个主题,切换瞬间取到的是插值色板;
            // 这里要断言「最终色板」,所以把过渡时长归零。
            themeAnimationDuration: Duration.zero,
            home: Builder(builder: (context) {
              colors = context.heart;
              return const SizedBox.shrink();
            }),
          ),
        );
        expect(colors, entry.value, reason: '${entry.key} 取错了色板');
      }
    });

    test('scaffoldBackgroundColor 跟随色板', () {
      expect(
        buildAppTheme(brightness: Brightness.light).scaffoldBackgroundColor,
        HeartColors.light.bgPage,
      );
      expect(
        buildAppTheme(brightness: Brightness.dark).scaffoldBackgroundColor,
        HeartColors.dark.bgPage,
      );
    });
  });
}
