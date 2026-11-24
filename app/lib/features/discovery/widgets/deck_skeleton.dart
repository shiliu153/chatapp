import 'package:flutter/material.dart';

import '../../../core/theme/tokens.g.dart' as tokens;
import '../../../core/ui/ember_ui.dart';

/// 发现页加载骨架:与卡面等大的骨架块 + 操作钮位(spec §8.2 / §8.3「骨架」行)。
///
/// 形状按目标内容来:卡面是 `radius.xl` 的大圆角块,操作钮是两个圆形块;
/// 呼吸(透明度 .5↔1、1.2s 循环)由 [EmberSkeleton] 提供 —— 它是规范允许的
/// **唯二循环动画**之一,且减弱动态效果时自动静止(§8.4)。
///
/// 无限动画:可见状态的测试只用有限 `pump`,禁 `pumpAndSettle`。
class DeckSkeleton extends StatelessWidget {
  /// 构造骨架。
  const DeckSkeleton({super.key});

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Expanded(
          child: Padding(
            padding: EdgeInsets.fromLTRB(
              tokens.space20,
              tokens.space8,
              tokens.space20,
              0,
            ),
            child: LayoutBuilder(
              builder: (context, constraints) => Stack(
                children: [
                  Positioned.fill(
                    child: EmberSkeleton(
                      radius: tokens.radiusXl,
                      height: constraints.maxHeight,
                    ),
                  ),
                  Positioned(
                    left: tokens.space20,
                    right: tokens.space20,
                    bottom: tokens.space20,
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        EmberSkeleton(width: 180, height: tokens.fontSizeTitle),
                        SizedBox(height: tokens.space12),
                        EmberSkeleton(width: 96, height: tokens.fontSizeCaption),
                        SizedBox(height: tokens.space12),
                        EmberSkeleton(width: 240, height: tokens.fontSizeCaption),
                        SizedBox(height: tokens.space16),
                        Row(
                          children: [
                            EmberSkeleton(
                              width: 44,
                              height: 16,
                              radius: tokens.radiusXs,
                            ),
                            SizedBox(width: tokens.space8),
                            EmberSkeleton(
                              width: 44,
                              height: 16,
                              radius: tokens.radiusXs,
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
        SizedBox(
          height: SwipeDeckSkeletonMetrics.actionRowHeight,
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              EmberSkeleton(
                width: EmberComponentSizes.actionButtonSmall,
                height: EmberComponentSizes.actionButtonSmall,
                shape: BoxShape.circle,
              ),
              SizedBox(width: SwipeDeckSkeletonMetrics.actionGap),
              EmberSkeleton(
                width: EmberComponentSizes.actionButtonLarge,
                height: EmberComponentSizes.actionButtonLarge,
                shape: BoxShape.circle,
              ),
            ],
          ),
        ),
        SizedBox(height: tokens.space20),
      ],
    );
  }
}

/// 骨架里两个圆形块与卡组的几何对齐用的口径(与 `SwipeDeck` 保持同一套间距)。
///
/// 单独放一处而不是 import `swipe_deck.dart`:骨架屏不该为了两个常数把卡组
/// 拖进依赖图(它也用在别的页面级骨架场景里)。
abstract final class SwipeDeckSkeletonMetrics {
  /// 操作钮之间的间距。
  static const actionGap = 44.0;

  /// 操作钮行的高度。
  static const actionRowHeight = 88.0;
}
