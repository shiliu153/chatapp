import 'package:flutter/material.dart';

import '../../../core/theme/tokens.g.dart' as tokens;
import '../../../core/ui/ember_ui.dart';
import '../../../core/widgets/avatar_hero.dart';
import '../profile_component_sizes.dart';

/// 他人资料页骨架(E-5.4 page spec §5「资料加载中」):头图等大骨架 + 信息行形状。
///
/// **Hero 为什么要挂在骨架上**:Hero 只在 push 之后的下一帧末扫描一次(shuttle
/// 定下就不再重建),而资料页首帧一定是 loading 态。如果 Hero 只在 data 态才出现,
/// 转场就永远找不到目标端 —— 表现为「有 tag、但不飞」。所以头图骨架**同样**包一层
/// [AvatarHero](飞行中显示的是来源侧那张图,骨架只是落地后的占位)。
///
/// 呼吸是无限循环(规范允许的两处之一),可见它的测试只用有限 pump。
class UserProfileSkeleton extends StatelessWidget {
  /// 构造骨架。
  const UserProfileSkeleton({super.key, this.heroTag});

  /// Hero tag;`null`(深链 / 无来源)时不包 Hero。
  final String? heroTag;

  @override
  Widget build(BuildContext context) {
    final width = MediaQuery.sizeOf(context).width;
    final headerHeight = width * ProfileComponentSizes.headerRatio >
            ProfileComponentSizes.headerMaxHeight
        ? ProfileComponentSizes.headerMaxHeight
        : width * ProfileComponentSizes.headerRatio;
    return ListView(
      key: const Key('user.skeleton'),
      padding: EdgeInsets.zero,
      children: [
        AvatarHero(
          tag: heroTag,
          imageUrl: null,
          fromRadius: tokens.radiusXl,
          child: EmberSkeleton(
            width: double.infinity,
            height: headerHeight,
            radius: 0,
          ),
        ),
        Padding(
          padding: EdgeInsets.fromLTRB(
            tokens.space20,
            tokens.space20,
            tokens.space20,
            tokens.space32,
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              for (var i = 0; i < 4; i++) ...[
                Padding(
                  padding: EdgeInsets.symmetric(vertical: tokens.space16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const EmberSkeleton(width: 64, height: tokens.fontSizeSubtitle),
                      SizedBox(height: tokens.space8),
                      const EmberSkeleton(width: 200, height: tokens.fontSizeBody),
                    ],
                  ),
                ),
              ],
            ],
          ),
        ),
      ],
    );
  }
}
