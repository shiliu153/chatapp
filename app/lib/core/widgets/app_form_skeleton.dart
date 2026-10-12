import 'package:flutter/material.dart';

import '../theme/app_radius.dart';
import '../theme/app_spacing.dart';
import 'app_skeleton.dart';

/// 「心跳」§7 表单页加载骨架:每组 = 标签条(64×12)+ 输入框块(通栏×52)。
/// 含无限呼吸动画 —— 可见它的用例只用有限 pump(`pumpFrames`),禁 `pumpAndSettle`。
class AppFormSkeleton extends StatelessWidget {
  const AppFormSkeleton({super.key, this.fields = 3});

  final int fields;

  @override
  Widget build(BuildContext context) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (var i = 0; i < fields; i++) ...[
            if (i > 0) const SizedBox(height: AppSpacing.lg),
            const AppSkeleton(width: 64, height: 12),
            const SizedBox(height: AppSpacing.sm),
            const AppSkeleton(
              width: double.infinity,
              height: 52,
              radius: AppRadius.input,
            ),
          ],
        ],
      );
}
