import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_exception.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/widgets/app_dialog.dart';
import '../../core/widgets/app_list_row.dart';
import '../../core/widgets/app_row_group.dart';
import '../../core/widgets/app_sub_page_bar.dart';
import '../../core/widgets/app_toast.dart';
import '../auth/session.dart';
import 'settings_repository.dart';
import 'widgets/delete_account_dialog.dart';
import 'widgets/theme_mode_row.dart';
import 'widgets/visits_hidden_row.dart';
import '../../core/theme/heart_theme_context.dart';

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

  /// 注销账号:第一步后果说明 → 第二步输入手机号 → 成功即走登出通道回登录页。
  /// 不可恢复,所以两次确认缺一不可。
  Future<void> _deleteAccount(BuildContext context, WidgetRef ref) async {
    final confirmed = await showConfirmDialog(
      context,
      title: '注销账号?',
      message: '注销后,你的资料、照片、配对关系、聊天关系与广场动态将被永久删除,且无法恢复。',
      confirmLabel: '继续',
      danger: true,
    );
    if (!confirmed) return;
    if (!context.mounted) return;

    final phone = await showDeleteAccountDialog(context);
    if (phone == null) return;
    if (!context.mounted) return;

    try {
      await ref.read(settingsRepositoryProvider).deleteAccount(phone);
    } on ApiException catch (error) {
      if (!context.mounted) return;
      AppToast.show(context, error.message);
      return;
    }
    if (!context.mounted) return;
    AppToast.show(context, '账号已注销');
    await ref.read(sessionProvider.notifier).logout();
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final colors = context.heart;
    return Scaffold(
        backgroundColor: colors.bgPage,
        body: SafeArea(
          bottom: false,
          child: Column(
            children: [
              const AppSubPageBar(title: '设置'),
              Expanded(
                child: ListView(
                  key: const Key('settings.list'),
                  // 底部额外让开系统手势条:设置页内容会随分组增长(2026-11-05 新增「外观」卡后
                  // 已贴到底),edge-to-edge 设备上最后一张卡会压进手势区
                  padding: EdgeInsets.fromLTRB(
                      AppSpacing.pageH,
                      AppSpacing.md,
                      AppSpacing.pageH,
                      AppSpacing.xxl + MediaQuery.viewPaddingOf(context).bottom),
                  children: [
                    AppRowGroup(
                      children: [
                        const VisitsHiddenRow(),
                        AppListRow(
                          key: const Key('settings.row.blocks'),
                          icon: Icons.block_rounded,
                          title: '黑名单',
                          onTap: () => context.push('/settings/blocks'),
                        ),
                        AppListRow(
                          key: const Key('settings.row.notifications'),
                          icon: Icons.notifications_rounded,
                          title: '通知设置',
                          onTap: () => context.push('/settings/notifications'),
                        ),
                        AppListRow(
                          key: const Key('settings.row.devices'),
                          icon: Icons.devices_rounded,
                          title: '登录设备',
                          onTap: () => context.push('/settings/devices'),
                        ),
                      ],
                    ),
                    const SizedBox(height: AppSpacing.cardGap),
                    AppRowGroup(
                      children: [
                        // 我的数据(批次 P):纯只读报告页,放「查看类」这一组的第一行
                        AppListRow(
                          key: const Key('settings.row.stats'),
                          icon: Icons.insights_rounded,
                          title: '我的数据',
                          onTap: () => context.push('/settings/stats'),
                        ),
                        AppListRow(
                          key: const Key('settings.row.feedback'),
                          icon: Icons.feedback_rounded,
                          title: '意见反馈',
                          onTap: () => context.push('/settings/feedback'),
                        ),
                        AppListRow(
                          key: const Key('settings.row.about'),
                          icon: Icons.info_rounded,
                          title: '关于',
                          onTap: () => context.push('/settings/about'),
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
                          key: const Key('settings.row.deleteAccount'),
                          title: '注销账号',
                          centerTitle: true,
                          danger: true,
                          onTap: () => _deleteAccount(context, ref),
                        ),
                        AppListRow(
                          key: const Key('settings.logout'),
                          title: '退出登录',
                          centerTitle: true,
                          danger: true,
                          onTap: () => _logout(context, ref),
                        ),
                      ],
                    ),
                    const SizedBox(height: AppSpacing.cardGap),
                    // 外观放最后:注销/退出登录这类危险动作仍留在上方一屏内(§7 操作层级)
                    AppRowGroup(
                      children: [
                        const ThemeModeRow(),
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
}
