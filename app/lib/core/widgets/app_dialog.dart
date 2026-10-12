import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_radius.dart';
import '../theme/app_spacing.dart';
import '../theme/app_typography.dart';
import 'app_button.dart';

/// 「心跳」统一对话框:白底 R24、标题 17/w600 居中、正文 `caption` `text2`、
/// [actions] 等宽横排(次在左、主在右)。
///
/// 需要自定义内容(协议弹窗的协议链接)时传 [content];
/// 只要「确认/取消」两键的场合直接用 [showConfirmDialog]。
class AppDialog extends StatelessWidget {
  const AppDialog({
    super.key,
    required this.title,
    this.message,
    this.content,
    required this.actions,
  });

  final String title;
  final String? message;
  final Widget? content;
  final List<Widget> actions;

  @override
  Widget build(BuildContext context) => Dialog(
        backgroundColor: AppColors.bgCard,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppRadius.sheet),
        ),
        insetPadding: const EdgeInsets.symmetric(horizontal: AppSpacing.xxl),
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.xxl),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                title,
                textAlign: TextAlign.center,
                style: AppText.subtitle
                    .copyWith(fontSize: 17, color: AppColors.text1),
              ),
              if (message != null) ...[
                const SizedBox(height: AppSpacing.sm),
                Text(
                  message!,
                  textAlign: TextAlign.center,
                  style: AppText.caption.copyWith(color: AppColors.text2),
                ),
              ],
              if (content != null) ...[
                const SizedBox(height: AppSpacing.lg),
                content!,
              ],
              const SizedBox(height: AppSpacing.xxl),
              Row(
                children: [
                  for (var i = 0; i < actions.length; i++) ...[
                    if (i > 0) const SizedBox(width: AppSpacing.md),
                    Expanded(child: actions[i]),
                  ],
                ],
              ),
            ],
          ),
        ),
      );
}

/// 二次确认框:确认返回 true;取消 / 点外部返回 false。
Future<bool> showConfirmDialog(
  BuildContext context, {
  required String title,
  String? message,
  String cancelLabel = '取消',
  required String confirmLabel,
  bool danger = false,
  Key? confirmKey,
  bool barrierDismissible = true,
}) async {
  final confirmed = await showDialog<bool>(
    context: context,
    barrierDismissible: barrierDismissible,
    builder: (context) => AppDialog(
      title: title,
      message: message,
      actions: [
        AppButton(
          label: cancelLabel,
          variant: AppButtonVariant.secondary,
          onPressed: () => Navigator.pop(context, false),
        ),
        AppButton(
          key: confirmKey,
          label: confirmLabel,
          variant:
              danger ? AppButtonVariant.dangerFilled : AppButtonVariant.primary,
          onPressed: () => Navigator.pop(context, true),
        ),
      ],
    ),
  );
  return confirmed == true;
}
