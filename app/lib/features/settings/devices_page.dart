import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_exception.dart';
import '../../core/client_header.dart';
import '../../core/format.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/theme/app_typography.dart';
import '../../core/theme/heart_theme_context.dart';
import '../../core/widgets/app_dialog.dart';
import '../../core/widgets/app_error_view.dart';
import '../../core/widgets/app_list_row.dart';
import '../../core/widgets/app_list_skeleton.dart';
import '../../core/widgets/app_row_group.dart';
import '../../core/widgets/app_sub_page_bar.dart';
import '../../core/widgets/app_text_action.dart';
import '../../core/widgets/app_toast.dart';
import '../auth/session.dart';
import 'devices_controller.dart';
import 'models.dart';
import 'settings_repository.dart';

/// 登录设备(批次 M):二级页顶栏 + 一类端一行,除「本机」外每行可单独下线。
///
/// 列表与 `current` 的口径全在后端(见 `docs/api/auth.md` §1.6):本页只负责展示
/// 「最近活跃 / 首次登录」并给非当前端一个下线动作。
class DevicesPage extends ConsumerWidget {
  const DevicesPage({super.key});

  /// 下线某一端:二次确认 → `DELETE /devices/{client_type}` → 该行消失 + Toast。
  ///
  /// 失败一律按 [ApiException] 的中文 message 提示,不动列表(服务端幂等 204,
  /// 真失败时行还在,用户可重试)。
  Future<void> _logoutDevice(
      BuildContext context, WidgetRef ref, Device device) async {
    final confirmed = await showConfirmDialog(
      context,
      title: '下线「${device.clientLabel}」?',
      message: '该设备需要重新登录才能继续使用,本机不受影响。',
      confirmLabel: '下线',
      danger: true,
      confirmKey: const Key('devices.confirm'),
    );
    if (!confirmed || !context.mounted) return;

    try {
      await ref.read(settingsRepositoryProvider).logoutDevice(device.clientType);
    } on ApiException catch (error) {
      if (context.mounted) AppToast.show(context, error.message);
      return;
    }
    if (!context.mounted) return;

    // 防御:正常不会走到(当前端那行没有下线按钮)。万一后端把 current 标错,
    // 下线 App 端等于注销本端 —— 必须清凭证回登录页,不能留半登录态。
    if (device.current || device.clientType == appClientType) {
      AppToast.show(context, '本机已下线,请重新登录');
      await ref.read(sessionProvider.notifier).logout();
      return;
    }

    await ref.read(devicesProvider.notifier).reload();
    if (!context.mounted) return;
    AppToast.show(context, '已下线「${device.clientLabel}」');
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final colors = context.heart;
    final devices = ref.watch(devicesProvider);
    return Scaffold(
      backgroundColor: colors.bgPage,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            const AppSubPageBar(title: '登录设备'),
            Expanded(
              child: devices.when(
                loading: () => ListView(
                  padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
                  children: const [AppListSkeleton(rowCount: 2)],
                ),
                error: (error, _) => AppErrorView(
                  message: apiMessageOf(error),
                  retryKey: const Key('devices.retry'),
                  onRetry: () => ref.read(devicesProvider.notifier).reload(),
                ),
                data: (items) => ListView(
                  // 底部让开系统手势条,与设置页同口径(edge-to-edge 设备)
                  padding: EdgeInsets.fromLTRB(
                      AppSpacing.pageH,
                      AppSpacing.md,
                      AppSpacing.pageH,
                      AppSpacing.xxl + MediaQuery.viewPaddingOf(context).bottom),
                  children: [
                    AppRowGroup(
                      children: [
                        for (final device in items)
                          _deviceRow(context, ref, device),
                      ],
                    ),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  /// 一行一个端:端名 + 「最近活跃 / 首次登录」;当前端标「本机」且没有下线按钮。
  Widget _deviceRow(BuildContext context, WidgetRef ref, Device device) {
    final colors = context.heart;
    return AppListRow(
      key: Key('devices.row.${device.clientType}'),
      icon: _iconOf(device.clientType),
      title: device.clientLabel,
      subtitle: _subtitleOf(device),
      showChevron: false,
      trailing: device.current
          ? Text(
              '本机',
              key: Key('devices.current.${device.clientType}'),
              style: AppText.caption.copyWith(
                color: colors.brand,
                fontWeight: FontWeight.w600,
              ),
            )
          : AppTextAction(
              key: Key('devices.logout.${device.clientType}'),
              label: '下线',
              danger: true,
              onPressed: () => _logoutDevice(context, ref, device),
            ),
    );
  }
}

/// 端类型 → 图标;只认 `app` / `web`,将来多端时兜底成通用设备图标。
IconData _iconOf(String clientType) => switch (clientType) {
      'app' => Icons.smartphone_rounded,
      'web' => Icons.computer_rounded,
      _ => Icons.devices_rounded,
    };

/// 副标题:`最近活跃 ${相对时间} · 首次登录 ${日期}`。
///
/// `last_active_at == null` 时不显示空值,按契约给一句人话(该端只有登录记录,
/// 还没刷新过令牌)。
String _subtitleOf(Device device) {
  final lastActiveAt = device.lastActiveAt;
  final active = lastActiveAt == null
      ? '尚未在此端刷新过'
      : '最近活跃 ${formatLastActive(lastActiveAt)}';
  final createdAt = device.createdAt;
  return '$active · 首次登录 ${createdAt == null ? '未知' : formatDate(createdAt)}';
}
