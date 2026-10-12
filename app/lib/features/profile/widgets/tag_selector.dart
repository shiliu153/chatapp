import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api_exception.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_radius.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/theme/app_typography.dart';
import '../../../core/widgets/app_chip_group.dart';
import '../../../core/widgets/app_option_group.dart';
import '../../../core/widgets/app_skeleton.dart';
import '../profile_controller.dart';

class TagSelector extends ConsumerWidget {
  const TagSelector({super.key, required this.selectedIds, required this.onChanged});

  final Set<int> selectedIds;
  final ValueChanged<Set<int>> onChanged;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final tags = ref.watch(tagsProvider);
    return tags.when(
      // 三个胶囊骨架;AppSkeleton 是无限动画,可见它的用例只用有限 pump
      loading: () => const Row(
        children: [
          AppSkeleton(width: 64, height: 34, radius: AppRadius.full),
          SizedBox(width: AppSpacing.sm),
          AppSkeleton(width: 64, height: 34, radius: AppRadius.full),
          SizedBox(width: AppSpacing.sm),
          AppSkeleton(width: 64, height: 34, radius: AppRadius.full),
        ],
      ),
      error: (error, _) => Text(
        error is ApiException ? error.message : '标签加载失败',
        style: AppText.caption.copyWith(color: AppColors.text2),
      ),
      data: (list) => AppChipGroup<int>(
        items: [
          for (final tag in list) AppOption(value: tag.id, label: tag.name),
        ],
        selected: selectedIds,
        onChanged: onChanged,
      ),
    );
  }
}
