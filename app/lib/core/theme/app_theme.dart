import 'package:flutter/material.dart';

import 'app_radius.dart';
import 'app_typography.dart';
import 'heart_colors.dart';

/// SnackBar / Toast 深色浮层底色:浅色主题下是「比文字色更浅一档的深灰」,
/// 深色主题下要反过来比 bgCard 更亮一档,否则在 #0E1015 页面上糊成一片。
const _snackBgLight = Color(0xEB16181D); // rgba(22,24,29,.92)
const _snackBgDark = Color(0xEB2B303C);

/// 组装全局主题(规则 §8):colorScheme 从 brand 派生;全局字体;SnackBar 贴近 §7 Toast。
///
/// [brightness] 必填:暗色模式(F 批)之后主题不再是单例,调用方必须明确要哪一套,
/// 免得漏传时静默拿到浅色、暗色页面上冒出白块。
ThemeData buildAppTheme({required Brightness brightness}) {
  final colors = HeartColors.of(brightness);
  final base = ThemeData(
    colorScheme: ColorScheme.fromSeed(
      seedColor: colors.brand,
      brightness: brightness,
    ),
    useMaterial3: true,
    fontFamily: 'SpaceGrotesk',
    fontFamilyFallback: kFontFallback,
    extensions: [colors],
  );
  return base.copyWith(
    scaffoldBackgroundColor: colors.bgPage,
    snackBarTheme: SnackBarThemeData(
      backgroundColor:
          brightness == Brightness.dark ? _snackBgDark : _snackBgLight,
      contentTextStyle: AppText.caption.copyWith(color: Colors.white),
      behavior: SnackBarBehavior.floating,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(AppRadius.input),
      ),
    ),
  );
}
