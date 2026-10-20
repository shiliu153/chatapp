import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_exception.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/theme/app_typography.dart';
import '../../core/widgets/app_button.dart';
import '../../core/widgets/app_option_group.dart';
import '../../core/widgets/app_sub_page_bar.dart';
import '../../core/widgets/app_text_field.dart';
import '../../core/widgets/app_toast.dart';
import 'settings_repository.dart';

/// 意见反馈页:类型 + 内容 + 可选联系方式。
class FeedbackPage extends ConsumerStatefulWidget {
  const FeedbackPage({super.key});

  @override
  ConsumerState<FeedbackPage> createState() => _FeedbackPageState();
}

class _FeedbackPageState extends ConsumerState<FeedbackPage> {
  static const _types = [
    AppOption(value: 'feature', label: '功能建议'),
    AppOption(value: 'bug', label: '问题反馈'),
    AppOption(value: 'account', label: '账号问题'),
    AppOption(value: 'other', label: '其他'),
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
      AppToast.show(context, '反馈已提交,谢谢你');
      await Navigator.of(context).maybePop();
    } on ApiException catch (error) {
      if (mounted) AppToast.show(context, error.message);
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        backgroundColor: AppColors.bgPage,
        body: SafeArea(
          bottom: false,
          child: Column(
            children: [
              const AppSubPageBar(title: '意见反馈'),
              Expanded(
                child: ListView(
                  padding: const EdgeInsets.fromLTRB(AppSpacing.pageH,
                      AppSpacing.md, AppSpacing.pageH, AppSpacing.xxl),
                  children: [
                    Text('反馈类型',
                        style: AppText.caption.copyWith(color: AppColors.text2)),
                    const SizedBox(height: AppSpacing.xs),
                    AppOptionGroup<String>(
                      key: const Key('feedback.type'),
                      options: _types,
                      value: _type,
                      onChanged: (value) => setState(() => _type = value),
                    ),
                    const SizedBox(height: AppSpacing.lg),
                    AppTextField(
                      key: const Key('feedback.content'),
                      controller: _content,
                      label: '反馈内容',
                      hint: '说说遇到了什么,或希望我们做什么(至少 10 字)',
                      maxLines: 6,
                      minLines: 6,
                      maxLength: 500,
                      counterKey: const Key('feedback.content.counter'),
                      onChanged: (_) => setState(() {}),
                    ),
                    const SizedBox(height: AppSpacing.lg),
                    AppTextField(
                      key: const Key('feedback.contact'),
                      controller: _contact,
                      label: '联系方式(选填)',
                      hint: '手机号 / 邮箱 / 微信,方便我们回复你',
                      maxLength: 64,
                    ),
                    const SizedBox(height: AppSpacing.xl),
                    AppButton(
                      key: const Key('feedback.submit'),
                      label: _submitting ? '提交中' : '提交反馈',
                      onPressed: _canSubmit ? _submit : null,
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      );
}
