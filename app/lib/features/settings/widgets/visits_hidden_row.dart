import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api_exception.dart';
import '../../../core/widgets/app_list_row.dart';
import '../../../core/widgets/app_toast.dart';
import '../../profile/profile_controller.dart';

/// 「隐身浏览」开关行:乐观更新,失败回滚并提示。
class VisitsHiddenRow extends ConsumerStatefulWidget {
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
      AppToast.show(context, error.message);
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
    return AppListRow(
      key: const Key('settings.row.visitsHidden'),
      icon: Icons.visibility_off_rounded,
      title: '隐身浏览',
      subtitle: '开启后,你看过的人不会看到你的访问记录',
      onTap: () => _toggle(!value),
      trailing: Switch.adaptive(
        value: value,
        onChanged: _busy ? null : _toggle,
      ),
    );
  }
}
