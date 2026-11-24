import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_exception.dart';
import '../../core/theme/app_typography.dart';
import '../../core/theme/ember_theme_context.dart';
import '../../core/theme/tokens.g.dart' as tokens;
import '../../core/ui/ember_ui.dart';
import 'settings_repository.dart';

/// 意见反馈页(E-5.6b 迁移到 Ember):类型 + 内容 + 可选联系方式。
///
/// 只换皮:四类选项的取值(`feature` / `bug` / `account` / `other`)、「至少 10 字才能
/// 提交」的门槛、提交成功回退 + Toast 全部不变。形态按 page spec §3 / §4:
/// - 类型选择用 [`EmberChip`](§8.3「Chip selected = `brand.default` + `brand.on`」),
///   选中态除了颜色还加粗一档(§8.4「颜色不是唯一线索」);
/// - 两个输入框换 [`EmberField`](`surface.card` + 1px `border.divider` + 高 52);
/// - 提交键换 [`EmberButton`](52 高、`radius.pill`、`emberGlow`),请求在飞时走
///   `loading`(保持底与字 + 尾随转圈,禁点击)。
class FeedbackPage extends ConsumerStatefulWidget {
  /// 构造意见反馈页。
  const FeedbackPage({super.key});

  @override
  ConsumerState<FeedbackPage> createState() => _FeedbackPageState();
}

class _FeedbackPageState extends ConsumerState<FeedbackPage> {
  /// 反馈类型(取值 → 展示名);取值与后端 `POST /feedback` 的枚举一一对应。
  static const _types = <(String, String)>[
    ('feature', '功能建议'),
    ('bug', '问题反馈'),
    ('account', '账号问题'),
    ('other', '其他'),
  ];

  final _content = TextEditingController();
  final _contact = TextEditingController();
  var _type = 'feature';
  var _submitting = false;

  bool get _canSubmit => !_submitting && _content.text.trim().length >= 10;

  @override
  void dispose() {
    _content.dispose();
    _contact.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    setState(() => _submitting = true);
    try {
      await ref.read(settingsRepositoryProvider).submitFeedback(
            type: _type,
            content: _content.text.trim(),
            contact: _contact.text.trim(),
          );
      if (!mounted) return;
      EmberToast.show(context, '反馈已提交,谢谢你');
      await Navigator.of(context).maybePop();
    } on ApiException catch (error) {
      if (mounted) EmberToast.show(context, error.message);
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    return EmberPageScaffold(
      title: '意见反馈',
      backKey: const Key('feedback.back'),
      body: ListView(
        padding: EdgeInsets.only(
          top: tokens.space16,
          bottom: tokens.space40 + MediaQuery.viewPaddingOf(context).bottom,
        ),
        children: [
          Text(
            '反馈类型',
            style: AppText.caption.copyWith(color: colors.textSecondary),
          ),
          SizedBox(height: tokens.space8),
          Wrap(
            key: const Key('feedback.type'),
            spacing: tokens.space8,
            runSpacing: tokens.space8,
            children: [
              for (final (value, label) in _types)
                EmberChip(
                  key: Key('feedback.type.$value'),
                  label: label,
                  selected: _type == value,
                  onTap: () => setState(() => _type = value),
                ),
            ],
          ),
          SizedBox(height: tokens.space24),
          EmberField(
            key: const Key('feedback.content'),
            controller: _content,
            label: '反馈内容',
            placeholder: '说说遇到了什么,或希望我们做什么(至少 10 字)',
            maxLines: 6,
            maxLength: 500,
            onChanged: (_) => setState(() {}),
          ),
          SizedBox(height: tokens.space16),
          EmberField(
            key: const Key('feedback.contact'),
            controller: _contact,
            label: '联系方式(选填)',
            placeholder: '手机号 / 邮箱 / 微信,方便我们回复你',
            maxLength: 64,
          ),
          SizedBox(height: tokens.space24),
          EmberButton(
            key: const Key('feedback.submit'),
            label: '提交反馈',
            loading: _submitting,
            expand: true,
            onPressed: _canSubmit ? _submit : null,
          ),
        ],
      ),
    );
  }
}
