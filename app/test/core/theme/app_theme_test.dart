import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/theme/app_theme.dart';
import 'package:chatapp_app/core/theme/app_typography.dart';
import 'package:chatapp_app/core/theme/heart_colors.dart';

void main() {
  test('主题:全局 SpaceGrotesk + 页面底色 + SnackBar 深色浮层', () {
    final theme = buildAppTheme(brightness: Brightness.light);
    expect(theme.scaffoldBackgroundColor, HeartColors.light.bgPage);
    expect(theme.textTheme.bodyMedium?.fontFamily, 'SpaceGrotesk');
    expect(AppText.body.fontFamily, 'SpaceGrotesk');
    expect(AppText.body.fontFamilyFallback, contains('PingFang SC'));
    expect(theme.snackBarTheme.backgroundColor, const Color(0xEB16181D));
  });

  test('colorScheme 从 brand 派生', () {
    final theme = buildAppTheme(brightness: Brightness.light);
    expect(theme.colorScheme.brightness, Brightness.light);
    // fromSeed 的 primary 是 brand 的色调派生,不是原值;只断言可区分于默认紫
    expect(theme.colorScheme.primary, isNot(equals(Colors.deepPurple)));
  });

  test('暗色主题:brightness / 底色 / 扩展色板三处一致', () {
    final theme = buildAppTheme(brightness: Brightness.dark);
    expect(theme.colorScheme.brightness, Brightness.dark);
    expect(theme.scaffoldBackgroundColor, HeartColors.dark.bgPage);
    expect(theme.extension<HeartColors>(), HeartColors.dark);
    // 暗色下 Toast 底色要比 bgCard 亮一档,否则糊在页面上
    expect(theme.snackBarTheme.backgroundColor, isNot(const Color(0xEB16181D)));
  });
}
