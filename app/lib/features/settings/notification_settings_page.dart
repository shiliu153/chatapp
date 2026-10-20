import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_exception.dart';
import '../../core/push/push_controller.dart';
import '../../core/push/push_repository.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/theme/app_typography.dart';
import '../../core/widgets/app_error_view.dart';
import '../../core/widgets/app_list_row.dart';
import '../../core/widgets/app_row_group.dart';
import '../../core/widgets/app_sub_page_bar.dart';
import '../../core/widgets/app_toast.dart';

/// 通知设置:三项真实开关(账号级)+ 系统通知权限提示。
class NotificationSettingsPage extends ConsumerStatefulWidget {
  const NotificationSettingsPage({super.key});

  @override
  ConsumerState<NotificationSettingsPage> createState() => _NotificationSettingsPageState();
}

class _NotificationSettingsPageState extends ConsumerState<NotificationSettingsPage> {
  PushPreferences? _prefs;
  bool _loading = true;
  String? _error;
  bool _notificationEnabled = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final prefs = await ref.read(pushRepositoryProvider).fetchPreferences();
      final enabled = await ref.read(pushServiceProvider).isNotificationEnabled();
      if (!mounted) return;
      setState(() {
        _prefs = prefs;
        _notificationEnabled = enabled;
        _loading = false;
      });
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _error = error.message;
        _loading = false;
      });
    }
  }

  Future<void> _toggle({bool? likes, bool? matches, bool? system}) async {
    final current = _prefs;
    if (current == null) return;
    final next = current.copyWith(likes: likes, matches: matches, system: system);
    setState(() => _prefs = next); // 乐观更新
    try {
      final saved = await ref
          .read(pushRepositoryProvider)
          .updatePreferences(likes: likes, matches: matches, system: system);
      if (!mounted) return;
      setState(() => _prefs = saved);
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() => _prefs = current); // 失败回滚
      AppToast.show(context, error.message);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        backgroundColor: AppColors.bgPage,
        body: SafeArea(
          bottom: false,
          child: Column(
            children: [
              const AppSubPageBar(title: '通知设置'),
              Expanded(child: _body()),
            ],
          ),
        ),
      );

  Widget _body() {
    if (_loading) return const Center(child: CircularProgressIndicator());
    final error = _error;
    if (error != null) {
      return AppErrorView(message: error, onRetry: _load);
    }
    final prefs = _prefs!;
    return ListView(
      padding: const EdgeInsets.fromLTRB(
          AppSpacing.pageH, AppSpacing.md, AppSpacing.pageH, AppSpacing.xxl),
      children: [
        if (!_notificationEnabled) ...[
          AppRowGroup(children: [
            AppListRow(
              key: const Key('notifications.permission'),
              icon: Icons.notifications_off_rounded,
              title: '系统通知未开启',
              subtitle: '开启后才能收到提醒',
              showChevron: false,
              trailing: Text('去开启',
                  style: AppText.body.copyWith(color: AppColors.brand)),
              onTap: () => ref.read(pushServiceProvider).openNotificationSettings(),
            ),
          ]),
          const SizedBox(height: AppSpacing.cardGap),
        ],
        AppRowGroup(children: [
          _NotifyRow(
            key: const Key('notifications.likes'),
            icon: Icons.favorite_rounded,
            title: '新的喜欢',
            subtitle: '有人喜欢你时提醒你',
            value: prefs.likes,
            onChanged: (value) => _toggle(likes: value),
          ),
          _NotifyRow(
            key: const Key('notifications.matches'),
            icon: Icons.celebration_rounded,
            title: '配对成功',
            subtitle: '互相喜欢时提醒你',
            value: prefs.matches,
            onChanged: (value) => _toggle(matches: value),
          ),
          _NotifyRow(
            key: const Key('notifications.system'),
            icon: Icons.shield_rounded,
            title: '系统通知',
            subtitle: '举报处理、账号限制等通知',
            value: prefs.system,
            onChanged: (value) => _toggle(system: value),
          ),
        ]),
        const SizedBox(height: AppSpacing.lg),
        Text('新消息提醒需要接入离线推送,将在后续版本开放',
            style: AppText.caption.copyWith(color: AppColors.text3)),
      ],
    );
  }
}

class _NotifyRow extends StatelessWidget {
  const _NotifyRow({
    super.key,
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.value,
    required this.onChanged,
  });

  final IconData icon;
  final String title;
  final String subtitle;
  final bool value;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) => AppListRow(
        icon: icon,
        title: title,
        subtitle: subtitle,
        showChevron: false,
        trailing: Switch.adaptive(value: value, onChanged: onChanged),
      );
}
