import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_exception.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/widgets/app_error_view.dart';
import '../../core/widgets/app_form_skeleton.dart';
import '../../core/widgets/app_option_group.dart';
import '../../core/widgets/app_range_field.dart';
import '../../core/widgets/app_section_card.dart';
import '../../core/widgets/app_sub_page_bar.dart';
import '../../core/widgets/app_text_action.dart';
import '../../core/widgets/app_text_field.dart';
import '../../core/widgets/app_toast.dart';
import 'models.dart';
import 'profile_controller.dart';
import 'profile_repository.dart';

/// 想找的人(附录 E):目标性别 / 年龄区间 / 城市。
class PreferencePage extends ConsumerStatefulWidget {
  const PreferencePage({super.key});

  @override
  ConsumerState<PreferencePage> createState() => _PreferencePageState();
}

class _PreferencePageState extends ConsumerState<PreferencePage> {
  final _city = TextEditingController();
  String? _targetGender;
  RangeValues _ageRange = const RangeValues(18, 99);
  bool _prefilled = false;
  bool _saving = false;

  @override
  void dispose() {
    _city.dispose();
    super.dispose();
  }

  void _prefill(Preference preference) {
    if (_prefilled) return;
    _prefilled = true;
    _targetGender = preference.targetGender;
    _ageRange = RangeValues(
      preference.ageMin.toDouble(),
      preference.ageMax.toDouble().clamp(18, 99),
    );
    _city.text = preference.city;
  }

  Future<void> _save() async {
    setState(() => _saving = true);
    try {
      await ref.read(profileRepositoryProvider).updatePreference({
        'target_gender': _targetGender,
        'age_min': _ageRange.start.round(),
        'age_max': _ageRange.end.round(),
        'city': _city.text.trim(),
      });
      if (!mounted) return;
      AppToast.show(context, '已保存');
      Navigator.of(context).pop();
    } on ApiException catch (error) {
      if (mounted) AppToast.show(context, error.message);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final profile = ref.watch(profileProvider);
    return Scaffold(
      backgroundColor: AppColors.bgPage,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            AppSubPageBar(
              title: '想找的人',
              trailing: AppTextAction(
                key: const Key('preference.save'),
                label: _saving ? '保存中…' : '保存',
                onPressed: _saving ? null : _save,
              ),
            ),
            Expanded(
              child: profile.when(
                loading: () => const Padding(
                  padding: EdgeInsets.all(AppSpacing.pageH),
                  child: AppFormSkeleton(key: Key('preference.skeleton')),
                ),
                error: (error, _) => AppErrorView(
                  message: apiMessageOf(error),
                  retryKey: const Key('preference.retry'),
                  onRetry: () => ref.read(profileProvider.notifier).reload(),
                ),
                data: (data) {
                  _prefill(data.preference);
                  return ListView(
                    padding: const EdgeInsets.fromLTRB(AppSpacing.pageH,
                        AppSpacing.md, AppSpacing.pageH, AppSpacing.xxl),
                    children: [
                      AppSectionCard(
                        title: '我想找',
                        children: [
                          AppOptionGroup<String>(
                            options: const [
                              AppOption(value: 'any', label: '不限'),
                              AppOption(value: 'male', label: '男'),
                              AppOption(value: 'female', label: '女'),
                            ],
                            value: _targetGender ?? 'any',
                            onChanged: (value) => setState(() =>
                                _targetGender = value == 'any' ? null : value),
                          ),
                        ],
                      ),
                      const SizedBox(height: AppSpacing.cardGap),
                      AppSectionCard(
                        children: [
                          AppRangeField(
                            title:
                                '年龄 ${_ageRange.start.round()} – ${_ageRange.end.round()} 岁',
                            values: _ageRange,
                            min: 18,
                            max: 99,
                            divisions: 81,
                            onChanged: (values) =>
                                setState(() => _ageRange = values),
                          ),
                        ],
                      ),
                      const SizedBox(height: AppSpacing.cardGap),
                      AppSectionCard(
                        children: [
                          AppTextField(
                            key: const Key('preference.city'),
                            controller: _city,
                            label: '城市(留空 = 不限)',
                            maxLength: 50,
                          ),
                        ],
                      ),
                    ],
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }
}
