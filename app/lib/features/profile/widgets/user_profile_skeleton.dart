import 'package:flutter/material.dart';

import '../../../core/theme/app_spacing.dart';
import '../../../core/widgets/app_skeleton.dart';

/// 他人资料页骨架:头图等大骨架 + 3 行行骨架。
/// 呼吸动画为无限循环——可见它的测试只用有限 pump。
class UserProfileSkeleton extends StatelessWidget {
  const UserProfileSkeleton({super.key});

  /// 与附录 C.4 的头图比例一致(屏宽 × 1.15,封顶 420)。
  static const _headerRatio = 1.15;
  static const _headerMax = 420.0;

  @override
  Widget build(BuildContext context) {
    final width = MediaQuery.sizeOf(context).width;
    final headerHeight =
        width * _headerRatio > _headerMax ? _headerMax : width * _headerRatio;
    return Column(
      key: const Key('user.skeleton'),
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        AppSkeleton(width: double.infinity, height: headerHeight, radius: 0),
        const SizedBox(height: AppSpacing.lg),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: AppSpacing.pageH),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              for (var i = 0; i < 3; i++) ...[
                const AppSkeleton(width: double.infinity, height: 16),
                const SizedBox(height: AppSpacing.xl),
              ],
            ],
          ),
        ),
      ],
    );
  }
}
