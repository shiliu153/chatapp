import 'package:flutter/material.dart';

import '../theme/app_radius.dart';
import '../theme/app_spacing.dart';
import 'app_skeleton.dart';

/// 列表页通用加载骨架:圆头像 + 两条文字条。
/// 含无限呼吸动画 —— 可见它的用例只用有限 pump。
class AppListSkeleton extends StatelessWidget {
  const AppListSkeleton({super.key, this.rowCount = 6});

  final int rowCount;

  @override
  Widget build(BuildContext context) => Column(
        children: [
          for (var i = 0; i < rowCount; i++)
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
