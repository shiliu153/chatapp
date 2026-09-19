import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_spacing.dart';
import '../theme/app_typography.dart';

/// 「心跳」规则 §7 空态:大号彩色元素(mark 优先,emoji 备选)+ 标题 17/w600
/// + 说明 13 text2 + 可选按钮。禁止灰色图标占位。
class AppEmptyState extends StatelessWidget {
  const AppEmptyState({
    super.key,
    this.mark,
    this.emoji,
    required this.title,
    this.description,
    this.action,
  });

  /// 大号元素二选一:mark(自定义图形,优先)或 emoji。
  final Widget? mark;
  final String? emoji;
  final String title;
  final String? description;
  final Widget? action;

  @override
  Widget build(BuildContext context) => Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (mark != null)
            mark!
          else if (emoji != null)
            Text(emoji!, style: AppText.emoji),
          const SizedBox(height: AppSpacing.md),
          Text(title, style: AppText.subtitle.copyWith(fontSize: 17)),
          if (description != null) ...[
            const SizedBox(height: AppSpacing.xs),
            Text(
              description!,
              style: AppText.caption.copyWith(color: AppColors.text2),
              textAlign: TextAlign.center,
            ),
          ],
          if (action != null) ...[
            const SizedBox(height: AppSpacing.lg),
            action!,
          ],
        ],
      );
}
