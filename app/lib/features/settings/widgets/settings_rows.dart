import 'package:flutter/material.dart';

import '../../../core/theme/tokens.g.dart' as tokens;
import '../../../core/ui/ember_ui.dart';

/// 设置线(E-5.6b)里「卡片内一行」的内边距:横向 20 + 纵向 12。
///
/// 为什么需要它:[`EmberSettingsTile`] 默认只给纵向 12(横向留给页面或 `EmberCard`),
/// 而设置线的分组用 `EmberCard(padding: EdgeInsets.zero)` —— 卡片不留内边距,分隔线
/// 才能像 spec §5.2 那样铺满整行宽度;横向 20 于是由行自己补。集中一处,免得四个
/// 页面各写一份数字(裸间距是 Ember 明令禁止的,见 §3.3)。
const settingsRowPadding = EdgeInsets.symmetric(
  horizontal: tokens.space20,
  vertical: tokens.space12,
);

/// 设置线的分组卡:一张 `EmberCard`(`radius.lg` + 明暗两套层级)包住若干
/// [`EmberSettingsTile`](或危险按钮、分段控件)。
///
/// **卡片内边距为 0**:行自己带 [settingsRowPadding],分隔线才能铺满卡片宽度。
/// 组与组之间的 12 间距由页面给(spec §5.2「卡片间距 12」),不在这里猜。
class SettingsGroup extends StatelessWidget {
  /// 构造分组卡。
  const SettingsGroup({super.key, required this.children});

  /// 组内各行(自上而下,分隔线由各行自己按 `showDivider` 决定)。
  final List<Widget> children;

  @override
  Widget build(BuildContext context) => EmberCard(
        padding: EdgeInsets.zero,
        child: Column(children: children),
      );
}
