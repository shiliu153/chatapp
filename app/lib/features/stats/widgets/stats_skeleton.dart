import 'package:flutter/material.dart';

import '../../../core/theme/app_radius.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/widgets/app_skeleton.dart';
import 'stats_cards.dart';

/// 「我的数据」加载骨架:区间行 + 七张数字卡,形状照目标内容摆(§7「加载」)。
///
/// 卡的数量取自 [statsCardSpecs],与数据态的卡片网格保持同一份来源。
/// 含无限呼吸动画 —— 可见它的用例只能用有限 `pump`(见 `docs/pitfalls/testing.md`)。
class StatsSkeleton extends StatelessWidget {
  const StatsSkeleton({super.key});

  /// 卡内内容与数字卡同构(上下内边距 16 + 数字 + 标签),故高度取固定档。
  static const _cardHeight = 92.0;

  @override
  Widget build(BuildContext context) {
    return ListView(
      key: const Key('stats.skeleton'),
      padding: const EdgeInsets.fromLTRB(AppSpacing.pageH, AppSpacing.md,
          AppSpacing.pageH, AppSpacing.xxl),
      children: [
        // 区间行(「2026-11-09 ~ 2026-11-15」)的占位
        const AppSkeleton(width: 168, height: 14),
        const SizedBox(height: AppSpacing.cardGap),
        for (var i = 0; i < statsCardSpecs.length; i += 2) ...[
          if (i > 0) const SizedBox(height: AppSpacing.cardGap),
          Row(
            children: [
              const Expanded(
                  child:
                      AppSkeleton(height: _cardHeight, radius: AppRadius.card)),
              const SizedBox(width: AppSpacing.cardGap),
              Expanded(
                child: i + 1 < statsCardSpecs.length
                    ? const AppSkeleton(
                        height: _cardHeight, radius: AppRadius.card)
                    : const SizedBox.shrink(),
              ),
            ],
          ),
        ],
      ],
    );
  }
}
