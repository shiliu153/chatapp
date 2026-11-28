import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api_exception.dart';
import '../../../core/theme/ember_theme_context.dart';
import '../../../core/theme/tokens.g.dart' as tokens;
import '../../../core/ui/ember_ui.dart';
import '../profile_controller.dart';

/// 标签多选(E-5.6c 换皮):`EmberChip` 胶囊,选中 = `brand.default` 实底 +
/// `brand.on` 字(spec §8.3 Chip 行);未选中 `surface.sunken` + `text.secondary`。
///
/// 只换视觉:标签列表仍来自 `tagsProvider`,选择仍由调用方持有 `Set<int>`,
/// 点一下切换、回调整份新集合 —— 与改版前逐字一致(编辑资料页与完善资料向导共用)。
class TagSelector extends ConsumerWidget {
  /// 构造标签选择。
  const TagSelector({
    super.key,
    required this.selectedIds,
    required this.onChanged,
  });

  /// 已选标签 id。
  final Set<int> selectedIds;

  /// 选择变化回调(整份新集合)。
  final ValueChanged<Set<int>> onChanged;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final colors = context.ember;
    final tags = ref.watch(tagsProvider);
    return tags.when(
      // 三个胶囊骨架;EmberSkeleton 是无限动画,可见它的用例只用有限 pump。
      loading: () => Wrap(
        spacing: tokens.space8,
        children: [
          for (var i = 0; i < 3; i++)
            const EmberSkeleton(
              width: 64,
              height: EmberComponentSizes.chipHeight,
              radius: tokens.radiusPill,
            ),
        ],
      ),
      error: (error, _) => Text(
        error is ApiException ? error.message : '标签加载失败',
        style: TextStyle(
          fontSize: tokens.fontSizeCaption,
          height: tokens.fontLineHeightCaption,
          color: colors.textSecondary,
        ),
      ),
      data: (list) => Wrap(
        spacing: tokens.space8,
        children: [
          for (final tag in list)
            EmberChip(
              label: tag.name,
              selected: selectedIds.contains(tag.id),
              onTap: () {
                final next = {...selectedIds};
                if (!next.remove(tag.id)) next.add(tag.id);
                onChanged(next);
              },
            ),
        ],
      ),
    );
  }
}
