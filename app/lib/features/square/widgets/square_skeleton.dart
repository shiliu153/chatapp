import 'package:flutter/material.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_radius.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/widgets/app_skeleton.dart';

/// 广场/我的动态加载骨架(附录 D):3 张卡骨架 — 圆头像 + 两条文字 + 图块 + 操作行。
/// 呼吸动画为无限循环 — 可见它的测试只用有限 pump。
class SquareSkeleton extends StatelessWidget {
  const SquareSkeleton({super.key});

  @override
  Widget build(BuildContext context) => Column(
        key: key ?? const Key('square.skeleton'),
        children: [
          for (var i = 0; i < 3; i++) ...[
            if (i > 0) const SizedBox(height: AppSpacing.cardGap),
            Container(
              padding: const EdgeInsets.all(AppSpacing.lg),
              decoration: BoxDecoration(
                color: AppColors.bgCard,
                borderRadius: BorderRadius.circular(AppRadius.card),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      const AppSkeleton(
                          width: 40, height: 40, radius: AppRadius.full),
                      const SizedBox(width: AppSpacing.md),
                      Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const AppSkeleton(width: 120, height: 14),
                          const SizedBox(height: AppSpacing.xs),
                          const AppSkeleton(width: 72, height: 12),
                        ],
                      ),
                    ],
                  ),
                  const SizedBox(height: AppSpacing.md),
                  const AppSkeleton(width: double.infinity, height: 14),
                  const SizedBox(height: AppSpacing.sm),
                  const AppSkeleton(width: 220, height: 14),
                  const SizedBox(height: AppSpacing.md),
                  const AppSkeleton(
                      width: double.infinity, height: 120, radius: AppRadius.image),
                  const SizedBox(height: AppSpacing.md),
                  const AppSkeleton(width: 140, height: 16),
                ],
              ),
            ),
          ],
        ],
      );
}
