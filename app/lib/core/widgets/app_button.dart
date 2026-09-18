import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_gradients.dart';
import '../theme/app_motion.dart';
import '../theme/app_radius.dart';
import '../theme/app_shadows.dart';
import '../theme/app_typography.dart';

enum AppButtonVariant { primary, secondary, text, danger }

/// 「心跳」规则 §7 按钮:高 52 胶囊;按压 scale .96。
class AppButton extends StatefulWidget {
  const AppButton({
    super.key,
    required this.label,
    this.onPressed,
    this.variant = AppButtonVariant.primary,
  });

  final String label;
  final VoidCallback? onPressed;
  final AppButtonVariant variant;

  @override
  State<AppButton> createState() => _AppButtonState();
}

class _AppButtonState extends State<AppButton> {
  var _pressed = false;

  @override
  Widget build(BuildContext context) {
    final disabled = widget.onPressed == null;
    var (decoration, textStyle) = switch (widget.variant) {
      AppButtonVariant.primary => (
          BoxDecoration(
            gradient: disabled ? null : AppGradients.heart,
            color: disabled ? AppColors.divider : null,
            borderRadius: BorderRadius.circular(AppRadius.full),
            boxShadow: disabled ? null : AppShadows.primaryButton,
          ),
          AppText.body.copyWith(color: Colors.white, fontWeight: FontWeight.w700),
        ),
      AppButtonVariant.secondary => (
          BoxDecoration(
            color: AppColors.bgCard,
            borderRadius: BorderRadius.circular(AppRadius.full),
            border: Border.all(color: AppColors.divider),
          ),
          AppText.body.copyWith(color: AppColors.text1, fontWeight: FontWeight.w600),
        ),
      AppButtonVariant.text => (
          const BoxDecoration(),
          AppText.body.copyWith(color: AppColors.brand, fontWeight: FontWeight.w600),
        ),
      AppButtonVariant.danger => (
          BoxDecoration(
            borderRadius: BorderRadius.circular(AppRadius.full),
            border: Border.all(color: AppColors.danger),
          ),
          AppText.body.copyWith(color: AppColors.danger, fontWeight: FontWeight.w600),
        ),
    };
    if (disabled) {
      textStyle = textStyle.copyWith(color: AppColors.text3);
    }

    return GestureDetector(
      onTapDown: disabled ? null : (_) => setState(() => _pressed = true),
      onTapUp: disabled ? null : (_) => setState(() => _pressed = false),
      onTapCancel: disabled ? null : () => setState(() => _pressed = false),
      onTap: widget.onPressed,
      child: AnimatedScale(
        scale: _pressed ? 0.96 : 1,
        duration: AppMotion.fast,
        child: Container(
          height: 52,
          alignment: Alignment.center,
          decoration: decoration,
          child: Text(widget.label, style: textStyle),
        ),
      ),
    );
  }
}
