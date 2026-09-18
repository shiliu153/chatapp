import 'package:flutter/material.dart';

import 'app_colors.dart';
import 'app_radius.dart';
import 'app_typography.dart';

/// 组装全局主题(规则 §8):colorScheme 从 brand 派生;全局字体;SnackBar 贴近 §7 Toast。
ThemeData buildAppTheme() {
  final base = ThemeData(
    colorScheme: ColorScheme.fromSeed(seedColor: AppColors.brand),
    useMaterial3: true,
    fontFamily: 'SpaceGrotesk',
    fontFamilyFallback: kFontFallback,
  );
  return base.copyWith(
    scaffoldBackgroundColor: AppColors.bgPage,
    snackBarTheme: SnackBarThemeData(
      backgroundColor: const Color(0xEB16181D), // rgba(22,24,29,.92)
      contentTextStyle: AppText.caption.copyWith(color: Colors.white),
      behavior: SnackBarBehavior.floating,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(AppRadius.input),
      ),
    ),
  );
}
