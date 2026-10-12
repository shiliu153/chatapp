import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_radius.dart';
import '../theme/app_shadows.dart';
import '../theme/app_spacing.dart';
import '../theme/app_typography.dart';

/// 「心跳」§7 表单分组卡:白卡 R20 + 卡片阴影 + 内边距 16;可选分组标题。
/// 子项按 [gap] 竖排(默认 `AppSpacing.lg` = 16)。
///
/// 行式列表(行自带内边距、行间分隔线)请用 `AppRowGroup`,别把两种内边距
/// 语义塞进同一个构造(附录 E.1)。
class AppSectionCard extends StatelessWidget {
  const AppSectionCard({
    super.key,
    this.title,
    required this.children,
    this.gap = AppSpacing.lg,
  });

  final String? title;
  final List<Widget> children;
  final double gap;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.all(AppSpacing.lg),
        decoration: BoxDecoration(
          color: AppColors.bgCard,
          borderRadius: BorderRadius.circular(AppRadius.card),
          boxShadow: AppShadows.card,
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (title != null) ...[
              Text(title!,
                  style: AppText.subtitle.copyWith(color: AppColors.text1)),
              const SizedBox(height: AppSpacing.md),
            ],
            for (var i = 0; i < children.length; i++) ...[
              if (i > 0) SizedBox(height: gap),
              children[i],
            ],
          ],
        ),
      );
}
