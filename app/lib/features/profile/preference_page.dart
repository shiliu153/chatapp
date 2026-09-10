import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_exception.dart';
import 'models.dart';
import 'profile_controller.dart';
import 'profile_repository.dart';

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

  void _show(String message) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
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
        title: const Text('想找的人'),
        actions: [
          TextButton(
            key: const Key('preference.save'),
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
          _prefill(data.preference);
          return ListView(
            padding: const EdgeInsets.all(16),
            children: [
              Text('我想找', style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: 8),
              SegmentedButton<String>(
                segments: const [
                  ButtonSegment(value: 'any', label: Text('不限')),
                  ButtonSegment(value: 'male', label: Text('男')),
                  ButtonSegment(value: 'female', label: Text('女')),
                ],
                selected: {_targetGender ?? 'any'},
                onSelectionChanged: (selection) => setState(() {
                  final value = selection.first;
                  _targetGender = value == 'any' ? null : value;
                }),
              ),
              const SizedBox(height: 24),
              Text('年龄 ${_ageRange.start.round()} – ${_ageRange.end.round()} 岁',
                  style: Theme.of(context).textTheme.titleMedium),
              RangeSlider(
                values: _ageRange,
                min: 18,
                max: 99,
                divisions: 81,
                labels: RangeLabels(_ageRange.start.round().toString(),
                    _ageRange.end.round().toString()),
                onChanged: (values) => setState(() => _ageRange = values),
              ),
              const SizedBox(height: 16),
              TextField(
                key: const Key('preference.city'),
                controller: _city,
                maxLength: 50,
                decoration: const InputDecoration(
                  labelText: '城市(留空 = 不限)',
                  counterText: '',
                  border: OutlineInputBorder(),
                ),
              ),
            ],
          );
        },
      ),
    );
  }
}
