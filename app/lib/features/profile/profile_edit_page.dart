import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_exception.dart';
import '../../core/format.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/theme/app_typography.dart';
import '../../core/widgets/app_error_view.dart';
import '../../core/widgets/app_form_skeleton.dart';
import '../../core/widgets/app_section_card.dart';
import '../../core/widgets/app_sub_page_bar.dart';
import '../../core/widgets/app_text_action.dart';
import '../../core/widgets/app_toast.dart';
import 'models.dart';
import 'profile_controller.dart';
import 'widgets/photo_grid.dart';
import 'widgets/profile_form_fields.dart';
import 'widgets/tag_selector.dart';

/// 编辑资料(附录 E):二级页顶栏 + 三张分组卡(基本信息 / 关于我 / 照片)。
class ProfileEditPage extends ConsumerStatefulWidget {
  const ProfileEditPage({super.key});

  @override
  ConsumerState<ProfileEditPage> createState() => _ProfileEditPageState();
}

class _ProfileEditPageState extends ConsumerState<ProfileEditPage> {
  final _nickname = TextEditingController();
  final _city = TextEditingController();
  final _bio = TextEditingController();
  String? _gender;
  DateTime? _birthday;
  Set<int> _tagIds = {};
  bool _prefilled = false;
  bool _saving = false;

  @override
  void dispose() {
    _nickname.dispose();
    _city.dispose();
    _bio.dispose();
    super.dispose();
  }

  void _prefill(Profile profile) {
    if (_prefilled) return;
    _prefilled = true;
    _nickname.text = profile.nickname;
    _city.text = profile.city;
    _bio.text = profile.bio;
    _gender = profile.gender;
    _birthday = parseDate(profile.birthday);
    _tagIds = profile.tags.map((tag) => tag.id).toSet();
  }

  Future<void> _save() async {
    final nickname = _nickname.text.trim();
    if (nickname.isEmpty) {
      AppToast.show(context, '请填写昵称');
      return;
    }
    if (_birthday != null && !isAtLeast18(_birthday!)) {
      AppToast.show(context, '未满 18 周岁,无法使用本应用');
      return;
    }

    final patch = <String, dynamic>{
      'nickname': nickname,
      'city': _city.text.trim(),
      'bio': _bio.text.trim(),
      'tag_ids': _tagIds.toList(),
    };
    if (_gender != null) patch['gender'] = _gender;
    if (_birthday != null) patch['birthday'] = formatDate(_birthday!);

    setState(() => _saving = true);
    try {
      await ref.read(profileProvider.notifier).save(patch);
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
              title: '编辑资料',
              trailing: AppTextAction(
                key: const Key('edit.save'),
                label: _saving ? '保存中…' : '保存',
                onPressed: _saving ? null : _save,
              ),
            ),
            Expanded(
              child: profile.when(
                loading: () => const Padding(
                  padding: EdgeInsets.all(AppSpacing.pageH),
                  child: AppFormSkeleton(key: Key('edit.skeleton')),
                ),
                error: (error, _) => AppErrorView(
                  message: apiMessageOf(error),
                  retryKey: const Key('edit.retry'),
                  onRetry: () => ref.read(profileProvider.notifier).reload(),
                ),
                data: (data) {
                  _prefill(data);
                  return ListView(
                    padding: const EdgeInsets.fromLTRB(AppSpacing.pageH,
                        AppSpacing.md, AppSpacing.pageH, AppSpacing.xxl),
                    children: [
                      AppSectionCard(
                        title: '基本信息',
                        children: [
                          NicknameField(controller: _nickname),
                          GenderSelector(
                            value: _gender,
                            onChanged: (value) =>
                                setState(() => _gender = value),
                          ),
                          BirthdayField(
                            value: _birthday,
                            onChanged: (value) =>
                                setState(() => _birthday = value),
                          ),
                          CityField(controller: _city),
                        ],
                      ),
                      const SizedBox(height: AppSpacing.cardGap),
                      AppSectionCard(
                        title: '关于我',
                        children: [
                          BioField(controller: _bio),
                          Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text('标签',
                                  style: AppText.caption
                                      .copyWith(color: AppColors.text2)),
                              const SizedBox(height: AppSpacing.sm),
                              TagSelector(
                                selectedIds: _tagIds,
                                onChanged: (ids) =>
                                    setState(() => _tagIds = ids),
                              ),
                            ],
                          ),
                        ],
                      ),
                      const SizedBox(height: AppSpacing.cardGap),
                      const AppSectionCard(
                        title: '照片',
                        children: [PhotoGrid()],
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
