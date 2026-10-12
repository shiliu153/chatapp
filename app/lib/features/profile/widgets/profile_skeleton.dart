import 'package:flutter/material.dart';

import '../../../core/theme/app_radius.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/widgets/app_skeleton.dart';

/// 「我的」页骨架:身份卡(72 圆块 + 两条文字条)+ 5 行行骨架。
/// 呼吸动画为无限循环——可见它的测试只用有限 pump。
class ProfileSkeleton extends StatelessWidget {
  const ProfileSkeleton({super.key});

  @override
  Widget build(BuildContext context) => ListView(
        key: const Key('profile.skeleton'),
        padding: const EdgeInsets.symmetric(horizontal: AppSpacing.pageH),
        children: [
          const Row(
            children: [
              AppSkeleton(width: 72, height: 72, radius: AppRadius.full),
              SizedBox(width: AppSpacing.lg),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    AppSkeleton(width: 120, height: 20),
                    SizedBox(height: AppSpacing.sm),
                    AppSkeleton(width: 72, height: 12),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.xxl),
          for (var i = 0; i < 5; i++) ...[
            const AppSkeleton(width: double.infinity, height: 16),
            const SizedBox(height: AppSpacing.xl),
          ],
        ],
      );
}
