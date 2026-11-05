import 'package:flutter/material.dart';

import '../theme/app_motion.dart';
import '../theme/app_radius.dart';
import '../theme/app_spacing.dart';
import '../theme/app_typography.dart';
import 'app_option_group.dart';
import '../theme/heart_theme_context.dart';

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
  Widget build(BuildContext context) {
    final colors = context.heart;
    return Wrap(
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
                      ? colors.brand.withValues(alpha: .12)
                      : colors.bgCard,
                  borderRadius: BorderRadius.circular(AppRadius.full),
                  border: Border.all(
                    color: selected.contains(item.value)
                        ? colors.brand
                        : colors.divider,
                  ),
                ),
                child: Text(
                  item.label,
                  style: AppText.body.copyWith(
                    color: selected.contains(item.value)
                        ? colors.brand
                        : colors.text2,
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
}
