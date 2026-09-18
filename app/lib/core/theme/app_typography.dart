import 'package:flutter/material.dart';

/// 「心跳」规则 §3:中文走系统字体 fallback,拉丁/数字走 Space Grotesk。
const kFontFallback = ['PingFang SC', 'MiSans', 'HarmonyOS Sans', 'sans-serif'];

TextStyle _sg({
  required double size,
  required FontWeight weight,
  double? spacing,
  double? height,
}) =>
    TextStyle(
      fontFamily: 'SpaceGrotesk',
      fontFamilyFallback: kFontFallback,
      fontSize: size,
      fontWeight: weight,
      letterSpacing: spacing,
      height: height,
    );

/// 规则 §3.2 字阶。
abstract final class AppText {
  static final display = _sg(size: 32, weight: FontWeight.w800, spacing: -0.64, height: 1.2); // -0.02em
  static final title = _sg(size: 20, weight: FontWeight.w700, spacing: -0.2, height: 1.2); // -0.01em
  static final subtitle = _sg(size: 16, weight: FontWeight.w600, height: 1.2);
  static final body = _sg(size: 15, weight: FontWeight.w500, height: 1.45);
  static final caption = _sg(size: 13, weight: FontWeight.w400, height: 1.45);
  static final micro = _sg(size: 12, weight: FontWeight.w400);
  static final badge = _sg(size: 11, weight: FontWeight.w700); // 角标专用
  static final navLabel = _sg(size: 10, weight: FontWeight.w400); // 底栏未选中(§7)
  static final navLabelSelected = _sg(size: 10, weight: FontWeight.w700); // 底栏选中(§7)
}
