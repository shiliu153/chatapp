import 'package:flutter/material.dart';

import '../../../core/theme/app_radius.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/widgets/app_skeleton.dart';

/// 聊天页消息骨架:左右交错的头像圆块 + 气泡块 ×4。
/// 呼吸动画为无限循环——可见它的测试只用有限 pump。
class ChatSkeleton extends StatelessWidget {
  const ChatSkeleton({super.key});

  @override
  Widget build(BuildContext context) => const Padding(
        key: Key('chat.skeleton'),
        padding: EdgeInsets.all(AppSpacing.lg),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _BubbleRow(alignEnd: false, bubbleWidth: 180),
            _BubbleRow(alignEnd: true, bubbleWidth: 140),
            _BubbleRow(alignEnd: false, bubbleWidth: 220),
            _BubbleRow(alignEnd: true, bubbleWidth: 160),
          ],
        ),
      );
}

class _BubbleRow extends StatelessWidget {
  const _BubbleRow({required this.alignEnd, required this.bubbleWidth});

  final bool alignEnd;
  final double bubbleWidth;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: AppSpacing.md),
        child: Row(
          mainAxisAlignment:
              alignEnd ? MainAxisAlignment.end : MainAxisAlignment.start,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (!alignEnd) ...[
              const AppSkeleton(width: 40, height: 40, radius: AppRadius.full),
              const SizedBox(width: AppSpacing.sm),
            ],
            AppSkeleton(width: bubbleWidth, height: 40, radius: AppRadius.bubble),
            if (alignEnd) ...[
              const SizedBox(width: AppSpacing.sm),
              const AppSkeleton(width: 40, height: 40, radius: AppRadius.full),
            ],
          ],
        ),
      );
}
