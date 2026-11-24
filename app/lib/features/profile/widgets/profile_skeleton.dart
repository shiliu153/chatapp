import 'package:flutter/material.dart';

import '../../../core/theme/tokens.g.dart' as tokens;
import '../../../core/ui/ember_ui.dart';

/// 「我的」页骨架(E-5.4 page spec §5「资料加载中」):身份卡(96 圆块 + 两条
/// 文字条)+ 信息行形状。
///
/// 形状按目标内容(§8.3 骨架行「形状按目标内容」):身份卡是一块 `radius.lg` 的
/// 大色块,下面每一行一条「行高 72」的横条,分隔线位置留空。
///
/// 呼吸是无限循环(规范允许的两处之一),可见它的测试只用有限 pump。
class ProfileSkeleton extends StatelessWidget {
  /// 构造骨架。
  const ProfileSkeleton({super.key});

  @override
  Widget build(BuildContext context) {
    return ListView(
      key: const Key('profile.skeleton'),
      padding: EdgeInsets.fromLTRB(
        tokens.space20,
        0,
        tokens.space20,
        tokens.space32,
      ),
      children: [
        // 身份卡:大头像 + 昵称条 + ID 条
        Row(
          children: [
            const EmberSkeleton(
              width: EmberComponentSizes.avatarHero,
              height: EmberComponentSizes.avatarHero,
              shape: BoxShape.circle,
            ),
            SizedBox(width: tokens.space16),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const EmberSkeleton(width: 140, height: tokens.fontSizeTitle),
                  SizedBox(height: tokens.space8),
                  const EmberSkeleton(width: 72, height: tokens.fontSizeMicro),
                ],
              ),
            ),
          ],
        ),
        SizedBox(height: tokens.space24),
        // 信息行:行高与真实行一致(72),骨架不会在数据到达时「跳一下」
        for (var i = 0; i < 5; i++) ...[
          Padding(
            padding: EdgeInsets.symmetric(vertical: tokens.space16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const EmberSkeleton(width: 64, height: tokens.fontSizeSubtitle),
                SizedBox(height: tokens.space8),
                const EmberSkeleton(width: 160, height: tokens.fontSizeBody),
              ],
            ),
          ),
        ],
      ],
    );
  }
}
