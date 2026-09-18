import 'package:flutter/material.dart';

import 'app_colors.dart';

/// 「心跳」规则 §2.1 渐变(135° = 左上→右下)。
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
}
