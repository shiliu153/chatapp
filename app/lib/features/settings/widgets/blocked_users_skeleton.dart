import 'package:flutter/material.dart';

import '../../../core/theme/app_radius.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/widgets/app_skeleton.dart';

/// 黑名单加载骨架(附录 E):3 行「圆头像 44 + 两条文字条」。
/// 含无限呼吸动画 —— 可见它的用例只用有限 pump。
class BlockedUsersSkeleton extends StatelessWidget {
  const BlockedUsersSkeleton({super.key});

  @override
  Widget build(BuildContext context) => Column(
        key: const Key('blocked.skeleton'),
        children: [
          for (var i = 0; i < 3; i++)
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
                      AppSkeleton(width: 96, height: 12),
                    ],
                  ),
                ],
              ),
            ),
        ],
      );
}
