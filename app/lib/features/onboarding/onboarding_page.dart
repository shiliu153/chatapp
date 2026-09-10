import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_exception.dart';
import '../../core/format.dart';
import '../profile/models.dart';
import '../profile/profile_controller.dart';
import '../profile/widgets/photo_grid.dart';
import '../profile/widgets/profile_form_fields.dart';
import '../profile/widgets/tag_selector.dart';

String? validateBasicStep(
    {required String nickname, required String? gender, required DateTime? birthday}) {
  if (nickname.isEmpty) return '请填写昵称';
  if (gender == null) return '请选择性别';
  if (birthday == null) return '请选择生日';
  if (!isAtLeast18(birthday)) return '未满 18 周岁,无法使用本应用';
  return null;
}

String? validateAboutStep({required String city, required String bio}) {
  if (city.isEmpty) return '请填写城市';
  if (bio.isEmpty) return '请填写简介';
  return null;
}

class OnboardingPage extends ConsumerStatefulWidget {
  const OnboardingPage({super.key});

  @override
  ConsumerState<OnboardingPage> createState() => _OnboardingPageState();
}

class _OnboardingPageState extends ConsumerState<OnboardingPage> {
  final _pageController = PageController();
  final _nickname = TextEditingController();
  final _city = TextEditingController();
  final _bio = TextEditingController();
  String? _gender;
  DateTime? _birthday;
  Set<int> _tagIds = {};
  bool _prefilled = false;
  bool _busy = false;
  int _step = 0;

  @override
  void dispose() {
    _pageController.dispose();
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

  void _show(String message) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  void _goToStep(int step) {
    setState(() => _step = step);
    _pageController.animateToPage(step,
        duration: const Duration(milliseconds: 250), curve: Curves.easeOut);
  }

  Future<void> _next() async {
    Map<String, dynamic>? patch;
    if (_step == 0) {
      final error = validateBasicStep(
          nickname: _nickname.text.trim(), gender: _gender, birthday: _birthday);
      if (error != null) {
        _show(error);
        return;
      }
      patch = {
        'nickname': _nickname.text.trim(),
        'gender': _gender,
        'birthday': formatDate(_birthday!),
      };
    } else if (_step == 1) {
      final error = validateAboutStep(city: _city.text.trim(), bio: _bio.text.trim());
      if (error != null) {
        _show(error);
        return;
      }
      patch = {
        'city': _city.text.trim(),
        'bio': _bio.text.trim(),
        'tag_ids': _tagIds.toList(),
      };
    } else {
      await _finish();
      return;
    }

    setState(() => _busy = true);
    try {
      await ref.read(profileProvider.notifier).save(patch);
      if (!mounted) return;
      _goToStep(_step + 1);
    } on ApiException catch (error) {
      if (mounted) _show(error.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _finish() async {
    setState(() => _busy = true);
    try {
      await ref.read(profileProvider.notifier).reload();
      if (!mounted) return;
      final profile = ref.read(profileProvider).value;
      if (profile == null || profile.photos.where((photo) => photo.isApproved).isEmpty) {
        _show('至少上传一张照片');
        return;
      }
      context.go('/home');
    } on ApiException catch (error) {
      if (mounted) _show(error.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final profile = ref.watch(profileProvider);
    return Scaffold(
      appBar: AppBar(
        title: const Text('完善资料'),
        actions: [
          TextButton(
            onPressed: () => context.go('/home'),
            child: const Text('稍后再说'),
          ),
        ],
      ),
      body: profile.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (error, _) => Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text('$error'),
              FilledButton(
                onPressed: () => ref.read(profileProvider.notifier).reload(),
                child: const Text('重试'),
              ),
            ],
          ),
        ),
        data: (data) {
          _prefill(data);
          return Column(
            children: [
              Padding(
                padding: const EdgeInsets.all(16),
                child: LinearProgressIndicator(value: (_step + 1) / 3),
              ),
              Text('第 ${_step + 1} 步 / 共 3 步'),
              Expanded(
                child: PageView(
                  controller: _pageController,
                  physics: const NeverScrollableScrollPhysics(),
                  children: [
                    _StepBasic(
                      nickname: _nickname,
                      gender: _gender,
                      birthday: _birthday,
                      onGenderChanged: (value) => setState(() => _gender = value),
                      onBirthdayChanged: (value) => setState(() => _birthday = value),
                    ),
                    _StepAbout(
                      city: _city,
                      bio: _bio,
                      tagIds: _tagIds,
                      onTagsChanged: (ids) => setState(() => _tagIds = ids),
                    ),
                    const _StepPhotos(),
                  ],
                ),
              ),
              Padding(
                padding: const EdgeInsets.all(16),
                child: Row(
                  children: [
                    if (_step > 0)
                      OutlinedButton(
                        onPressed: _busy ? null : () => _goToStep(_step - 1),
                        child: const Text('上一步'),
                      ),
                    const Spacer(),
                    FilledButton(
                      key: const Key('onboarding.next'),
                      onPressed: _busy ? null : _next,
                      child: Text(_step == 2 ? '完成' : '下一步'),
                    ),
                  ],
                ),
              ),
            ],
          );
        },
      ),
    );
  }
}

class _StepBasic extends StatelessWidget {
  const _StepBasic({
    required this.nickname,
    required this.gender,
    required this.birthday,
    required this.onGenderChanged,
    required this.onBirthdayChanged,
  });

  final TextEditingController nickname;
  final String? gender;
  final DateTime? birthday;
  final ValueChanged<String> onGenderChanged;
  final ValueChanged<DateTime> onBirthdayChanged;

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        NicknameField(controller: nickname),
        const SizedBox(height: 16),
        GenderSelector(value: gender, onChanged: onGenderChanged),
        const SizedBox(height: 16),
        BirthdayField(value: birthday, onChanged: onBirthdayChanged),
      ],
    );
  }
}

class _StepAbout extends StatelessWidget {
  const _StepAbout({
    required this.city,
    required this.bio,
    required this.tagIds,
    required this.onTagsChanged,
  });

  final TextEditingController city;
  final TextEditingController bio;
  final Set<int> tagIds;
  final ValueChanged<Set<int>> onTagsChanged;

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        CityField(controller: city),
        const SizedBox(height: 16),
        BioField(controller: bio),
        const SizedBox(height: 16),
        Text('标签(可多选)', style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 8),
        TagSelector(selectedIds: tagIds, onChanged: onTagsChanged),
      ],
    );
  }
}

class _StepPhotos extends StatelessWidget {
  const _StepPhotos();

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: const [
        Text('上传至少 1 张照片(最多 6 张),让别人认识你'),
        SizedBox(height: 16),
        PhotoGrid(),
      ],
    );
  }
}
