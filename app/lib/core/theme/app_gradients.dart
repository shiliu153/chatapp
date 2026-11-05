import 'package:flutter/material.dart';

import 'app_colors.dart';
import 'heart_colors.dart';

/// 「心跳」规则 §2.1 渐变(135° = 左上→右下)。
///
/// 静态常量是**浅色**版本(给 const 上下文与既有 token 测试用);双主题之后取色走
/// [heartOf] / [systemOf] / [heartSweepOf],暗色下 heartOrange 会提亮一档(§2.1.1)。
abstract final class AppGradients {
  static const heart = LinearGradient(
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
    colors: [AppColors.brand, AppColors.heartOrange],
  );
  static const system = LinearGradient(
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
    colors: [AppColors.violet, AppColors.systemBlue],
  );

  /// 附录 C.2 完成度环的进度弧:与 heart 同色,但沿圆周扫过(SweepGradient)。
  static const heartSweep = SweepGradient(
    colors: [AppColors.brand, AppColors.heartOrange],
  );

  /// 主题感知的心跳渐变(粉→橙)。
  static LinearGradient heartOf(HeartColors colors) => LinearGradient(
        begin: Alignment.topLeft,
        end: Alignment.bottomRight,
        colors: [colors.brand, colors.heartOrange],
      );

  /// 主题感知的系统渐变(紫→蓝)。
  static LinearGradient systemOf(HeartColors colors) => LinearGradient(
        begin: Alignment.topLeft,
        end: Alignment.bottomRight,
        colors: [colors.violet, colors.systemBlue],
      );

  /// 主题感知的完成度环进度弧。
  static SweepGradient heartSweepOf(HeartColors colors) => SweepGradient(
        colors: [colors.brand, colors.heartOrange],
      );
}
