import 'package:flutter/material.dart';

import '../theme/app_spacing.dart';
import '../theme/app_typography.dart';
import 'app_button.dart';
import '../theme/heart_theme_context.dart';

/// 「心跳」附录 B.8 错误态:标题 17/w600 + 原因 13 text2 + 可选「重试」。
/// 页面统一用它;原因取接口中文 message,不显示裸异常串。
class AppErrorView extends StatelessWidget {
  const AppErrorView({
    super.key,
    this.title = '没能加载出来',
    required this.message,
    this.onRetry,
    this.retryKey,
  });

  final String title;
  final String message;
  final VoidCallback? onRetry;
  final Key? retryKey;

  @override
  Widget build(BuildContext context) {
    final colors = context.heart;
    return Center(
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.xxl),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(title, style: AppText.subtitle.copyWith(fontSize: 17)),
              const SizedBox(height: AppSpacing.sm),
              Text(
                message,
                textAlign: TextAlign.center,
                style: AppText.caption.copyWith(color: colors.text2),
              ),
              if (onRetry != null) ...[
                const SizedBox(height: AppSpacing.lg),
                AppButton(
                  key: retryKey,
                  label: '重试',
                  variant: AppButtonVariant.secondary,
                  onPressed: onRetry,
                ),
              ],
            ],
          ),
        ),
      );
  }
}
