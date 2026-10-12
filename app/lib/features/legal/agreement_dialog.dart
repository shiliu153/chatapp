import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../core/theme/app_spacing.dart';
import '../../core/widgets/app_button.dart';
import '../../core/widgets/app_dialog.dart';
import '../../core/widgets/app_text_action.dart';

/// 首启协议弹窗:不可点外部关闭;同意返回 true,不同意返回 false。
Future<bool?> showAgreementDialog(BuildContext context) => showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (context) => AppDialog(
        title: '用户协议与隐私政策',
        message: '欢迎使用「交友 Chat」。请阅读并同意以下文件后再开始使用:',
        content: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            AppTextAction(
              label: '《用户协议》',
              onPressed: () => context.push('/legal/agreement'),
            ),
            const SizedBox(height: AppSpacing.xs),
            AppTextAction(
              label: '《隐私政策》',
              onPressed: () => context.push('/legal/privacy'),
            ),
          ],
        ),
        actions: [
          AppButton(
            key: const Key('agreement.decline'),
            label: '不同意',
            variant: AppButtonVariant.secondary,
            onPressed: () => Navigator.pop(context, false),
          ),
          AppButton(
            key: const Key('agreement.accept'),
            label: '同意并继续',
            onPressed: () => Navigator.pop(context, true),
          ),
        ],
      ),
    );
