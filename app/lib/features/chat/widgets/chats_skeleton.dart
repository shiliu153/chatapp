import 'package:flutter/material.dart';

import '../../../core/theme/app_radius.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/widgets/app_skeleton.dart';

/// 消息页行骨架:圆头像块 + 两行文字条 ×6。
/// 呼吸动画为无限循环——可见它的测试只用有限 pump。
class ChatsSkeleton extends StatelessWidget {
  const ChatsSkeleton({super.key});

  @override
  Widget build(BuildContext context) => Column(
        key: const Key('chats.skeleton'),
        children: [
          for (var i = 0; i < 6; i++)
            const Padding(
              padding: EdgeInsets.symmetric(
                  horizontal: AppSpacing.pageH, vertical: AppSpacing.md),
              child: Row(
                children: [
                  AppSkeleton(width: 48, height: 48, radius: AppRadius.full),
                  SizedBox(width: AppSpacing.md),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        AppSkeleton(width: 120, height: 14),
                        SizedBox(height: AppSpacing.sm),
                        AppSkeleton(width: 180, height: 12),
                      ],
                    ),
                  ),
                ],
              ),
            ),
        ],
      );
}
