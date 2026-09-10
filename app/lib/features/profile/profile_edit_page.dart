import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_exception.dart';
import '../../core/format.dart';
import 'models.dart';
import 'profile_controller.dart';
import 'widgets/photo_grid.dart';
import 'widgets/profile_form_fields.dart';
import 'widgets/tag_selector.dart';

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

  void _show(String message) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _save() async {
    final nickname = _nickname.text.trim();
    if (nickname.isEmpty) {
      _show('请填写昵称');
      return;
    }
    if (_birthday != null && !isAtLeast18(_birthday!)) {
      _show('未满 18 周岁,无法使用本应用');
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
      _show('已保存');
      Navigator.of(context).pop();
    } on ApiException catch (error) {
      if (mounted) _show(error.message);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final profile = ref.watch(profileProvider);
    return Scaffold(
      appBar: AppBar(
        title: const Text('编辑资料'),
        actions: [
          TextButton(
            key: const Key('edit.save'),
            onPressed: _saving ? null : _save,
            child: Text(_saving ? '保存中…' : '保存'),
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
          return ListView(
            padding: const EdgeInsets.all(16),
            children: [
              NicknameField(controller: _nickname),
              const SizedBox(height: 16),
              GenderSelector(
                  value: _gender, onChanged: (value) => setState(() => _gender = value)),
              const SizedBox(height: 16),
              BirthdayField(
                  value: _birthday, onChanged: (value) => setState(() => _birthday = value)),
              const SizedBox(height: 16),
              CityField(controller: _city),
              const SizedBox(height: 16),
              BioField(controller: _bio),
              const SizedBox(height: 16),
              Text('标签', style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: 8),
              TagSelector(
                  selectedIds: _tagIds, onChanged: (ids) => setState(() => _tagIds = ids)),
              const SizedBox(height: 24),
              Text('照片', style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: 8),
              const PhotoGrid(),
            ],
          );
        },
      ),
    );
  }
}
