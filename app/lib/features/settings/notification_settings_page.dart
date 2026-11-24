import 'package:flutter/material.dart';
import 'package:phosphor_glyphs/phosphor_glyphs.dart';

import '../../core/theme/app_typography.dart';
import '../../core/theme/ember_theme_context.dart';
import '../../core/theme/tokens.g.dart' as tokens;
import '../../core/ui/ember_ui.dart';
import 'widgets/settings_rows.dart';

/// 通知设置(E-5.6b 迁移到 Ember):推送尚未上线,开关只读并明确标注。
///
/// 只换皮:两条提醒项、文案与「只读」口径不变。形态 = §9.4 二级页 shell + 一张分组卡,
/// 每行是 [`EmberSettingsTile`] 的**开关行**(`switchValue` 给值、`onChanged` 给
/// `null` = 不可切换),「即将上线」落在副标题上 —— 规范的行形态只有「标题 + 副标题 +
/// 右侧 slot」,而右侧 slot 已被开关占用(同一行右侧只放一件事,`EmberSettingsTile`
/// 构造时断言拦下 `switchValue` + `trailing` 同时出现)。
///
/// 读屏(page spec §6 第 3 条):两行分别播报「新配对提醒,已关闭」「新消息提醒,已关闭」。
class NotificationSettingsPage extends StatelessWidget {
  /// 构造通知设置页。
  const NotificationSettingsPage({super.key});

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    return EmberPageScaffold(
      title: '通知设置',
      backKey: const Key('notifications.back'),
      body: ListView(
        padding: EdgeInsets.only(
          top: tokens.space16,
          bottom: tokens.space40 + MediaQuery.viewPaddingOf(context).bottom,
        ),
        children: [
          SettingsGroup(
            children: [
              EmberSettingsTile(
                key: const Key('notifications.match'),
                icon: PhosphorIconsRegular.heart,
                title: '新配对提醒',
                subtitle: '即将上线 · 有人和你互相喜欢时提醒你',
                switchValue: false,
                onChanged: null,
                showDivider: true,
                padding: settingsRowPadding,
              ),
              EmberSettingsTile(
                key: const Key('notifications.message'),
                icon: PhosphorIconsRegular.chatCircleDots,
                title: '新消息提醒',
                subtitle: '即将上线 · 收到新消息时提醒你',
                switchValue: false,
                onChanged: null,
                padding: settingsRowPadding,
              ),
            ],
          ),
          SizedBox(height: tokens.space16),
          Text(
            '推送功能将在后续版本上线,届时可以分别控制这两类提醒。当前开关仅为占位,不会保存任何设置。',
            style: AppText.caption.copyWith(color: colors.textSecondary),
          ),
        ],
      ),
    );
  }
}
