import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/theme/app_gradients.dart';
import 'package:chatapp_app/core/theme/app_theme.dart';
import 'package:chatapp_app/core/theme/ember_colors.dart';
import 'package:chatapp_app/core/theme/ember_theme_context.dart';
import 'package:chatapp_app/core/theme/tokens.g.dart' as tokens;

/// WCAG 2.x 对比度(只用于本文件的「文字能不能读」断言)。
///
/// 真正的门禁是 `scripts/design_contrast.py`(阈值 owner 是 spec §3.4);这里复算
/// 一遍是为了在**改 token 时 App 侧会立刻红**,而不是等 contract 轨才发现。
double _contrast(Color foreground, Color background) {
  final l1 = foreground.computeLuminance();
  final l2 = background.computeLuminance();
  final lighter = l1 > l2 ? l1 : l2;
  final darker = l1 > l2 ? l2 : l1;
  return (lighter + 0.05) / (darker + 0.05);
}

void main() {
  group('EmberColors:值只来自生成物', () {
    test('浅色 20 个语义字段逐项等于 tokens.g.dart 的 *Light 常量', () {
      const expected = <String, Color>{
        'surfacePage': tokens.colorSurfacePageLight,
        'surfaceCard': tokens.colorSurfaceCardLight,
        'surfaceSunken': tokens.colorSurfaceSunkenLight,
        'textPrimary': tokens.colorTextPrimaryLight,
        'textSecondary': tokens.colorTextSecondaryLight,
        'textTertiary': tokens.colorTextTertiaryLight,
        'borderDivider': tokens.colorBorderDividerLight,
        'borderStrong': tokens.colorBorderStrongLight,
        'brandDefault': tokens.colorBrandDefaultLight,
        'brandOn': tokens.colorBrandOnLight,
        'accentDefault': tokens.colorAccentDefaultLight,
        'accentOn': tokens.colorAccentOnLight,
        'statusDanger': tokens.colorStatusDangerLight,
        'statusOnDanger': tokens.colorStatusOnDangerLight,
        'statusSuccess': tokens.colorStatusSuccessLight,
        'statusOnSuccess': tokens.colorStatusOnSuccessLight,
        'statusWarning': tokens.colorStatusWarningLight,
        'statusOnWarning': tokens.colorStatusOnWarningLight,
        'statusInfo': tokens.colorStatusInfoLight,
        'overlayScrim': tokens.colorOverlayScrimLight,
      };
      expect(EmberColors.light.toMap(), expected);
    });

    test('深色 20 个语义字段逐项等于 tokens.g.dart 的 *Dark 常量', () {
      const expected = <String, Color>{
        'surfacePage': tokens.colorSurfacePageDark,
        'surfaceCard': tokens.colorSurfaceCardDark,
        'surfaceSunken': tokens.colorSurfaceSunkenDark,
        'textPrimary': tokens.colorTextPrimaryDark,
        'textSecondary': tokens.colorTextSecondaryDark,
        'textTertiary': tokens.colorTextTertiaryDark,
        'borderDivider': tokens.colorBorderDividerDark,
        'borderStrong': tokens.colorBorderStrongDark,
        'brandDefault': tokens.colorBrandDefaultDark,
        'brandOn': tokens.colorBrandOnDark,
        'accentDefault': tokens.colorAccentDefaultDark,
        'accentOn': tokens.colorAccentOnDark,
        'statusDanger': tokens.colorStatusDangerDark,
        'statusOnDanger': tokens.colorStatusOnDangerDark,
        'statusSuccess': tokens.colorStatusSuccessDark,
        'statusOnSuccess': tokens.colorStatusOnSuccessDark,
        'statusWarning': tokens.colorStatusWarningDark,
        'statusOnWarning': tokens.colorStatusOnWarningDark,
        'statusInfo': tokens.colorStatusInfoDark,
        'overlayScrim': tokens.colorOverlayScrimDark,
      };
      expect(EmberColors.dark.toMap(), expected);
    });

    test('浅/深两套字段名集合完全一致(少一个深色值 = 深色下静默回落浅色)', () {
      expect(
        EmberColors.light.toMap().keys.toSet(),
        EmberColors.dark.toMap().keys.toSet(),
      );
      expect(EmberColors.light.toMap().length, 20);
    });

    test('中性色六项在深色下确实换值', () {
      const neutrals = [
        'surfacePage',
        'surfaceCard',
        'surfaceSunken',
        'textPrimary',
        'textSecondary',
        'textTertiary',
      ];
      final light = EmberColors.light.toMap();
      final dark = EmberColors.dark.toMap();
      for (final name in neutrals) {
        expect(dark[name], isNot(equals(light[name])), reason: '中性色 $name 没有换值');
      }
    });
  });

  group('EmberColors:spec §3.4 的两条硬规则', () {
    test('深色主按钮 = 亮底 + 近黑文字;浅色 = 深底 + 白字', () {
      // 浅色:白字压在朱砂上,WCAG ≥ 4.5
      expect(
        _contrast(EmberColors.light.brandOn, EmberColors.light.brandDefault),
        greaterThanOrEqualTo(4.5),
      );
      // 深色:亮朱砂配白字只有 2.17(必挂),所以 on 色必须翻成近黑
      expect(EmberColors.dark.brandOn.computeLuminance(), lessThan(0.05));
      expect(
        _contrast(EmberColors.dark.brandOn, EmberColors.dark.brandDefault),
        greaterThanOrEqualTo(4.5),
      );
    });

    test('次级文字在两个模式下都够读(≥ 4.5,且比三级文字更强)', () {
      for (final colors in [EmberColors.light, EmberColors.dark]) {
        final page = colors.surfacePage;
        expect(
          _contrast(colors.textSecondary, page),
          greaterThanOrEqualTo(4.5),
          reason: 'text.secondary 在 ${colors == EmberColors.light ? '浅' : '深'}色底上不够读',
        );
        expect(
          _contrast(colors.textSecondary, page),
          greaterThan(_contrast(colors.textTertiary, page)),
        );
      }
    });
  });

  group('过渡别名(心跳期字段名 → Ember 语义角色)', () {
    test('每个别名都指向对应语义字段,不复制色值', () {
      for (final colors in [EmberColors.light, EmberColors.dark]) {
        expect(colors.bgPage, colors.surfacePage);
        expect(colors.bgCard, colors.surfaceCard);
        expect(colors.divider, colors.borderDivider);
        expect(colors.text1, colors.textPrimary);
        expect(colors.text2, colors.textSecondary);
        expect(colors.text3, colors.textTertiary);
        expect(colors.brand, colors.brandDefault);
        expect(colors.heartOrange, colors.accentDefault);
        // §18.2:violet 与 systemBlue 合并成 status.info 单色
        expect(colors.violet, colors.statusInfo);
        expect(colors.systemBlue, colors.statusInfo);
        expect(colors.green, colors.statusSuccess);
        expect(colors.amber, colors.statusWarning);
        expect(colors.danger, colors.statusDanger);
        expect(colors.photoScrim, colors.overlayScrim);
        expect(colors.success, colors.statusSuccess);
        expect(colors.warning, colors.statusWarning);
      }
    });
  });

  group('取板与插值', () {
    test('of() 按亮度取板', () {
      expect(EmberColors.of(Brightness.light), same(EmberColors.light));
      expect(EmberColors.of(Brightness.dark), same(EmberColors.dark));
    });

    test('lerp 两端点取自身,other 为 null 时返回自身', () {
      final start = EmberColors.light.lerp(EmberColors.dark, 0);
      expect(start.surfacePage, EmberColors.light.surfacePage);
      final end = EmberColors.light.lerp(EmberColors.dark, 1);
      expect(end.surfacePage, EmberColors.dark.surfacePage);
      expect(
        EmberColors.light.lerp(null, 0.5).surfacePage,
        EmberColors.light.surfacePage,
      );
    });

    test('copyWith 只改传入字段', () {
      final patched = EmberColors.light.copyWith(brandDefault: const Color(0xFF123456));
      expect(patched.brandDefault, const Color(0xFF123456));
      expect(patched.surfacePage, EmberColors.light.surfacePage);
      // 过渡别名跟着语义字段走,不会与字段脱节
      expect(patched.brand, patched.brandDefault);
    });
  });

  group('主题注册与 context.ember', () {
    testWidgets('Theme.of(context).extension<EmberColors>() 非空且等于当前板', (tester) async {
      late EmberColors fromTheme;
      await tester.pumpWidget(
        MaterialApp(
          theme: buildAppTheme(brightness: Brightness.light),
          home: Builder(builder: (context) {
            fromTheme = Theme.of(context).extension<EmberColors>()!;
            return const SizedBox.shrink();
          }),
        ),
      );
      expect(fromTheme, EmberColors.light);
    });

    testWidgets('context.ember 在浅/暗主题下分别取到对应板;context.heart 是同一个', (tester) async {
      for (final entry in {
        Brightness.light: EmberColors.light,
        Brightness.dark: EmberColors.dark,
      }.entries) {
        late EmberColors viaEmber;
        late EmberColors viaHeart;
        await tester.pumpWidget(
          MaterialApp(
            theme: buildAppTheme(brightness: entry.key),
            // AnimatedTheme 默认会 lerp 两个主题,切换瞬间取到的是插值板;
            // 这里要断言「最终色板」,所以把过渡时长归零。
            themeAnimationDuration: Duration.zero,
            home: Builder(builder: (context) {
              viaEmber = context.ember;
              viaHeart = context.heart;
              return const SizedBox.shrink();
            }),
          ),
        );
        expect(viaEmber, entry.value, reason: '${entry.key} 取错了色板');
        expect(viaHeart, entry.value, reason: '${entry.key} 的过渡别名取错了色板');
      }
    });
  });

  group('过渡渐变(spec §18.1 #2:渐变全部取消)', () {
    test('heartOf 两端是 brand.default → accent.default', () {
      final gradient = AppGradients.heartOf(EmberColors.light);
      expect(gradient.colors, [
        EmberColors.light.brandDefault,
        EmberColors.light.accentDefault,
      ]);
      expect(gradient.begin, Alignment.topLeft);
      expect(gradient.end, Alignment.bottomRight);
    });

    test('systemOf 已退化为 status.info 单色(§18.2 的语义合并)', () {
      final gradient = AppGradients.systemOf(EmberColors.dark);
      expect(gradient.colors.toSet(), {EmberColors.dark.statusInfo});
    });

    test('heartSweepOf 与 heartOf 同色', () {
      expect(
        AppGradients.heartSweepOf(EmberColors.light).colors,
        AppGradients.heartOf(EmberColors.light).colors,
      );
    });
  });
}
