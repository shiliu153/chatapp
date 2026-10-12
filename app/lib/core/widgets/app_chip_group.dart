import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_motion.dart';
import '../theme/app_radius.dart';
import '../theme/app_spacing.dart';
import '../theme/app_typography.dart';
import 'app_option_group.dart';

/// 「心跳」§7 多选标签:胶囊描边 `divider`;
/// 选中 = `brand@12%` 底 + 1px `brand` 描边 + `brand` 15/w600 字。
class AppChipGroup<T> extends StatelessWidget {
  const AppChipGroup({
    super.key,
    required this.items,
    required this.selected,
    required this.onChanged,
  });

  final List<AppOption<T>> items;
  final Set<T> selected;
  final ValueChanged<Set<T>> onChanged;

  @override
  Widget build(BuildContext context) => Wrap(
        spacing: AppSpacing.sm,
        runSpacing: AppSpacing.sm,
        children: [
          for (final item in items)
            GestureDetector(
              onTap: () {
                final next = {...selected};
                if (!next.remove(item.value)) next.add(item.value);
                onChanged(next);
              },
              behavior: HitTestBehavior.opaque,
              child: AnimatedContainer(
                duration: AppMotion.fast,
                padding: const EdgeInsets.symmetric(
                  horizontal: AppSpacing.lg,
                  vertical: AppSpacing.sm,
                ),
                decoration: BoxDecoration(
                  color: selected.contains(item.value)
                      ? AppColors.brand.withValues(alpha: .12)
                      : AppColors.bgCard,
                  borderRadius: BorderRadius.circular(AppRadius.full),
                  border: Border.all(
                    color: selected.contains(item.value)
                        ? AppColors.brand
                        : AppColors.divider,
                  ),
                ),
                child: Text(
                  item.label,
                  style: AppText.body.copyWith(
                    color: selected.contains(item.value)
                        ? AppColors.brand
                        : AppColors.text2,
                    fontWeight: selected.contains(item.value)
                        ? FontWeight.w600
                        : FontWeight.w500,
                  ),
                ),
              ),
            ),
        ],
      );
}
