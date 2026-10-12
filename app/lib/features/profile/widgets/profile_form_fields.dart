import 'package:flutter/material.dart';

import '../../../core/format.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/theme/app_typography.dart';
import '../../../core/widgets/app_option_group.dart';
import '../../../core/widgets/app_picker_field.dart';
import '../../../core/widgets/app_text_field.dart';

/// 资料表单字段(批次⑥ 表单控件规范):全部是 core 组件的薄包装,
/// 对外构造签名与批次① 一致,编辑资料页与引导页共用。

class NicknameField extends StatelessWidget {
  const NicknameField({super.key, required this.controller, this.errorText});

  final TextEditingController controller;
  final String? errorText;

  @override
  Widget build(BuildContext context) => AppTextField(
        key: const Key('edit.nickname'),
        controller: controller,
        label: '昵称',
        maxLength: 20,
        errorText: errorText,
      );
}

class GenderSelector extends StatelessWidget {
  const GenderSelector({super.key, required this.value, required this.onChanged});

  final String? value;
  final ValueChanged<String> onChanged;

  @override
  Widget build(BuildContext context) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('性别', style: AppText.caption.copyWith(color: AppColors.text2)),
          const SizedBox(height: AppSpacing.xs),
          AppOptionGroup<String>(
            options: const [
              AppOption(value: 'male', label: '男'),
              AppOption(value: 'female', label: '女'),
            ],
            value: value,
            onChanged: onChanged,
          ),
        ],
      );
}

class BirthdayField extends StatelessWidget {
  const BirthdayField({super.key, required this.value, required this.onChanged});

  final DateTime? value;
  final ValueChanged<DateTime> onChanged;

  @override
  Widget build(BuildContext context) => AppPickerField(
        key: const Key('edit.birthday'),
        label: '生日',
        value: value == null ? null : formatDate(value!),
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
      );
}

class CityField extends StatelessWidget {
  const CityField({super.key, required this.controller});

  final TextEditingController controller;

  @override
  Widget build(BuildContext context) => AppTextField(
        key: const Key('edit.city'),
        controller: controller,
        label: '城市',
        maxLength: 50,
      );
}

class BioField extends StatelessWidget {
  const BioField({super.key, required this.controller});

  final TextEditingController controller;

  @override
  Widget build(BuildContext context) => AppTextField(
        key: const Key('edit.bio'),
        controller: controller,
        label: '简介',
        maxLines: 3,
        maxLength: 200,
      );
}
