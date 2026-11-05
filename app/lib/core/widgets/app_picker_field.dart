import 'package:flutter/material.dart';

import '../theme/app_radius.dart';
import '../theme/app_spacing.dart';
import '../theme/app_typography.dart';
import '../theme/heart_theme_context.dart';

/// 「心跳」§7 选择框:外观与 `AppTextField` 同规格(白底 R16 描边 1px 高 52),
/// 点整块唤起外部选择器(如 `showDatePicker`)。
class AppPickerField extends StatelessWidget {
  const AppPickerField({
    super.key,
    required this.label,
    this.value,
    this.placeholder = '请选择',
    required this.onTap,
  });

  final String label;
  final String? value;
  final String placeholder;
  final VoidCallback onTap;

  static const height = 52.0;

  @override
  Widget build(BuildContext context) {
    final colors = context.heart;
    return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label, style: AppText.caption.copyWith(color: colors.text2)),
          const SizedBox(height: AppSpacing.xs),
          GestureDetector(
            onTap: onTap,
            behavior: HitTestBehavior.opaque,
            child: Container(
              height: height,
              padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
              decoration: BoxDecoration(
                color: colors.bgCard,
                borderRadius: BorderRadius.circular(AppRadius.input),
                border: Border.all(color: colors.divider),
              ),
              child: Row(
                children: [
                  Expanded(
                    child: Text(
                      value ?? placeholder,
                      style: AppText.body.copyWith(
                        color: value == null ? colors.text3 : colors.text1,
                      ),
                    ),
                  ),
                  Icon(Icons.expand_more_rounded,
                      size: 20, color: colors.text3),
                ],
              ),
            ),
          ),
        ],
      );
  }
}
