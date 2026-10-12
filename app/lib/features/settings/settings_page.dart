import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/theme/app_colors.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/widgets/app_dialog.dart';
import '../../core/widgets/app_list_row.dart';
import '../../core/widgets/app_row_group.dart';
import '../../core/widgets/app_sub_page_bar.dart';
import '../auth/session.dart';

/// 设置页(附录 E):二级页顶栏 + 两张行分组卡。
class SettingsPage extends ConsumerWidget {
  const SettingsPage({super.key});

  Future<void> _logout(BuildContext context, WidgetRef ref) async {
    final confirmed = await showConfirmDialog(
      context,
      title: '退出登录?',
      message: '退出后需要重新用手机号登录',
      confirmLabel: '退出',
      danger: true,
    );
    if (!confirmed) return;
    await ref.read(sessionProvider.notifier).logout();
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) => Scaffold(
        backgroundColor: AppColors.bgPage,
        body: SafeArea(
          bottom: false,
          child: Column(
            children: [
              const AppSubPageBar(title: '设置'),
              Expanded(
                child: ListView(
                  padding: const EdgeInsets.fromLTRB(AppSpacing.pageH,
                      AppSpacing.md, AppSpacing.pageH, AppSpacing.xxl),
                  children: [
                    AppRowGroup(
                      children: [
                        AppListRow(
                          key: const Key('settings.row.blocks'),
                          icon: Icons.block_rounded,
                          title: '黑名单',
                          onTap: () => context.push('/settings/blocks'),
                        ),
                        AppListRow(
                          key: const Key('settings.row.agreement'),
                          icon: Icons.description_rounded,
                          title: '用户协议',
                          onTap: () => context.push('/legal/agreement'),
                        ),
                        AppListRow(
                          key: const Key('settings.row.privacy'),
                          icon: Icons.privacy_tip_rounded,
                          title: '隐私政策',
                          onTap: () => context.push('/legal/privacy'),
                        ),
                      ],
                    ),
                    const SizedBox(height: AppSpacing.cardGap),
                    AppRowGroup(
                      children: [
                        AppListRow(
                          key: const Key('settings.logout'),
                          title: '退出登录',
                          centerTitle: true,
                          danger: true,
                          onTap: () => _logout(context, ref),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      );
}
