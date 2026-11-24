import 'package:flutter/material.dart';

import '../../../core/theme/tokens.g.dart' as tokens;
import '../../../core/ui/ember_ui.dart';

/// 聊天页消息骨架:左右交错的头像圆块 + 气泡块 ×4(E-5.3 page spec §5「EmberSkeleton 按气泡形状」)。
///
/// 骨架是纯装饰(§8.4),循环呼吸由 [EmberSkeleton] 自己管 —— 可见它的测试只能用
/// 有限 `pump`,禁 `pumpAndSettle`(它永远不会 settle)。
class ChatSkeleton extends StatelessWidget {
  /// 构造骨架。
  const ChatSkeleton({super.key});

  @override
  Widget build(BuildContext context) => Padding(
        key: const Key('chat.skeleton'),
        padding: EdgeInsets.all(tokens.space20),
        child: const Column(
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
        padding: EdgeInsets.only(bottom: tokens.space12),
        child: Row(
          mainAxisAlignment:
              alignEnd ? MainAxisAlignment.end : MainAxisAlignment.start,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (!alignEnd) ...[
              const EmberSkeleton(
                width: EmberComponentSizes.avatarMd,
                height: EmberComponentSizes.avatarMd,
                shape: BoxShape.circle,
              ),
              SizedBox(width: tokens.space8),
            ],
            EmberSkeleton(
              width: bubbleWidth,
              height: tokens.space40,
              radius: tokens.radiusMd,
            ),
            if (alignEnd) ...[
              SizedBox(width: tokens.space8),
              const EmberSkeleton(
                width: EmberComponentSizes.avatarMd,
                height: EmberComponentSizes.avatarMd,
                shape: BoxShape.circle,
              ),
            ],
          ],
        ),
      );
}
