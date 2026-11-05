import 'package:flutter/material.dart';

import '../theme/app_radius.dart';
import '../theme/app_shadows.dart';
import '../theme/app_spacing.dart';
import '../theme/app_typography.dart';
import '../theme/heart_theme_context.dart';

/// 「心跳」§7 行分组卡:白卡 R20 + 卡片阴影 + **无内边距**(行自带 16 水平内边距);
/// 行之间插 1px `divider`。可选分组标题(自带 16 内边距)。
class AppRowGroup extends StatelessWidget {
  const AppRowGroup({super.key, this.title, required this.children});

  final String? title;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    final colors = context.heart;
    return Container(
        clipBehavior: Clip.antiAlias,
        decoration: BoxDecoration(
          color: colors.bgCard,
          borderRadius: BorderRadius.circular(AppRadius.card),
          boxShadow: AppShadows.card,
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            if (title != null)
              Padding(
                padding: const EdgeInsets.fromLTRB(AppSpacing.lg, AppSpacing.md,
                    AppSpacing.lg, AppSpacing.xs),
                child: Text(title!,
                    style: AppText.caption.copyWith(color: colors.text3)),
              ),
            for (var i = 0; i < children.length; i++) ...[
              if (i > 0)
                Divider(height: 1, thickness: 1, color: colors.divider),
              children[i],
            ],
          ],
        ),
      );
  }
}
