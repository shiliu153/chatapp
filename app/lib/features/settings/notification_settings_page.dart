import 'package:flutter/material.dart';

import '../../core/theme/app_colors.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/theme/app_typography.dart';
import '../../core/widgets/app_list_row.dart';
import '../../core/widgets/app_row_group.dart';
import '../../core/widgets/app_sub_page_bar.dart';

/// 通知设置骨架:推送尚未上线,开关只读并明确标注。
class NotificationSettingsPage extends StatelessWidget {
  const NotificationSettingsPage({super.key});

  @override
  Widget build(BuildContext context) => Scaffold(
        backgroundColor: AppColors.bgPage,
        body: SafeArea(
          bottom: false,
          child: Column(
            children: [
              const AppSubPageBar(title: '通知设置'),
              Expanded(
                child: ListView(
                  padding: const EdgeInsets.fromLTRB(AppSpacing.pageH,
                      AppSpacing.md, AppSpacing.pageH, AppSpacing.xxl),
                  children: [
                    AppRowGroup(
                      children: [
                        _NotifyRow(
                          key: const Key('notifications.match'),
                          icon: Icons.favorite_rounded,
                          title: '新配对提醒',
                          subtitle: '有人和你互相喜欢时提醒你',
                        ),
                        _NotifyRow(
                          key: const Key('notifications.message'),
                          icon: Icons.chat_bubble_rounded,
                          title: '新消息提醒',
                          subtitle: '收到新消息时提醒你',
                        ),
                      ],
                    ),
                    const SizedBox(height: AppSpacing.lg),
                    Text(
                      '推送功能将在后续版本上线,届时可以分别控制这两类提醒。当前开关仅为占位,不会保存任何设置。',
                      style: AppText.caption.copyWith(color: AppColors.text3),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      );
}

class _NotifyRow extends StatelessWidget {
  const _NotifyRow({
    super.key,
    required this.icon,
    required this.title,
    required this.subtitle,
  });

  final IconData icon;
  final String title;
  final String subtitle;

  @override
  Widget build(BuildContext context) => AppListRow(
        icon: icon,
        title: title,
        subtitle: subtitle,
        showChevron: false,
        trailing: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text('即将上线',
                style: AppText.micro.copyWith(color: AppColors.text3)),
            const SizedBox(width: AppSpacing.xs),
            Switch.adaptive(value: false, onChanged: null),
          ],
        ),
      );
}
