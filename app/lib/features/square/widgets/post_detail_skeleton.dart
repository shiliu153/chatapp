import 'package:flutter/material.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_radius.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/widgets/app_skeleton.dart';

/// 动态详情加载骨架(附录 D):1 张卡骨架 + 2 条评论行骨架。
/// 呼吸动画为无限循环 — 可见它的测试只用有限 pump。
class PostDetailSkeleton extends StatelessWidget {
  const PostDetailSkeleton({super.key});

  @override
  Widget build(BuildContext context) => SingleChildScrollView(
        // 骨架为静态展示,包滚动免疫小屏溢出(同 SquareSkeleton)
        child: Column(
          key: key ?? const Key('post.skeleton'),
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
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
                      const AppSkeleton(width: 40, height: 40, radius: AppRadius.full),
                      const SizedBox(width: AppSpacing.md),
                      const AppSkeleton(width: 120, height: 14),
                    ],
                  ),
                  const SizedBox(height: AppSpacing.md),
                  const AppSkeleton(width: double.infinity, height: 14),
                  const SizedBox(height: AppSpacing.sm),
                  const AppSkeleton(width: 240, height: 14),
                ],
              ),
            ),
            const SizedBox(height: AppSpacing.lg),
            for (var i = 0; i < 2; i++) ...[
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: AppSpacing.pageH),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const AppSkeleton(width: 28, height: 28, radius: AppRadius.full),
                    const SizedBox(width: AppSpacing.sm),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const AppSkeleton(width: 96, height: 12),
                          const SizedBox(height: AppSpacing.xs),
                          const AppSkeleton(width: 200, height: 13),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: AppSpacing.lg),
            ],
          ],
        ),
      );
}
