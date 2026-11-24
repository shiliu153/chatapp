import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:phosphor_glyphs/phosphor_glyphs.dart';

import '../../core/api_exception.dart';
import '../../core/client_header.dart';
import '../../core/format.dart';
import '../../core/theme/app_typography.dart';
import '../../core/theme/ember_theme_context.dart';
import '../../core/theme/tokens.g.dart' as tokens;
import '../../core/ui/ember_ui.dart';
import '../auth/session.dart';
import 'devices_controller.dart';
import 'models.dart';
import 'settings_repository.dart';
import 'widgets/settings_illustration.dart';
import 'widgets/settings_rows.dart';

/// 登录设备(批次 M,E-5.6b 迁移到 Ember):一类端一行,除「本机」外每行可单独下线。
///
/// 列表与 `current` 的口径全在后端(见 `docs/api/auth.md` §1.6):本页只负责展示
/// 「最近活跃 / 首次登录」并给非当前端一个下线动作。
///
/// 只换皮:确认文案、请求路径、当前端防御性登出都与迁移前一致。形态 = §9.4 shell +
/// 一张分组卡,每行 [`EmberSettingsTile`];行内「下线」是 `EmberButton` 文字变体
/// (spec §8.3「文字按钮 = `brand.default` 15/w600,无底」),确认框换 [`EmberDialog`]。
class DevicesPage extends ConsumerWidget {
  /// 构造登录设备页。
  const DevicesPage({super.key});

  /// 下线某一端:二次确认 → `DELETE /devices/{client_type}` → 该行消失 + Toast。
  ///
  /// 失败一律按 [ApiException] 的中文 message 提示,不动列表(服务端幂等 204,
  /// 真失败时行还在,用户可重试)。
  Future<void> _logoutDevice(
      BuildContext context, WidgetRef ref, Device device) async {
    final confirmed = await showEmberDialog(
      context,
      icon: PhosphorIconsRegular.signOut,
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
      if (context.mounted) EmberToast.show(context, error.message);
      return;
    }
    if (!context.mounted) return;

    // 防御:正常不会走到(当前端那行没有下线按钮)。万一后端把 current 标错,
    // 下线 App 端等于注销本端 —— 必须清凭证回登录页,不能留半登录态。
    if (device.current || device.clientType == appClientType) {
      EmberToast.show(context, '本机已下线,请重新登录');
      await ref.read(sessionProvider.notifier).logout();
      return;
    }

    await ref.read(devicesProvider.notifier).reload();
    if (!context.mounted) return;
    EmberToast.show(context, '已下线「${device.clientLabel}」');
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final devices = ref.watch(devicesProvider);
    return EmberPageScaffold(
      title: '登录设备',
      backKey: const Key('devices.back'),
      body: devices.when(
        loading: () => const _DevicesSkeleton(),
        // §5「加载失败」:EmberEmpty 错误形态 + 「重试」(不用灰色图标)
        error: (error, _) => Center(
          child: Padding(
            padding: EdgeInsets.all(tokens.space24),
            child: EmberEmpty(
              illustration: const SettingsIllustration(
                SettingsIllustrationKind.loadFailed,
              ),
              title: '设备列表没能加载出来',
              description: apiMessageOf(error),
              actionLabel: '重试',
              actionKey: const Key('devices.retry'),
              onAction: () => ref.read(devicesProvider.notifier).reload(),
            ),
          ),
        ),
        data: (items) => items.isEmpty
            ? Center(
                child: Padding(
                  padding: EdgeInsets.all(tokens.space24),
                  child: EmberEmpty(
                    illustration: const SettingsIllustration(
                      SettingsIllustrationKind.listEmpty,
                    ),
                    title: '还没有其他登录设备',
                    description: '在别的设备上登录后会出现在这里',
                  ),
                ),
              )
            : ListView(
                // 底部让开系统手势条,与设置页同口径(edge-to-edge 设备)
                padding: EdgeInsets.only(
                  top: tokens.space12,
                  bottom: tokens.space40 +
                      MediaQuery.viewPaddingOf(context).bottom,
                ),
                children: [
                  SettingsGroup(
                    children: [
                      for (final (index, device) in items.indexed)
                        _deviceRow(
                          context,
                          ref,
                          device,
                          showDivider: index < items.length - 1,
                        ),
                    ],
                  ),
                ],
              ),
      ),
    );
  }

  /// 一行一个端:端名 + 「最近活跃 / 首次登录」;当前端标「本机」且没有下线按钮。
  ///
  /// 读屏标签自己拼一次而不是用组件的默认值:行内右侧的「下线」按钮会被
  /// `EmberSettingsTile` 的 `ExcludeSemantics` 一起挡在语义树外(组件设计如此 ——
  /// 整行算一件事),所以标签里必须把「下线」这个动作念出来,否则读屏用户看不到
  /// 这一行还能做什么。
  Widget _deviceRow(
    BuildContext context,
    WidgetRef ref,
    Device device, {
    required bool showDivider,
  }) {
    final colors = context.ember;
    final subtitle = _subtitleOf(device);
    return EmberSettingsTile(
      key: Key('devices.row.${device.clientType}'),
      icon: _iconOf(device.clientType),
      title: device.clientLabel,
      subtitle: subtitle,
      semanticLabel: '${device.clientLabel},$subtitle,'
          '${device.current ? '本机' : '下线'}',
      showDivider: showDivider,
      padding: settingsRowPadding,
      // 整行可点 = 下线(与右侧按钮同一个动作),读屏的点击动作也落在这里
      onTap: device.current ? null : () => _logoutDevice(context, ref, device),
      trailing: device.current
          ? Text(
              '本机',
              key: Key('devices.current.${device.clientType}'),
              style: AppText.caption.copyWith(
                color: colors.brandDefault,
                fontWeight: FontWeight.w600,
              ),
            )
          : EmberButton(
              key: Key('devices.logout.${device.clientType}'),
              label: '下线',
              variant: EmberButtonVariant.text,
              onPressed: () => _logoutDevice(context, ref, device),
            ),
    );
  }
}

/// 加载骨架:两行「图标 + 两条文字条」,形状与真实行一致(不跳版)。
class _DevicesSkeleton extends StatelessWidget {
  const _DevicesSkeleton();

  @override
  Widget build(BuildContext context) => ListView(
        key: const Key('devices.skeleton'),
        padding: EdgeInsets.symmetric(vertical: tokens.space12),
        children: [
          for (var i = 0; i < 2; i++)
            Padding(
              padding: settingsRowPadding,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  EmberSkeleton(width: 120, height: tokens.fontSizeSubtitle),
                  SizedBox(height: tokens.space8),
                  EmberSkeleton(width: 220, height: tokens.fontSizeCaption),
                ],
              ),
            ),
        ],
      );
}

/// 端类型 → 图标;只认 `app` / `web`,将来多端时兜底成通用设备图标。
IconData _iconOf(String clientType) => switch (clientType) {
      'app' => PhosphorIconsRegular.deviceMobile,
      'web' => PhosphorIconsRegular.desktop,
      _ => PhosphorIconsRegular.devices,
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
