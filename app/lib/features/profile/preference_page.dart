import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_exception.dart';
import '../../core/theme/app_typography.dart';
import '../../core/theme/ember_theme_context.dart';
import '../../core/theme/tokens.g.dart' as tokens;
import '../../core/ui/ember_ui.dart';
import 'models.dart';
import 'profile_controller.dart';
import 'profile_repository.dart';
import 'widgets/profile_form_fields.dart';
import 'widgets/profile_illustration.dart';

/// 想找的人(附录 E / E-5.6c):§9.4 二级页 shell + 目标性别 / 年龄区间 / 城市。
///
/// **只换皮**:三个字段、PATCH 的四个键(`target_gender` / `age_min` / `age_max` /
/// `city`)与「`不限` = `null`」的映射与改版前逐字一致;提交失败给表单底部的
/// `status.danger` 提示条(§5),不再弹全局 Toast。
class PreferencePage extends ConsumerStatefulWidget {
  /// 构造偏好页。
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
  String? _submitError;

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
    setState(() {
      _submitError = null;
      _saving = true;
    });
    try {
      await ref.read(profileRepositoryProvider).updatePreference({
        'target_gender': _targetGender,
        'age_min': _ageRange.start.round(),
        'age_max': _ageRange.end.round(),
        'city': _city.text.trim(),
      });
      if (!mounted) return;
      EmberToast.show(context, '已保存');
      Navigator.of(context).pop();
    } on ApiException catch (error) {
      if (mounted) setState(() => _submitError = error.message);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final profile = ref.watch(profileProvider);
    return EmberPageScaffold(
      title: '想找的人',
      backKey: const Key('preference.back'),
      bottomBar: profile.maybeWhen(
        orElse: () => null,
        data: (_) => Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (_submitError != null) ...[
              FormErrorBanner(message: _submitError!),
              SizedBox(height: tokens.space12),
            ],
            EmberButton(
              key: const Key('preference.save'),
              label: '保存',
              expand: true,
              loading: _saving,
              onPressed: _save,
            ),
          ],
        ),
      ),
      body: profile.when(
        // 骨架放进可滚动列表(与编辑资料页同一口径:窄屏上骨架比可视区高)。
        loading: () => ListView(
          key: const Key('preference.skeleton'),
          padding: EdgeInsets.only(top: tokens.space16, bottom: tokens.space40),
          children: const [_PreferenceSkeleton()],
        ),
        error: (error, _) => Center(
          child: Padding(
            padding: EdgeInsets.all(tokens.space20),
            child: EmberEmpty(
              illustration:
                  const ProfileIllustration(ProfileIllustrationKind.loadFailed),
              title: '没能加载出来',
              description: apiMessageOf(error),
              actionLabel: '重试',
              actionKey: const Key('preference.retry'),
              onAction: () => ref.read(profileProvider.notifier).reload(),
            ),
          ),
        ),
        data: (data) {
          _prefill(data.preference);
          return ListView(
            padding: EdgeInsets.only(top: tokens.space16, bottom: tokens.space40),
            children: [
              _Section(
                title: '我想找',
                children: [
                  _LabeledGroup(
                    label: '性别',
                    child: Wrap(
                      spacing: tokens.space8,
                      children: [
                        for (final option in _genderOptions)
                          EmberChip(
                            label: option.label,
                            selected: (_targetGender ?? 'any') == option.value,
                            onTap: () => setState(() => _targetGender =
                                option.value == 'any' ? null : option.value),
                          ),
                      ],
                    ),
                  ),
                ],
              ),
              SizedBox(height: tokens.space24),
              _Section(
                title: '年龄',
                children: [
                  _AgeRangeField(
                    values: _ageRange,
                    onChanged: (values) => setState(() => _ageRange = values),
                  ),
                ],
              ),
              SizedBox(height: tokens.space24),
              _Section(
                title: '城市',
                children: [
                  EmberField(
                    fieldKey: const Key('preference.city'),
                    controller: _city,
                    placeholder: '留空 = 不限',
                    label: '城市',
                    maxLength: 50,
                  ),
                ],
              ),
            ],
          );
        },
      ),
    );
  }

  /// 目标性别三档;`any` 映射成 `null` 发出去(与改版前一致)。
  static const _genderOptions = <({String value, String label})>[
    (value: 'any', label: '不限'),
    (value: 'male', label: '男'),
    (value: 'female', label: '女'),
  ];
}

/// 一个「标签 + 控件」的表单行(分组卡里的一行)。
class _LabeledGroup extends StatelessWidget {
  const _LabeledGroup({required this.label, required this.child});

  final String label;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        // 组名留在语义树里当组头(chip 各自读「女,已选中」)。
        Text(
          label,
          style: TextStyle(
            fontSize: tokens.fontSizeCaption,
            height: tokens.fontLineHeightCaption,
            color: context.ember.textSecondary,
          ),
        ),
        SizedBox(height: tokens.space8),
        child,
      ],
    );
  }
}

/// 年龄区间:双滑块,选中轨道 `brand.default`、未选 `surface.sunken`、滑块
/// `surface.card`(Ember 没有渐变,§3.5 —— 改版前的 `gradientHeart` 轨道退役)。
class _AgeRangeField extends StatelessWidget {
  const _AgeRangeField({required this.values, required this.onChanged});

  /// 当前区间。
  final RangeValues values;

  /// 变化回调。
  final ValueChanged<RangeValues> onChanged;

  /// 轨道高度(spec §8 未给滑块档,取 `space.4` 与底部分段进度条同档)。
  static const double _trackHeight = tokens.space4;

  /// 滑块直径(spec §8 未给滑块档,12 沿用改版前的手感,可点区域由 Material 自带)。
  static const double _thumbRadius = 12;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // 取值读成一条「年龄,18 – 99 岁」:滑块的两个手柄由 Material 自己播报,
        // 这行文字给的是整体区间的概览(§8.4「颜色/形状之外给文字」)。
        Semantics(
          container: true,
          label: '年龄，${values.start.round()} – ${values.end.round()} 岁',
          child: ExcludeSemantics(
            child: Text(
              '${values.start.round()} – ${values.end.round()} 岁',
              style: TextStyle(
                fontSize: tokens.fontSizeSubtitle,
                fontWeight: FontWeight.w600,
                height: tokens.fontLineHeightSubtitle,
                color: colors.textPrimary,
              ),
            ),
          ),
        ),
        SliderTheme(
          data: SliderTheme.of(context).copyWith(
            trackHeight: _trackHeight,
            activeTrackColor: colors.brandDefault,
            inactiveTrackColor: colors.surfaceSunken,
            thumbColor: colors.surfaceCard,
            overlayColor: colors.brandDefault.withValues(alpha: 0.12),
            rangeTrackShape: const RoundedRectRangeSliderTrackShape(),
            rangeThumbShape: const RoundRangeSliderThumbShape(
              enabledThumbRadius: _thumbRadius,
            ),
            valueIndicatorColor: colors.overlayScrim,
          ),
          child: RangeSlider(
            key: const Key('preference.age'),
            values: values,
            min: 18,
            max: 99,
            divisions: 81,
            labels: RangeLabels(
              values.start.round().toString(),
              values.end.round().toString(),
            ),
            onChanged: onChanged,
          ),
        ),
      ],
    );
  }
}

/// 分组卡:标题 17/w600 + `EmberCard`(与编辑资料页同一口径)。
class _Section extends StatelessWidget {
  const _Section({required this.title, required this.children});

  final String title;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: EdgeInsets.only(bottom: tokens.space12),
          child: Text(
            title,
            style: AppText.subtitle.copyWith(color: colors.textPrimary),
          ),
        ),
        EmberCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              for (var i = 0; i < children.length; i++) ...[
                if (i > 0) SizedBox(height: tokens.space16),
                children[i],
              ],
            ],
          ),
        ),
      ],
    );
  }
}

/// 加载态骨架:三块「标题 + 卡片」(`surface.sunken` 色块,§8.3 骨架)。
class _PreferenceSkeleton extends StatelessWidget {
  const _PreferenceSkeleton();

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (var block = 0; block < 3; block++) ...[
          if (block > 0) SizedBox(height: tokens.space24),
          const EmberSkeleton(width: 72, height: tokens.fontSizeSubtitle),
          SizedBox(height: tokens.space12),
          const EmberSkeleton(
            height: tokens.sizeControlHeight + tokens.space20 * 2,
            radius: tokens.radiusLg,
          ),
        ],
      ],
    );
  }
}
