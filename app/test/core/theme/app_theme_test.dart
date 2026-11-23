import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/theme/app_shadows.dart';
import 'package:chatapp_app/core/theme/app_theme.dart';
import 'package:chatapp_app/core/theme/app_typography.dart';
import 'package:chatapp_app/core/theme/ember_colors.dart';
import 'package:chatapp_app/core/theme/tokens.g.dart' as tokens;

void main() {
  test('主题:页面底取 surface.page,全局仍是 SpaceGrotesk(§4 属 E-5)', () {
    final theme = buildAppTheme(brightness: Brightness.light);
    expect(theme.scaffoldBackgroundColor, EmberColors.light.surfacePage);
    expect(theme.canvasColor, EmberColors.light.surfacePage);
    expect(theme.textTheme.bodyMedium?.fontFamily, 'SpaceGrotesk');
    expect(AppText.body.fontFamily, 'SpaceGrotesk');
    expect(AppText.body.fontFamilyFallback, contains('PingFang SC'));
  });

  test('colorScheme 逐槽位取 token,primary 是 brand.default 原值(禁止 fromSeed)', () {
    final theme = buildAppTheme(brightness: Brightness.light);
    final scheme = theme.colorScheme;
    expect(scheme.brightness, Brightness.light);
    // fromSeed 会把 brand 派生成一整套调色板,primary 就不会等于原值 —— 这条断言
    // 正是「不许用种子算法」的机械判据。
    expect(scheme.primary, EmberColors.light.brandDefault);
    expect(scheme.onPrimary, EmberColors.light.brandOn);
    expect(scheme.surface, EmberColors.light.surfaceCard);
    expect(scheme.onSurface, EmberColors.light.textPrimary);
    expect(scheme.error, EmberColors.light.statusDanger);
    expect(scheme.onError, EmberColors.light.statusOnDanger);
    expect(scheme.outlineVariant, EmberColors.light.borderDivider);
  });

  test('EmberColors 注册进 extensions', () {
    expect(
      buildAppTheme(brightness: Brightness.light).extension<EmberColors>(),
      EmberColors.light,
    );
    expect(
      buildAppTheme(brightness: Brightness.dark).extension<EmberColors>(),
      EmberColors.dark,
    );
  });

  test('暗色主题:brightness / 底色 / 扩展三处一致', () {
    final theme = buildAppTheme(brightness: Brightness.dark);
    expect(theme.colorScheme.brightness, Brightness.dark);
    expect(theme.scaffoldBackgroundColor, EmberColors.dark.surfacePage);
    expect(theme.extension<EmberColors>(), EmberColors.dark);
  });

  test('SnackBar / Toast 底色 = overlay.scrim(§8.2),两模式不同', () {
    final light = buildAppTheme(brightness: Brightness.light);
    final dark = buildAppTheme(brightness: Brightness.dark);
    expect(light.snackBarTheme.backgroundColor, EmberColors.light.overlayScrim);
    expect(dark.snackBarTheme.backgroundColor, EmberColors.dark.overlayScrim);
    expect(
      light.snackBarTheme.backgroundColor,
      isNot(dark.snackBarTheme.backgroundColor),
    );
    // 圆角走 token(§8.3 Toast 用 radius.md)
    expect(
      light.snackBarTheme.shape,
      RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(tokens.radiusMd),
      ),
    );
  });

  test('lib/ 里不允许出现 ColorScheme.fromSeed(规范 §8 / 工单 E-2 明令)', () {
    final hits = <String>[];
    for (final entity in Directory('lib').listSync(recursive: true)) {
      if (entity is! File || !entity.path.endsWith('.dart')) continue;
      // 注释里提到这个 API 是正常的(本规范的禁令就写在注释里),只抓真调用。
      for (final line in entity.readAsLinesSync()) {
        final code = line.split('//').first;
        if (code.contains('ColorScheme.fromSeed')) hits.add('${entity.path}: $line');
      }
    }
    expect(hits, isEmpty, reason: '种子算法会生成规范里没有的颜色:${hits.join(', ')}');
  });

  test('阴影层级来自生成物里的 elevation token', () {
    expect(AppShadows.card.single.offset, const Offset(0, 2));
    expect(AppShadows.card.single.blurRadius, 8);
    expect(AppShadows.floatingBar.single.offset, const Offset(0, 10));
    expect(AppShadows.floatingBar.single.blurRadius, 24);
  });
}
