import 'package:flutter/material.dart';
import 'package:phosphor_glyphs/phosphor_glyphs.dart';

import '../../../core/theme/app_typography.dart';
import '../../../core/theme/ember_theme_context.dart';
import '../../../core/theme/tokens.g.dart' as tokens;
import '../../../core/ui/ember_ui.dart';

/// 注销账号的第二步确认(E-5.6b 迁移到 Ember):必须输入完整手机号才能提交。
///
/// 返回用户输入的手机号;取消 / 点外部返回 `null`。请求由调用方发。
///
/// **只换皮**:二次确认的次数、必须输入手机号这条安全口径、后果清单都与迁移前
/// 一致(spec §7 第 5 条「不改输入文字确认」,加强确认属安全口径变更,另开单)。
/// 换的是外壳 —— 自绘 `AppDialog` → [`EmberDialog`](图标 + 标题 + 说明 + 危险确认键),
/// 输入框 → [`EmberField`]。
///
/// **与迁移前的一处交互差异(已写进 PR 正文)**:`EmberDialog` 目前没有「禁用确认键」
/// 的能力(两个按钮的 `onPressed` 由组件内部拼),所以确认键**始终可点**,点下去
/// 才校验:不合法时在输入框下方给 `status.danger` 说明(spec §5「表单校验失败:
/// 字段下方 danger 文字,不弹全局 Toast」),合法才关闭并返回手机号。能力缺口已在
/// PR 正文与回报里列出,没有改公共组件。
Future<String?> showDeleteAccountDialog(BuildContext context) => showDialog<String>(
      context: context,
      // 遮罩用 overlay.scrim(与 `showEmberDialog` / Sheet 同一档)
      barrierColor: context.ember.overlayScrim,
      builder: (context) => const _DeleteAccountDialog(),
    );

class _DeleteAccountDialog extends StatefulWidget {
  const _DeleteAccountDialog();

  @override
  State<_DeleteAccountDialog> createState() => _DeleteAccountDialogState();
}

class _DeleteAccountDialogState extends State<_DeleteAccountDialog> {
  static final _phonePattern = RegExp(r'^\d{11}$');

  /// 注销后会被永久删除的内容(与隐私政策 §四、docs/api/users.md §2.10 口径一致)。
  static const _consequences = [
    '个人资料、标签与全部照片',
    '配对关系与聊天关系',
    '你发布的动态与评论',
    '拉黑与举报记录',
    '账号本身(手机号将被释放)',
  ];

  final _controller = TextEditingController();
  String? _error;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  /// 确认键:合法才关闭并回传手机号,不合法就地给字段级说明。
  void _confirm() {
    final phone = _controller.text.trim();
    if (!_phonePattern.hasMatch(phone)) {
      setState(() => _error = '请输入当前账号的 11 位手机号');
      return;
    }
    Navigator.pop(context, phone);
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    return EmberDialog(
      icon: PhosphorIconsRegular.trash,
      title: '注销账号',
      message: '以下内容将被永久删除,且无法恢复:',
      content: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (final item in _consequences)
            Padding(
              padding: EdgeInsets.only(bottom: tokens.space4),
              child: Text(
                '· $item',
                style: AppText.caption.copyWith(color: colors.textSecondary),
              ),
            ),
          SizedBox(height: tokens.space16),
          EmberField(
            key: const Key('deleteAccount.phone'),
            controller: _controller,
            label: '请输入当前账号的手机号以确认',
            placeholder: '11 位手机号',
            keyboardType: TextInputType.phone,
            errorText: _error,
            fieldKey: const Key('deleteAccount.phone.input'),
            // 用户一改动就撤掉上一次的说明(否则红字会挂在那里像新错误)
            onChanged: (_) {
              if (_error != null) setState(() => _error = null);
            },
          ),
        ],
      ),
      // §9.3「明确动词」:读屏念到的是动作本身,不是「确定」
      confirmLabel: '确认注销',
      cancelLabel: '取消',
      danger: true,
      confirmKey: const Key('deleteAccount.confirm'),
      cancelKey: const Key('deleteAccount.cancel'),
      onConfirm: _confirm,
      onCancel: () => Navigator.pop(context),
    );
  }
}
