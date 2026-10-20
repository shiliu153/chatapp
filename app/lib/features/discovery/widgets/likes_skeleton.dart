import 'package:flutter/material.dart';

import '../../../core/theme/app_radius.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/widgets/app_skeleton.dart';

/// 「喜欢我的人」加载骨架:6 行圆头像 + 两条文字条。
/// 含无限呼吸动画 —— 可见它的用例只用有限 pump。
class LikesSkeleton extends StatelessWidget {
  const LikesSkeleton({super.key});

  @override
  Widget build(BuildContext context) => Column(
        key: const Key('likes.skeleton'),
        children: [
          for (var i = 0; i < 6; i++)
            const Padding(
              padding: EdgeInsets.symmetric(
                horizontal: AppSpacing.lg,
                vertical: AppSpacing.md,
              ),
              child: Row(
                children: [
                  AppSkeleton(width: 44, height: 44, radius: AppRadius.full),
                  SizedBox(width: AppSpacing.md),
                  Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      AppSkeleton(width: 120, height: 14),
                      SizedBox(height: AppSpacing.xs),
                      AppSkeleton(width: 160, height: 12),
                    ],
                  ),
                ],
              ),
            ),
        ],
      );
}
