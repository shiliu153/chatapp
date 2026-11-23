import 'package:flutter/material.dart';

import '../theme/app_spacing.dart';
import '../theme/heart_theme_context.dart';

/// 小号「转圈」(「心跳」§7 加载):**常驻无限动画**,尺寸与描边集中在这里,
/// 免得每处各写一份 `CircularProgressIndicator(strokeWidth: 2)`。
///
/// 默认走中性色 [EmberColors.text3] —— 转码中这类「进行中但不抢视线」的状态用中性色,
/// 主色留给真正的高音(主按钮 / 选中 / 未读)。
///
/// ⚠️ 可见转圈的用例**禁用 `pumpAndSettle`**(无限动画不收敛),要断言它请用 `tester.pump()`。
class AppSpinner extends StatelessWidget {
  const AppSpinner({
    super.key,
    this.size = AppSpacing.lg,
    this.color,
    this.strokeWidth = 2,
  });

  /// 直径(逻辑像素)。
  final double size;

  /// 转圈颜色;不传用当前主题的中性色 `text3`。
  final Color? color;

  /// 线宽。
  final double strokeWidth;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: size,
      height: size,
      child: CircularProgressIndicator(
        strokeWidth: strokeWidth,
        color: color ?? context.heart.text3,
      ),
    );
  }
}
