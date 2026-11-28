import 'package:flutter/material.dart';

import '../../../core/theme/tokens.g.dart' as tokens;
import '../../../core/ui/ember_ui.dart';

/// 黑名单加载骨架(附录 E,E-5.6b 迁移到 Ember):3 行「圆头像 48 + 两条文字条」。
///
/// 骨架色块换 [`EmberSkeleton`](spec §8.3「`surface.sunken`,透明度 .5↔1,1.2s 循环」),
/// 头像位换 [`EmberAvatar`] 的 `loading` 档 —— 形状与真实行一致(圆 + 两条字条),
/// 加载完成时不会跳版。**含无限呼吸动画**:可见它的用例只能有限 pump。
class BlockedUsersSkeleton extends StatelessWidget {
  /// 构造骨架。
  const BlockedUsersSkeleton({super.key});

  @override
  Widget build(BuildContext context) => Column(
        key: const Key('blocked.skeleton'),
        children: [
          for (var i = 0; i < 3; i++)
            Padding(
              padding: EdgeInsets.symmetric(
                horizontal: tokens.space20,
                vertical: tokens.space12,
              ),
              child: Row(
                children: [
                  const EmberAvatar(
                    loading: true,
                    size: EmberComponentSizes.avatarLg,
                  ),
                  SizedBox(width: tokens.space12),
                  Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      EmberSkeleton(
                        width: 120,
                        height: tokens.fontSizeSubtitle,
                      ),
                      SizedBox(height: tokens.space8),
                      EmberSkeleton(
                        width: 96,
                        height: tokens.fontSizeCaption,
                      ),
                    ],
                  ),
                ],
              ),
            ),
        ],
      );
}
