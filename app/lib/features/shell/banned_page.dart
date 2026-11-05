import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/theme/app_spacing.dart';
import '../../core/theme/app_typography.dart';
import '../../core/widgets/app_button.dart';
import '../auth/session.dart';
import '../profile/models.dart';
import '../../core/theme/heart_theme_context.dart';

/// 重封禁用户看到的整屏提示(替代主框架):原因 + 退出登录。
/// 大号元素用 `danger@12%` 圆底 + `block_rounded`(§7 禁止灰色图标占位)。
class BannedPage extends ConsumerWidget {
  const BannedPage({super.key, required this.profile});

  final Profile profile;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final colors = context.heart;
    return Scaffold(
        backgroundColor: colors.bgPage,
        body: Center(
          child: Padding(
            padding: const EdgeInsets.all(AppSpacing.xxl),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Container(
                  width: 96,
                  height: 96,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: colors.danger.withValues(alpha: .12),
                  ),
                  child: Icon(Icons.block_rounded,
                      size: 40, color: colors.danger),
                ),
                const SizedBox(height: AppSpacing.lg),
                Text('账号已被封禁',
                    style: AppText.title.copyWith(color: colors.text1)),
                if (profile.banReason.isNotEmpty) ...[
                  const SizedBox(height: AppSpacing.sm),
                  Text('原因:${profile.banReason}',
                      style: AppText.caption.copyWith(color: colors.text2)),
                ],
                const SizedBox(height: AppSpacing.sm),
                Text('封禁期间所有功能暂停使用',
                    style: AppText.caption.copyWith(color: colors.text2)),
                const SizedBox(height: AppSpacing.sm),
                Text('如有疑问请联系客服',
                    style: AppText.micro.copyWith(color: colors.text3)),
                const SizedBox(height: AppSpacing.xxl),
                AppButton(
                  key: const Key('banned.logout'),
                  label: '退出登录',
                  variant: AppButtonVariant.dangerFilled,
                  onPressed: () => ref.read(sessionProvider.notifier).logout(),
                ),
              ],
            ),
          ),
        ),
      );
  }
}
