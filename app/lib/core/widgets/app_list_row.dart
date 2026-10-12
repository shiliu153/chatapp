import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_motion.dart';
import '../theme/app_spacing.dart';
import '../theme/app_typography.dart';

/// 「心跳」§5.2 列表行:高 64;左槽图标(20)或头像;标题 + 可选副标题;
/// 右槽 [trailing] 或默认 `chevron_right_rounded`;按压 scale .98。
///
/// [centerTitle] 是「退出登录」这类单行危险动作的变体:居中、无左右槽。
class AppListRow extends StatefulWidget {
  const AppListRow({
    super.key,
    this.icon,
    this.avatar,
    required this.title,
    this.subtitle,
    this.trailing,
    this.onTap,
    this.danger = false,
    this.showChevron = true,
    this.centerTitle = false,
  });

  final IconData? icon;
  final Widget? avatar;
  final String title;
  final String? subtitle;
  final Widget? trailing;
  final VoidCallback? onTap;
  final bool danger;
  final bool showChevron;
  final bool centerTitle;

  static const height = 64.0;

  @override
  State<AppListRow> createState() => _AppListRowState();
}

class _AppListRowState extends State<AppListRow> {
  var _pressed = false;

  @override
  Widget build(BuildContext context) {
    final accent = widget.danger ? AppColors.danger : AppColors.text1;
    final iconColor = widget.danger ? AppColors.danger : AppColors.text2;
    final tappable = widget.onTap != null;

    final Widget content = widget.centerTitle
        ? Center(
            child: Text(
              widget.title,
              style: AppText.body
                  .copyWith(color: accent, fontWeight: FontWeight.w600),
            ),
          )
        : Row(
            children: [
              if (widget.avatar != null) ...[
                widget.avatar!,
                const SizedBox(width: AppSpacing.md),
              ] else if (widget.icon != null) ...[
                Icon(widget.icon, size: 20, color: iconColor),
                const SizedBox(width: AppSpacing.md),
              ],
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(
                      widget.title,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: AppText.body.copyWith(color: accent),
                    ),
                    if (widget.subtitle != null) ...[
                      const SizedBox(height: 2),
                      Text(
                        widget.subtitle!,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: AppText.micro.copyWith(color: AppColors.text3),
                      ),
                    ],
                  ],
                ),
              ),
              if (widget.trailing != null)
                widget.trailing!
              else if (widget.showChevron)
                const Icon(Icons.chevron_right_rounded,
                    size: 20, color: AppColors.text3),
            ],
          );

    return GestureDetector(
      // 必须 opaque:整行都要能点(默认 deferToChild 时,右侧空白区点不动)
      behavior: HitTestBehavior.opaque,
      onTapDown: tappable ? (_) => setState(() => _pressed = true) : null,
      onTapUp: tappable ? (_) => setState(() => _pressed = false) : null,
      onTapCancel: tappable ? () => setState(() => _pressed = false) : null,
      onTap: widget.onTap,
      child: AnimatedScale(
        scale: _pressed ? 0.98 : 1,
        duration: AppMotion.fast,
        child: Container(
          height: AppListRow.height,
          padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
          alignment: Alignment.center,
          child: content,
        ),
      ),
    );
  }
}
