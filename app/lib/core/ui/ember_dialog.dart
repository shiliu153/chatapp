import 'package:flutter/material.dart';

import '../theme/ember_theme_context.dart';
import '../theme/tokens.g.dart' as tokens;
import 'ember_button.dart';
import 'ember_component_sizes.dart';

/// 统一 Dialog:图标 + 标题 + 说明 + 两个按钮(spec §9.3「破坏性确认必须带图标 +
/// 明确动词」/ §8.3 按钮与卡片取值)。
///
/// 为什么必须有它:E-5.3 的对话线确认框是在 `features/chat` 里就地组装的
/// (见 `chat_confirm_dialog.dart` 的注释「等 E-5.6 统一二级页时再决定是否升进组件层」),
/// 本单(E-5.6a)就是那个时刻 —— 二/三级页共十来处弹窗,再各写一遍必然走味。
///
/// 逐格对齐 §8.3:
/// - 容器:`surface.card` + `radius.xl`(底部弹层同一档)+ 内边距 24;
/// - 遮罩:`overlay.scrim`(不用 Material 默认黑);
/// - 图标:直径 56 圆底、`brand.default` @12%,危险变体取 `status.danger`;
/// - 标题 `subtitle` 17/w600;说明 `caption` 13 `text.secondary`;
/// - 按钮:次在左、主在右等宽;危险变体的确认键走 [`EmberButtonVariant.danger`]
///   (实底只在二次确认之后,见该枚举注释)。
///
/// **动词纪律**(§9.3 + page spec §6 第 3 条):[confirmLabel] 不许是「确定 / 确认」——
/// 读屏要念到「注销账号」这种能独立看懂的动作,构造时断言拦下。
///
/// ```dart
/// final ok = await showEmberDialog(
///   context,
///   icon: PhosphorIconsRegular.signOut,
///   title: '注销账号?',
///   message: '账号注销后不可恢复。',
///   confirmLabel: '注销账号',
///   cancelLabel: '再想想',
///   danger: true,
/// );
/// ```
class EmberDialog extends StatelessWidget {
  /// 构造 Dialog(一般通过 [showEmberDialog] 用)。
  const EmberDialog({
    super.key,
    required this.icon,
    required this.title,
    required this.confirmLabel,
    this.message,
    this.content,
    this.cancelLabel = '取消',
    this.onConfirm,
    this.onCancel,
    this.danger = false,
    this.confirmKey,
    this.cancelKey,
  }) : assert(
          confirmLabel != '确定' && confirmLabel != '确认',
          '§9.3 要求 Dialog 的确认键是明确动词(「注销账号」而不是「确定」)',
        );

  /// 图标(Phosphor):§9.3 要求破坏性确认必须带图标,不给纯文字弹窗。
  final IconData icon;

  /// 标题(17/w600)。
  final String title;

  /// 确认键文案,**必须是动词**。
  final String confirmLabel;

  /// 说明(13/`text.secondary`);可为 `null`。
  final String? message;

  /// 附加内容(例如协议弹窗里的两个协议链接),放在说明与按钮之间。
  final Widget? content;

  /// 取消键文案。
  final String cancelLabel;

  /// 确认回调;`null` 时默认 `Navigator.pop(true)`。
  final VoidCallback? onConfirm;

  /// 取消回调;`null` 时默认 `Navigator.pop(false)`。
  final VoidCallback? onCancel;

  /// 是否危险操作(图标与确认键取 `status.danger`)。
  final bool danger;

  /// 确认键的 Key(页面测试定点点击按它取)。
  final Key? confirmKey;

  /// 取消键的 Key。
  final Key? cancelKey;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    final accent = danger ? colors.statusDanger : colors.brandDefault;

    return Dialog(
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
            // 图标:危险操作取 status.danger,常规取 brand.default(§6 语义色)。
            Center(
              child: Container(
                width: EmberComponentSizes.actionButtonSmall,
                height: EmberComponentSizes.actionButtonSmall,
                decoration: BoxDecoration(
                  color: accent.withValues(alpha: 0.12),
                  shape: BoxShape.circle,
                ),
                // 装饰图形不单独念(§8.4):信息在标题里已经有了。
                child: ExcludeSemantics(
                  child: Icon(icon, size: tokens.sizeIcon24, color: accent),
                ),
              ),
            ),
            SizedBox(height: tokens.space16),
            Text(
              title,
              textAlign: TextAlign.center,
              style: TextStyle(
                fontSize: tokens.fontSizeSubtitle,
                fontWeight: FontWeight.w600,
                height: tokens.fontLineHeightSubtitle,
                color: colors.textPrimary,
              ),
            ),
            if (message != null) ...[
              SizedBox(height: tokens.space8),
              Text(
                message!,
                textAlign: TextAlign.center,
                style: TextStyle(
                  fontSize: tokens.fontSizeCaption,
                  height: tokens.fontLineHeightCaption,
                  color: colors.textSecondary,
                ),
              ),
            ],
            if (content != null) ...[
              SizedBox(height: tokens.space16),
              content!,
            ],
            SizedBox(height: tokens.space24),
            Row(
              children: [
                Expanded(
                  child: EmberButton(
                    key: cancelKey,
                    label: cancelLabel,
                    variant: EmberButtonVariant.secondary,
                    onPressed: onCancel ?? () => Navigator.pop(context, false),
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
                    onPressed: onConfirm ?? () => Navigator.pop(context, true),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

/// 弹一个 [EmberDialog];确认返回 `true`,取消 / 点外部 / 返回键返回 `false`。
///
/// 参数说明:
/// - [context] 用于弹层与主题。
/// - [icon] 必填(§9.3:破坏性确认必须带图标)。
/// - [title] 标题(17/w600)。
/// - [confirmLabel] 确认键文案,**必须是动词**(断言拦「确定 / 确认」)。
/// - [message] 说明文案,可为 `null`。
/// - [content] 附加内容,可为 `null`。
/// - [cancelLabel] 取消键文案。
/// - [danger] 是否危险操作。
/// - [barrierDismissible] 点外部是否关闭;首次协议弹窗这类「必须做选择」的传 `false`。
/// - [confirmKey] / [cancelKey] 两个按钮的 Key。
///
/// Returns:
///   确认 `true`;其余 `false`。
Future<bool> showEmberDialog(
  BuildContext context, {
  required IconData icon,
  required String title,
  required String confirmLabel,
  String? message,
  Widget? content,
  String cancelLabel = '取消',
  bool danger = false,
  bool barrierDismissible = true,
  Key? confirmKey,
  Key? cancelKey,
}) async {
  final confirmed = await showDialog<bool>(
    context: context,
    barrierDismissible: barrierDismissible,
    // 遮罩用 overlay.scrim,不用 Material 默认黑(与 Sheet / Toast 同一档)。
    barrierColor: context.ember.overlayScrim,
    builder: (context) => EmberDialog(
      icon: icon,
      title: title,
      confirmLabel: confirmLabel,
      message: message,
      content: content,
      cancelLabel: cancelLabel,
      danger: danger,
      confirmKey: confirmKey,
      cancelKey: cancelKey,
    ),
  );
  return confirmed == true;
}
