import 'package:flutter/material.dart';

import '../../../core/theme/app_typography.dart';
import '../../../core/theme/ember_theme_context.dart';
import '../../../core/theme/tokens.g.dart' as tokens;
import '../../../core/ui/ember_ui.dart';

/// 对话线的二次确认框:图标 + 明确动词(§9.3「破坏性确认走 Dialog,必须带图标 +
/// 明确动词,不用『确定 / 取消』」)。
///
/// 为什么不在 `core/ui` 里加一个 `EmberDialog`:E-5.3 page spec §3 明写「不新增
/// `core/ui` 组件」,而规范也只给了 Dialog 的**口径**(图标 + 动词)、没给逐格取值表。
/// 所以这里按 §8.2 的按钮 / §8.3 的卡片取值就地组装,等 E-5.6 统一二级页时再决定
/// 是否升进组件层。
///
/// 用法:
/// ```dart
/// final ok = await showChatConfirmDialog(
///   context,
///   icon: PhosphorIconsRegular.trash,
///   title: '删除这 3 条?',
///   message: '只在你这边删除,对方仍可见。',
///   confirmLabel: '删除 3 条',
///   cancelLabel: '保留',
///   danger: true,
///   confirmKey: const Key('chat.select.confirm'),
/// );
/// ```
///
/// 参数说明:
/// - [context] 用于弹层与主题。
/// - [icon] 必填:§9.3 要求破坏性确认必须带图标,不给「纯文字弹窗」。
/// - [title] 标题(17/w600)。
/// - [message] 说明文案(13/`text.secondary`),可为 null。
/// - [confirmLabel] 确认键文案,**必须是动词**(「删除 3 条」而不是「确定」)。
/// - [cancelLabel] 取消键文案:保留「取消」二字 —— §9.3 禁的是「确定 / 取消」这对
///   **无信息量**的动词组合,而「取消」本身在带图标 + 明确动词的弹窗里语义清楚。
/// - [danger] 是否危险操作(图标与确认键取 `status.danger`)。
/// - [confirmKey] 确认键的 Key(页面测试与定点点击按它取)。
/// - [cancelKey] 取消键的 Key。
///
/// Returns:
///   确认返回 true;取消 / 点外部 / 返回键返回 false。
Future<bool> showChatConfirmDialog(
  BuildContext context, {
  required IconData icon,
  required String title,
  String? message,
  required String confirmLabel,
  String cancelLabel = '取消',
  bool danger = false,
  Key? confirmKey,
  Key? cancelKey,
}) async {
  final colors = context.ember;
  final accent = danger ? colors.statusDanger : colors.brandDefault;
  final confirmed = await showDialog<bool>(
    context: context,
    // scrim 用 overlay.scrim,不用 Material 默认黑(§8.3 Sheet / Toast 同一档)。
    barrierColor: colors.overlayScrim,
    builder: (context) => Dialog(
      backgroundColor: colors.surfaceCard,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(tokens.radiusXl),
      ),
      insetPadding: EdgeInsets.symmetric(horizontal: tokens.space24),
      child: Padding(
        padding: EdgeInsets.all(tokens.space24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // 图标:危险操作取 status.danger,其余取 brand.default(§6 语义色)。
            Center(
              child: Container(
                width: EmberComponentSizes.actionButtonSmall,
                height: EmberComponentSizes.actionButtonSmall,
                decoration: BoxDecoration(
                  color: accent.withValues(alpha: 0.12),
                  shape: BoxShape.circle,
                ),
                child: Icon(icon, size: tokens.sizeIcon24, color: accent),
              ),
            ),
            SizedBox(height: tokens.space16),
            Text(
              title,
              textAlign: TextAlign.center,
              style: AppText.subtitle.copyWith(color: colors.textPrimary),
            ),
            if (message != null) ...[
              SizedBox(height: tokens.space8),
              Text(
                message,
                textAlign: TextAlign.center,
                style: AppText.caption.copyWith(color: colors.textSecondary),
              ),
            ],
            SizedBox(height: tokens.space24),
            Row(
              children: [
                Expanded(
                  child: EmberButton(
                    key: cancelKey,
                    label: cancelLabel,
                    variant: EmberButtonVariant.secondary,
                    onPressed: () => Navigator.pop(context, false),
                  ),
                ),
                SizedBox(width: tokens.space12),
                Expanded(
                  child: EmberButton(
                    key: confirmKey,
                    label: confirmLabel,
                    variant: danger
                        ? EmberButtonVariant.danger
                        : EmberButtonVariant.primary,
                    onPressed: () => Navigator.pop(context, true),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    ),
  );
  return confirmed == true;
}
