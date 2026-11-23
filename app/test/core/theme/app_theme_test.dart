import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/theme/app_shadows.dart';
import 'package:chatapp_app/core/theme/app_theme.dart';
import 'package:chatapp_app/core/theme/app_typography.dart';
import 'package:chatapp_app/core/theme/ember_colors.dart';
import 'package:chatapp_app/core/theme/tokens.g.dart' as tokens;

void main() {
  test('主题:页面底取 surface.page;全局字族 = token 的 body 链(Ember §4.1)', () {
    final theme = buildAppTheme(brightness: Brightness.light);
    expect(theme.scaffoldBackgroundColor, EmberColors.light.surfacePage);
    expect(theme.canvasColor, EmberColors.light.surfacePage);
    // 全局不再钉死某个具名字族(Space Grotesk 已随「心跳」一起退役):主字族交给平台
    // 默认(Typography 会填 Roboto / SF),中文按 token `font.family.body` 链回落。
    // 断言「不是 SpaceGrotesk」而不是「是 null」—— ThemeData 自己会填平台默认值。
    expect(theme.textTheme.bodyMedium?.fontFamily, isNot('SpaceGrotesk'));
    expect(theme.textTheme.bodyMedium?.fontFamilyFallback, contains('PingFang SC'));
    expect(AppText.body.fontFamily, isNull);
    expect(AppText.body.fontFamilyFallback, contains('PingFang SC'));
    // 标题两档才是 Fraunces(§4.1「只用于 display / title」)
    expect(AppText.display.fontFamily, tokens.fontFamilyDisplay);
    expect(AppText.title.fontFamily, tokens.fontFamilyDisplay);
    expect(AppText.subtitle.fontFamily, isNull);
    // §4.2 字阶:字号 / 行高来自生成物,不是页面里的魔法数
    expect(AppText.body.fontSize, tokens.fontSizeBody);
    expect(AppText.body.height, tokens.fontLineHeightBody);
    expect(AppText.display.fontSize, tokens.fontSizeDisplay);
    expect(AppText.display.height, tokens.fontLineHeightDisplay);
    expect(AppText.micro.fontSize, tokens.fontSizeMicro);
    expect(AppText.badge.fontSize, tokens.fontSizeMicro); // §18.4 两档合一
  });

  test('Fraunces 是可变字体:标题档走 wght 轴而不是假粗体', () {
    // pubspec 里刻意没给 Fraunces 写 weight(写了就等于声明「只有那个字重」),
    // 所以真实字重必须靠 fontVariations 驱动 —— 缺了它 32/w700 会是描边加粗的衬线。
    expect(AppText.display.fontVariations, isNotNull);
    expect(AppText.display.fontVariations!.single.axis, 'wght');
    expect(AppText.display.fontVariations!.single.value, 700);
    expect(AppText.title.fontVariations!.single.value, 600);
    // 正文档不走可变轴(系统字族自己会挑)
    expect(AppText.body.fontVariations, isNull);
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
