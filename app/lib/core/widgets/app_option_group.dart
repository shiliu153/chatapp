import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_gradients.dart';
import '../theme/app_motion.dart';
import '../theme/app_radius.dart';
import '../theme/app_spacing.dart';
import '../theme/app_typography.dart';

/// 选项(单选/多选共用;`AppChipGroup` 也吃这个类型)。
class AppOption<T> {
  const AppOption({required this.value, required this.label});

  final T value;
  final String label;
}

/// 「心跳」§7 单选分段:白底 R16 描边容器内嵌等宽胶囊;
/// 选中 = `gradientHeart` 填充 + 白字 15/w600,未选中 = 透明底 + `text2`。
///
/// 整体高 [height](4 内边距 + 44 段)= 52,与 `AppTextField` 对齐。
/// 语义同旧 `SegmentedButton`:点已选中项不取消(现状如此,行为零变化)。
class AppOptionGroup<T> extends StatelessWidget {
  const AppOptionGroup({
    super.key,
    required this.options,
    required this.value,
    required this.onChanged,
  });

  final List<AppOption<T>> options;
  final T? value;
  final ValueChanged<T> onChanged;

  static const height = 52.0;
  static const _segmentHeight = 44.0;

  @override
  Widget build(BuildContext context) => Container(
        height: height,
        padding: const EdgeInsets.all(AppSpacing.xs),
        decoration: BoxDecoration(
          color: AppColors.bgCard,
          borderRadius: BorderRadius.circular(AppRadius.input),
          border: Border.all(color: AppColors.divider),
        ),
        child: Row(
          children: [
            for (final option in options)
              Expanded(
                child: GestureDetector(
                  onTap: () => onChanged(option.value),
                  behavior: HitTestBehavior.opaque,
                  child: AnimatedContainer(
                    duration: AppMotion.fast,
                    height: _segmentHeight,
                    alignment: Alignment.center,
                    decoration: BoxDecoration(
                      gradient:
                          option.value == value ? AppGradients.heart : null,
                      borderRadius: BorderRadius.circular(AppRadius.full),
                    ),
                    child: Text(
                      option.label,
                      style: AppText.body.copyWith(
                        color: option.value == value
                            ? Colors.white
                            : AppColors.text2,
                        fontWeight: option.value == value
                            ? FontWeight.w600
                            : FontWeight.w500,
                      ),
                    ),
                  ),
                ),
              ),
          ],
        ),
      );
}
