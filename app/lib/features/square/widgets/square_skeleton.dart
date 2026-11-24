import 'package:flutter/material.dart';

import '../../../core/theme/tokens.g.dart' as tokens;
import '../../../core/ui/ember_ui.dart';

/// 回声(广场)动态流加载骨架(E-5.5 page spec §5「动态流加载中」):
/// 3 张 [`EmberCard`] 骨架 —— 头像圆 + 两行文字 + 图片块 + 操作行,形状按目标内容
/// (§8.3 骨架「形状按目标内容」)。
///
/// 骨架的呼吸是 `EmberSkeleton` 内部的 1.2s 循环(§8.3 / §7.3 允许的两处循环动画之一);
/// 用到它的用例不要 `pumpAndSettle`(永远不收敛),按帧推进即可。
class SquareSkeleton extends StatelessWidget {
  /// 构造骨架。
  const SquareSkeleton({super.key});

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      // 3 张卡总高 > 一屏:包滚动,小屏不溢出(骨架屏为静态展示,不可交互)
      child: Column(
        key: const Key('square.skeleton'),
        children: [
          for (var i = 0; i < 3; i++) ...[
            if (i > 0) SizedBox(height: tokens.space12),
            const _SkeletonCard(),
          ],
        ],
      ),
    );
  }
}

/// 一张卡骨架:内边距 20(与真卡一致),行距按真卡的 4 / 8 / 12。
class _SkeletonCard extends StatelessWidget {
  const _SkeletonCard();

  @override
  Widget build(BuildContext context) {
    return EmberCard(
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
              Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  EmberSkeleton(width: 120, height: tokens.fontSizeSubtitle),
                  SizedBox(height: tokens.space4),
                  EmberSkeleton(width: 72, height: tokens.fontSizeMicro),
                ],
              ),
            ],
          ),
          SizedBox(height: tokens.space12),
          EmberSkeleton(height: tokens.fontSizeBody),
          SizedBox(height: tokens.space8),
          EmberSkeleton(width: 220, height: tokens.fontSizeBody),
          SizedBox(height: tokens.space12),
          EmberSkeleton(
            height: 120,
            radius: tokens.radiusSm,
          ),
          SizedBox(height: tokens.space12),
          Row(
            children: [
              EmberSkeleton(width: 40, height: tokens.fontSizeCaption),
              SizedBox(width: tokens.space16),
              EmberSkeleton(width: 40, height: tokens.fontSizeCaption),
            ],
          ),
        ],
      ),
    );
  }
}
