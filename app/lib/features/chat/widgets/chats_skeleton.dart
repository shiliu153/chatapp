import 'package:flutter/material.dart';

import '../../../core/theme/tokens.g.dart' as tokens;
import '../../../core/ui/ember_ui.dart';

/// 会话列表行骨架:圆头像块 + 两行文字条 ×6(E-5.3 page spec §5)。
///
/// 循环呼吸由 [EmberSkeleton] 自己管 —— 可见它的测试只能用有限 `pump`。
class ChatsSkeleton extends StatelessWidget {
  /// 构造骨架。
  const ChatsSkeleton({super.key});

  @override
  Widget build(BuildContext context) => Column(
        key: const Key('chats.skeleton'),
        children: [
          for (var i = 0; i < 6; i++)
            Padding(
              padding: EdgeInsets.symmetric(
                horizontal: tokens.space20,
                vertical: tokens.space12,
              ),
              child: Row(
                children: [
                  const EmberSkeleton(
                    width: EmberComponentSizes.avatarLg,
                    height: EmberComponentSizes.avatarLg,
                    shape: BoxShape.circle,
                  ),
                  SizedBox(width: tokens.space12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const EmberSkeleton(
                          width: 120,
                          height: tokens.fontSizeBody,
                        ),
                        SizedBox(height: tokens.space8),
                        const EmberSkeleton(
                          width: 180,
                          height: tokens.fontSizeCaption,
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
        ],
      );
}
