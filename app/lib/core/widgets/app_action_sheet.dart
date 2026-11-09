import 'package:flutter/material.dart';

import '../theme/app_radius.dart';
import '../theme/app_spacing.dart';
import '../theme/app_typography.dart';
import '../theme/heart_theme_context.dart';

/// 「心跳」§7 底部弹层里的一项操作。
///
/// [id] 是选项的稳定标识(文案会随状态变,比如「置顶」/「取消置顶」),
/// 选中后由 [showAppActionSheet] 原样 pop 出去,调用方按它分支。
/// 行 key 固定为 `actionSheet.<id>`,测试按它定位。
class AppActionSheetAction {
  const AppActionSheetAction({
    required this.id,
    required this.label,
    this.icon,
    this.danger = false,
  });

  /// 选项标识(如 `pin` / `mute` / `delete`)。
  final String id;

  /// 行文字。
  final String label;

  /// 左侧图标,**必须是 Material `*_rounded` 变体**(§4)。
  final IconData? icon;

  /// 危险操作(删除):文字与图标取 `danger`。
  final bool danger;

  Key get key => Key('actionSheet.$id');
}

/// 「心跳」§7 底部弹层:白底、上圆角 24、顶部拖把 36×4。
///
/// 只有行式选项,不做滚动 —— 选项数在个位数,撑不满一屏。
class AppActionSheet extends StatelessWidget {
  const AppActionSheet({super.key, this.title, required this.actions});

  /// 可选的说明文字(如会话昵称),显示在拖把下方。
  final String? title;

  final List<AppActionSheetAction> actions;

  /// §7「拖把」尺寸:设计文档没给 token 名,收在这里单点维护。
  static const _handleWidth = 36.0;
  static const _handleHeight = 4.0;
  static const _handleRadius = 2.0;

  /// §5.2 列表行高(操作行同档)。
  static const _rowHeight = 56.0;

  @override
  Widget build(BuildContext context) {
    final colors = context.heart;
    return SafeArea(
      top: false,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const SizedBox(height: AppSpacing.sm),
          Center(
            child: Container(
              width: _handleWidth,
              height: _handleHeight,
              decoration: BoxDecoration(
                color: colors.divider,
                borderRadius: BorderRadius.circular(_handleRadius),
              ),
            ),
          ),
          if (title != null)
            Padding(
              padding: const EdgeInsets.fromLTRB(
                  AppSpacing.lg, AppSpacing.md, AppSpacing.lg, 0),
              child: Text(
                title!,
                textAlign: TextAlign.center,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: AppText.caption.copyWith(color: colors.text2),
              ),
            ),
          const SizedBox(height: AppSpacing.sm),
          for (var i = 0; i < actions.length; i++) ...[
            if (i > 0)
              Divider(
                height: 1,
                thickness: 1,
                indent: AppSpacing.lg,
                endIndent: AppSpacing.lg,
                color: colors.divider,
              ),
            _ActionRow(action: actions[i], height: _rowHeight),
          ],
          const SizedBox(height: AppSpacing.sm),
        ],
      ),
    );
  }
}

class _ActionRow extends StatelessWidget {
  const _ActionRow({required this.action, required this.height});

  final AppActionSheetAction action;
  final double height;

  @override
  Widget build(BuildContext context) {
    final colors = context.heart;
    final foreground = action.danger ? colors.danger : colors.text1;
    final iconColor = action.danger ? colors.danger : colors.text2;
    return InkWell(
      key: action.key,
      onTap: () => Navigator.pop(context, action.id),
      child: SizedBox(
        height: height,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
          child: Row(
            children: [
              if (action.icon != null) ...[
                Icon(action.icon, size: 22, color: iconColor),
                const SizedBox(width: AppSpacing.md),
              ],
              Expanded(
                child: Text(
                  action.label,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: AppText.subtitle.copyWith(color: foreground),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// 弹出底部操作面板,返回选中项的 [AppActionSheetAction.id];点外部/返回 null。
Future<String?> showAppActionSheet(
  BuildContext context, {
  String? title,
  required List<AppActionSheetAction> actions,
}) {
  final colors = context.heart;
  return showModalBottomSheet<String>(
    context: context,
    backgroundColor: colors.bgCard,
    shape: const RoundedRectangleBorder(
      borderRadius: BorderRadius.vertical(top: Radius.circular(AppRadius.sheet)),
    ),
    builder: (_) => AppActionSheet(title: title, actions: actions),
  );
}
