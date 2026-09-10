import 'package:flutter/material.dart';

import '../../../core/format.dart';

class NicknameField extends StatelessWidget {
  const NicknameField({super.key, required this.controller, this.errorText});

  final TextEditingController controller;
  final String? errorText;

  @override
  Widget build(BuildContext context) {
    return TextField(
      key: const Key('edit.nickname'),
      controller: controller,
      maxLength: 20,
      decoration: InputDecoration(
        labelText: '昵称',
        counterText: '',
        border: const OutlineInputBorder(),
        errorText: errorText,
      ),
    );
  }
}

class GenderSelector extends StatelessWidget {
  const GenderSelector({super.key, required this.value, required this.onChanged});

  final String? value;
  final ValueChanged<String> onChanged;

  @override
  Widget build(BuildContext context) {
    return SegmentedButton<String>(
      segments: const [
        ButtonSegment(value: 'male', label: Text('男'), icon: Icon(Icons.male)),
        ButtonSegment(value: 'female', label: Text('女'), icon: Icon(Icons.female)),
      ],
      selected: value == null ? const <String>{} : {value!},
      emptySelectionAllowed: true,
      onSelectionChanged: (selection) {
        if (selection.isNotEmpty) onChanged(selection.first);
      },
    );
  }
}

class BirthdayField extends StatelessWidget {
  const BirthdayField({super.key, required this.value, required this.onChanged});

  final DateTime? value;
  final ValueChanged<DateTime> onChanged;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      key: const Key('edit.birthday'),
      onTap: () async {
        final now = DateTime.now();
        final picked = await showDatePicker(
          context: context,
          initialDate: value ?? DateTime(now.year - 25, now.month, now.day),
          firstDate: DateTime(now.year - 100),
          lastDate: DateTime(now.year - 18, now.month, now.day), // 未满 18 岁选不出来
          helpText: '选择生日',
        );
        if (picked != null) onChanged(picked);
      },
      child: InputDecorator(
        decoration: const InputDecoration(labelText: '生日', border: OutlineInputBorder()),
        child: Text(value == null ? '请选择' : formatDate(value!)),
      ),
    );
  }
}

class CityField extends StatelessWidget {
  const CityField({super.key, required this.controller});

  final TextEditingController controller;

  @override
  Widget build(BuildContext context) {
    return TextField(
      key: const Key('edit.city'),
      controller: controller,
      maxLength: 50,
      decoration: const InputDecoration(
        labelText: '城市',
        counterText: '',
        border: OutlineInputBorder(),
      ),
    );
  }
}

class BioField extends StatelessWidget {
  const BioField({super.key, required this.controller});

  final TextEditingController controller;

  @override
  Widget build(BuildContext context) {
    return TextField(
      key: const Key('edit.bio'),
      controller: controller,
      maxLength: 200,
      maxLines: 3,
      decoration: const InputDecoration(
        labelText: '简介',
        border: OutlineInputBorder(),
        alignLabelWithHint: true,
      ),
    );
  }
}
