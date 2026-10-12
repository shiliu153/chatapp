import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_spacing.dart';
import '../theme/app_typography.dart';

/// 「心跳」规则 §7 文字按钮的**紧凑形态**:`brand` 15/w600,无底无边距盒子。
///
/// 与 `AppButton` 的 `text` 变体区别:本组件没有 52 高、没有 24 水平内边距,
/// 因此能塞进输入框(`AppTextField.suffix`)与二级页顶栏(`AppSubPageBar.trailing`)。
/// `onPressed == null` 时文字 `text3`(§7 禁用态)。
class AppTextAction extends StatelessWidget {
  const AppTextAction({
    super.key,
    required this.label,
    this.onPressed,
    this.danger = false,
  });

  final String label;
  final VoidCallback? onPressed;
  final bool danger;

  @override
  Widget build(BuildContext context) {
    final disabled = onPressed == null;
    final color = disabled
        ? AppColors.text3
        : (danger ? AppColors.danger : AppColors.brand);
    return GestureDetector(
      onTap: onPressed,
      behavior: HitTestBehavior.opaque,
      child: Padding(
        padding: const EdgeInsets.symmetric(
          horizontal: AppSpacing.sm,
          vertical: AppSpacing.xs,
        ),
        child: Text(
          label,
          style: AppText.body.copyWith(color: color, fontWeight: FontWeight.w600),
        ),
      ),
    );
  }
}
