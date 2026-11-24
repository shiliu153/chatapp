import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:phosphor_glyphs/phosphor_glyphs.dart';

import '../../../core/api_exception.dart';
import '../../../core/ui/ember_ui.dart';
import '../../profile/profile_controller.dart';
import 'settings_rows.dart';

/// 「隐身浏览」开关行(E-5.6b 迁移到 Ember):乐观更新,失败回滚并提示。
///
/// 只换皮:取值与失败回滚口径一字不动,行本体换成 [`EmberSettingsTile`] 的
/// **开关行**(spec §8.3「开关行 on / off」):标题 17/w600 + 副标题 13
/// `text.secondary`、`Switch` 选中 `brand.default`、整行点击与点开关都只切换一次。
///
/// 读屏(page spec §6 第 3 条):整行播报「隐身浏览,已开启 / 已关闭」—— 由
/// `EmberSettingsTile` 统一给,本文件不再自己拼标签(拼了同一行会念两遍)。
class VisitsHiddenRow extends ConsumerStatefulWidget {
  /// 构造开关行。
  const VisitsHiddenRow({super.key});

  @override
  ConsumerState<VisitsHiddenRow> createState() => _VisitsHiddenRowState();
}

class _VisitsHiddenRowState extends ConsumerState<VisitsHiddenRow> {
  bool? _optimistic;
  bool _busy = false;

  Future<void> _toggle(bool next) async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _optimistic = next;
    });
    try {
      // save() 会把 PATCH 的响应写回 profileProvider,所以成功后不需要再拉一次
      await ref.read(profileProvider.notifier).save({'visits_hidden': next});
    } on ApiException catch (error) {
      if (!mounted) return;
      EmberToast.show(context, error.message);
    } finally {
      if (mounted) {
        setState(() {
          _busy = false;
          _optimistic = null;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final value = _optimistic ?? ref.watch(profileProvider).value?.visitsHidden ?? false;
    return EmberSettingsTile(
      key: const Key('settings.row.visitsHidden'),
      icon: PhosphorIconsRegular.eyeSlash,
      title: '隐身浏览',
      subtitle: '开启后,你看过的人不会看到你的访问记录',
      switchValue: value,
      // 请求在飞时置 `null` = 开关不可切换(与「心跳」期的 `_busy` 同口径)
      onChanged: _busy ? null : _toggle,
      // 本行是设置页第一组的第一行,下面还有三行,所以画分隔线
      showDivider: true,
      padding: settingsRowPadding,
    );
  }
}
