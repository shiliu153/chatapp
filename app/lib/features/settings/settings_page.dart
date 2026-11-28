import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:phosphor_glyphs/phosphor_glyphs.dart';

import '../../core/api_exception.dart';
import '../../core/theme/tokens.g.dart' as tokens;
import '../../core/ui/ember_ui.dart';
import '../auth/session.dart';
import 'settings_repository.dart';
import 'widgets/delete_account_dialog.dart';
import 'widgets/settings_rows.dart';
import 'widgets/theme_mode_row.dart';
import 'widgets/visits_hidden_row.dart';

/// 设置页(附录 E,E-5.6b 迁移到 Ember):§9.4 二级页 shell + 四张分组卡。
///
/// 只换皮,设置项与跳转目标一字不动。逐格对齐 page spec §3 / §4:
/// - 顶栏走 [`EmberPageScaffold`](52 高、返回 22、标题 17/w600 居中);
/// - 列表行走 [`EmberSettingsTile`](行高 68–76、标题 17/w600、副标题 13);
/// - 分组容器走 `EmberCard`(`radius.lg`,深色换 `border.divider` 描边);
/// - 危险动作(注销账号 / 退出登录)走 [`EmberButton`] 危险变体:默认只有
///   `status.danger` 描边,**实底只在二次确认之后**(§8.3 危险按钮 pressed 行);
/// - 图标换 Phosphor,动效走 `EmberPressable` 的 spring。
///
/// 顺序仍是「日常设置 → 查看类 → 危险动作 → 外观」:注销 / 退出留在上方一屏内,
/// 外观卡放最后(迁移前的口径,§7 操作层级)。
class SettingsPage extends ConsumerWidget {
  /// 构建设置页。
  const SettingsPage({super.key});

  Future<void> _logout(BuildContext context, WidgetRef ref) async {
    // 破坏性确认 = Dialog + 图标 + 明确动词(§9.3),不再用自绘 AppDialog
    final confirmed = await showEmberDialog(
      context,
      icon: PhosphorIconsRegular.signOut,
      title: '退出登录?',
      message: '退出后需要重新用手机号登录',
      confirmLabel: '退出',
      danger: true,
    );
    if (!confirmed) return;
    await ref.read(sessionProvider.notifier).logout();
  }

  /// 注销账号:第一步后果说明 → 第二步输入手机号 → 成功即走登出通道回登录页。
  /// 不可恢复,所以两次确认缺一不可(与迁移前完全一致)。
  Future<void> _deleteAccount(BuildContext context, WidgetRef ref) async {
    final confirmed = await showEmberDialog(
      context,
      icon: PhosphorIconsRegular.trash,
      title: '注销账号?',
      message: '注销后,你的资料、照片、配对关系、聊天关系与广场动态将被永久删除,且无法恢复。',
      // §9.3「明确动词」:念出来就知道这一步会做什么
      confirmLabel: '继续注销',
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
      EmberToast.show(context, error.message);
      return;
    }
    if (!context.mounted) return;
    EmberToast.show(context, '账号已注销');
    await ref.read(sessionProvider.notifier).logout();
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return EmberPageScaffold(
      title: '设置',
      backKey: const Key('settings.back'),
      body: ListView(
        key: const Key('settings.list'),
        // 横向 20 由 shell 给(§9.4);底部额外让开系统手势条 —— 内容会随分组增长,
        // edge-to-edge 设备上最后一张卡会压进手势区(迁移前踩过)。
        padding: EdgeInsets.only(
          top: tokens.space16,
          bottom: tokens.space40 + MediaQuery.viewPaddingOf(context).bottom,
        ),
        children: [
          SettingsGroup(
            children: [
              const VisitsHiddenRow(),
              _entryRow(
                key: const Key('settings.row.blocks'),
                icon: PhosphorIconsRegular.prohibit,
                title: '黑名单',
                onTap: () => context.push('/settings/blocks'),
              ),
              _entryRow(
                key: const Key('settings.row.notifications'),
                icon: PhosphorIconsRegular.bellSimple,
                title: '通知设置',
                onTap: () => context.push('/settings/notifications'),
              ),
              _entryRow(
                key: const Key('settings.row.devices'),
                icon: PhosphorIconsRegular.devices,
                title: '登录设备',
                showDivider: false,
                onTap: () => context.push('/settings/devices'),
              ),
            ],
          ),
          SizedBox(height: tokens.space12),
          SettingsGroup(
            children: [
              // 我的数据(批次 P):纯只读报告页,放「查看类」这一组的第一行
              _entryRow(
                key: const Key('settings.row.stats'),
                icon: PhosphorIconsRegular.chartBar,
                title: '我的数据',
                onTap: () => context.push('/settings/stats'),
              ),
              _entryRow(
                key: const Key('settings.row.feedback'),
                icon: PhosphorIconsRegular.chatCircleDots,
                title: '意见反馈',
                onTap: () => context.push('/settings/feedback'),
              ),
              _entryRow(
                key: const Key('settings.row.about'),
                icon: PhosphorIconsRegular.info,
                title: '关于',
                onTap: () => context.push('/settings/about'),
              ),
              _entryRow(
                key: const Key('settings.row.agreement'),
                icon: PhosphorIconsRegular.fileText,
                title: '用户协议',
                onTap: () => context.push('/legal/agreement'),
              ),
              _entryRow(
                key: const Key('settings.row.privacy'),
                icon: PhosphorIconsRegular.shieldCheck,
                title: '隐私政策',
                showDivider: false,
                onTap: () => context.push('/legal/privacy'),
              ),
            ],
          ),
          SizedBox(height: tokens.space12),
          EmberCard(
            padding: EdgeInsets.symmetric(
              horizontal: tokens.space20,
              vertical: tokens.space16,
            ),
            child: Column(
              children: [
                EmberButton(
                  key: const Key('settings.row.deleteAccount'),
                  label: '注销账号',
                  variant: EmberButtonVariant.danger,
                  expand: true,
                  onPressed: () => _deleteAccount(context, ref),
                ),
                SizedBox(height: tokens.space12),
                EmberButton(
                  key: const Key('settings.logout'),
                  label: '退出登录',
                  variant: EmberButtonVariant.danger,
                  expand: true,
                  onPressed: () => _logout(context, ref),
                ),
              ],
            ),
          ),
          SizedBox(height: tokens.space12),
          // 外观放最后:注销 / 退出登录这类危险动作仍留在上方一屏内(§7 操作层级)
          const ThemeModeRow(),
        ],
      ),
    );
  }

  /// 进下级的入口行:图标 + 标题 + 右侧箭头。
  ///
  /// 行内的读屏标签由 `EmberSettingsTile` 统一给(标题 + 副标题),这里不重复拼 ——
  /// 同一棵语义树里叠两层标签会让读屏把标题念两遍。
  Widget _entryRow({
    required Key key,
    required IconData icon,
    required String title,
    required VoidCallback onTap,
    bool showDivider = true,
  }) =>
      EmberSettingsTile(
        key: key,
        icon: icon,
        title: title,
        showChevron: true,
        showDivider: showDivider,
        padding: settingsRowPadding,
        onTap: onTap,
      );
}
