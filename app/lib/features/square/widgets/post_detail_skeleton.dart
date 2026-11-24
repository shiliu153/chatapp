import 'package:flutter/material.dart';

import '../../../core/theme/tokens.g.dart' as tokens;
import '../../../core/ui/ember_ui.dart';

/// 动态详情加载骨架(E-5.5 page spec §5):1 张卡骨架 + 2 条评论块骨架。
///
/// 只在**没有** `PostDetailArgs.seed` 时出现(我的动态 / 深链):有 seed 时详情页
/// 直接拿列表快照直出真卡,否则首帧没有 Hero 目标就不飞(见 `post_detail_page.dart`)。
///
/// 呼吸是 [EmberSkeleton] 的 1.2s 循环 —— 用到它的用例不要 `pumpAndSettle`。
class PostDetailSkeleton extends StatelessWidget {
  /// 构造骨架。
  const PostDetailSkeleton({super.key});

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      // 骨架为静态展示,包滚动免疫小屏溢出(同 SquareSkeleton)
      child: Column(
        key: const Key('post.skeleton'),
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          EmberCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    const EmberSkeleton(
                      width: EmberComponentSizes.avatarMd,
                      height: EmberComponentSizes.avatarMd,
                      shape: BoxShape.circle,
                    ),
                    SizedBox(width: tokens.space12),
                    EmberSkeleton(width: 120, height: tokens.fontSizeSubtitle),
                  ],
                ),
                SizedBox(height: tokens.space12),
                EmberSkeleton(height: tokens.fontSizeBody),
                SizedBox(height: tokens.space8),
                EmberSkeleton(width: 240, height: tokens.fontSizeBody),
              ],
            ),
          ),
          SizedBox(height: tokens.space16),
          for (var i = 0; i < 2; i++) ...[
            EmberSkeleton(
              height: 56,
              radius: tokens.radiusMd,
            ),
            SizedBox(height: tokens.space12),
          ],
        ],
      ),
    );
  }
}
