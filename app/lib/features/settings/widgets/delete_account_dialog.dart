import 'package:flutter/material.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/theme/app_typography.dart';
import '../../../core/widgets/app_button.dart';
import '../../../core/widgets/app_dialog.dart';
import '../../../core/widgets/app_text_field.dart';

/// 注销账号的第二步确认:必须输入完整手机号才能提交(不可恢复操作)。
///
/// 返回用户输入的手机号;取消 / 点外部返回 null。请求由调用方发。
Future<String?> showDeleteAccountDialog(BuildContext context) =>
    showDialog<String>(context: context, builder: (_) => const _DeleteAccountDialog());

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
  var _valid = false;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AppDialog(
        title: '注销账号',
        message: '以下内容将被永久删除,且无法恢复:',
        content: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            for (final item in _consequences)
              Padding(
                padding: const EdgeInsets.only(bottom: AppSpacing.xs),
                child: Text('· $item',
                    style: AppText.caption.copyWith(color: AppColors.text2)),
              ),
            const SizedBox(height: AppSpacing.md),
            AppTextField(
              key: const Key('deleteAccount.phone'),
              controller: _controller,
              label: '请输入当前账号的手机号以确认',
              hint: '11 位手机号',
              keyboardType: TextInputType.phone,
              onChanged: (value) =>
                  setState(() => _valid = _phonePattern.hasMatch(value.trim())),
            ),
          ],
        ),
        actions: [
          AppButton(
            key: const Key('deleteAccount.cancel'),
            label: '取消',
            variant: AppButtonVariant.secondary,
            onPressed: () => Navigator.pop(context),
          ),
          AppButton(
            key: const Key('deleteAccount.confirm'),
            label: '确认注销',
            variant: AppButtonVariant.dangerFilled,
            onPressed: _valid ? () => Navigator.pop(context, _controller.text.trim()) : null,
          ),
        ],
      );
}
