import 'package:flutter/material.dart';

import '../theme/heart_theme_context.dart';
import '../theme/app_gradients.dart';
import '../theme/app_motion.dart';
import '../theme/app_radius.dart';
import '../theme/app_shadows.dart';
import '../theme/app_spacing.dart';
import '../theme/app_typography.dart';

enum AppButtonVariant { primary, secondary, text, danger, dangerFilled }

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
    final colors = context.heart;
    final disabled = widget.onPressed == null;
    var (decoration, textStyle) = switch (widget.variant) {
      AppButtonVariant.primary => (
          BoxDecoration(
            gradient: disabled ? null : AppGradients.heartOf(colors),
            color: disabled ? colors.divider : null,
            borderRadius: BorderRadius.circular(AppRadius.full),
            boxShadow: disabled ? null : AppShadows.primaryButton,
          ),
          AppText.body.copyWith(color: Colors.white, fontWeight: FontWeight.w700),
        ),
      AppButtonVariant.secondary => (
          BoxDecoration(
            color: colors.bgCard,
            borderRadius: BorderRadius.circular(AppRadius.full),
            border: Border.all(color: colors.divider),
          ),
          AppText.body.copyWith(color: colors.text1, fontWeight: FontWeight.w600),
        ),
      AppButtonVariant.text => (
          const BoxDecoration(),
          AppText.body.copyWith(color: colors.brand, fontWeight: FontWeight.w600),
        ),
      AppButtonVariant.danger => (
          BoxDecoration(
            borderRadius: BorderRadius.circular(AppRadius.full),
            border: Border.all(color: colors.danger),
          ),
          AppText.body.copyWith(color: colors.danger, fontWeight: FontWeight.w600),
        ),
      // §7「危险按钮:danger 描边或实底(二次确认后)」的实底形态。
      // 不带阴影:同屏阴影层级不超过 2 种(§5.1),且 primaryButton 阴影是 brand 色。
      AppButtonVariant.dangerFilled => (
          BoxDecoration(
            color: disabled ? colors.divider : colors.danger,
            borderRadius: BorderRadius.circular(AppRadius.full),
          ),
          AppText.body.copyWith(color: Colors.white, fontWeight: FontWeight.w700),
        ),
    };
    if (disabled) {
      textStyle = textStyle.copyWith(color: colors.text3);
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
          padding: const EdgeInsets.symmetric(horizontal: AppSpacing.xxl),
          decoration: decoration,
          // Center(widthFactor:1) 而非 alignment:相对宽松约束下收缩为内容宽度
          // (Container.alignment 内部的 Align 会把按钮撑满整行)
          child: Center(
            widthFactor: 1,
            child: Text(widget.label, style: textStyle),
          ),
        ),
      ),
    );
  }
}
