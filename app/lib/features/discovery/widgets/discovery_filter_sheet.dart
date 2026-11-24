import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/theme/app_typography.dart';
import '../../../core/theme/ember_theme_context.dart';
import '../../../core/theme/tokens.g.dart' as tokens;
import '../../../core/ui/ember_ui.dart';
import '../../../core/widgets/app_range_field.dart';
import '../../../core/widgets/app_text_field.dart';
import '../../profile/models.dart';
import '../../profile/widgets/tag_selector.dart';
import '../models.dart';

/// 年龄筛选的可选区间(与「想找的人」设置页同口径)。
const filterAgeMin = 18;
const filterAgeMax = 99;

/// 弹出发现页筛选面板(批次 S;E-5.2 起换成 [EmberSheet])。
///
/// 面板是**纯临时**的:默认值 = 当前偏好([preference])叠加已生效的筛选([initial]),
/// 「应用」/「重置」都只把结果 pop 出去,**不写回偏好**、不落 shared_preferences。
///
/// 返回 `null` = 用户没应用(点空白/返回键关掉);否则是新的筛选态
/// (`DiscoveryFilter.none` 表示重置)。
///
/// 层级口径(「余烬 Ember」§9.3):单一维度筛选 = 底部 sheet,最高占屏 ≤60%,
/// scrim `overlay.scrim`,形态交给 [EmberSheet]。
Future<DiscoveryFilter?> showDiscoveryFilterSheet(
  BuildContext context, {
  required Preference preference,
  required DiscoveryFilter initial,
}) {
  return EmberSheet.show<DiscoveryFilter>(
    context,
    maxHeightRatio: 0.6,
    // 面板中部本身就是可滚区(矮屏 / 大字号时内容会超出一屏):BottomSheet 自带的
    // 竖向拖拽会和滚动抢同一串手势 —— 表现为「拖不动内容,反而把面板拖走」。
    // 所以关掉下拉关闭,仍保留点遮罩 / 返回键关闭。
    draggable: false,
    child: DiscoveryFilterSheet(preference: preference, initial: initial),
  );
}

/// 筛选面板本体:年龄双滑块 + 城市 + 标签多选,底部「重置」/「应用」。
///
/// 面板里的控件初值合并了两层来源:已生效的筛选优先,没筛过的字段回落到偏好 ——
/// 所以「只筛过城市」时,年龄滑块显示的仍是偏好里的区间。
class DiscoveryFilterSheet extends ConsumerStatefulWidget {
  /// 构造面板。
  const DiscoveryFilterSheet({
    super.key,
    required this.preference,
    this.initial = DiscoveryFilter.none,
  });

  /// 当前偏好(设置页 `PATCH /users/me/preference` 那一份),面板的兜底默认值。
  final Preference preference;

  /// 已经生效的筛选;为空 = 完全按偏好。
  final DiscoveryFilter initial;

  @override
  ConsumerState<DiscoveryFilterSheet> createState() => _DiscoveryFilterSheetState();
}

class _DiscoveryFilterSheetState extends ConsumerState<DiscoveryFilterSheet> {
  late RangeValues _age;
  late final TextEditingController _city;
  late Set<int> _tagIds;

  @override
  void initState() {
    super.initState();
    final preference = widget.preference;
    final initial = widget.initial;
    _age = RangeValues(
      _clampAge(initial.ageMin ?? preference.ageMin).toDouble(),
      _clampAge(initial.ageMax ?? preference.ageMax).toDouble(),
    );
    _city = TextEditingController(text: initial.city ?? preference.city);
    _tagIds = {...initial.tagIds};
  }

  @override
  void dispose() {
    _city.dispose();
    super.dispose();
  }

  static int _clampAge(int age) => age.clamp(filterAgeMin, filterAgeMax);

  /// 把面板上的值**减去偏好**得到筛选对象:没动过的字段留 `null`,请求里就不带。
  ///
  /// 三个「不发」的情形:
  /// 1. 年龄区间 == 偏好区间 → 不发 `age_min`/`age_max`(等价,少发更清楚);
  /// 2. 城市留空或与偏好相同 → 不发 `city`(后端把空串当「没传」,等价于沿用偏好);
  /// 3. 没选标签 → 不发 `tag_ids`。
  DiscoveryFilter _compose() {
    final preference = widget.preference;
    final min = _age.start.round();
    final max = _age.end.round();
    final ageChanged = min != _clampAge(preference.ageMin) ||
        max != _clampAge(preference.ageMax);
    final city = _city.text.trim();
    return DiscoveryFilter(
      ageMin: ageChanged ? min : null,
      ageMax: ageChanged ? max : null,
      city: city.isEmpty || city == preference.city ? null : city,
      tagIds: _tagIds.toList()..sort(),
    );
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    return Padding(
      // 键盘弹起时把面板整体顶上去,城市输入框不会被挡住
      padding: EdgeInsets.only(bottom: MediaQuery.viewInsetsOf(context).bottom),
      child: SafeArea(
        top: false,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Padding(
              padding: EdgeInsets.fromLTRB(
                tokens.space20,
                tokens.space8,
                tokens.space20,
                0,
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '筛选',
                    // `title` 24 / Fraunces(§4.2 弹层标题)。
                    style: AppText.title.copyWith(color: colors.textPrimary),
                  ),
                  SizedBox(height: tokens.space4),
                  Text(
                    '只影响这一次的候选池,不会改掉「想找的人」设置',
                    style: AppText.caption.copyWith(color: colors.textSecondary),
                  ),
                ],
              ),
            ),
            Flexible(
              child: SingleChildScrollView(
                padding: EdgeInsets.fromLTRB(
                  tokens.space20,
                  tokens.space16,
                  tokens.space20,
                  tokens.space16,
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    AppRangeField(
                      key: const Key('filter.age'),
                      title: '年龄 ${_age.start.round()} – ${_age.end.round()} 岁',
                      values: _age,
                      min: filterAgeMin.toDouble(),
                      max: filterAgeMax.toDouble(),
                      divisions: filterAgeMax - filterAgeMin,
                      onChanged: (values) => setState(() => _age = values),
                    ),
                    SizedBox(height: tokens.space16),
                    AppTextField(
                      key: const Key('filter.city'),
                      controller: _city,
                      label: '城市(留空 = 不限)',
                      maxLength: 50,
                    ),
                    SizedBox(height: tokens.space16),
                    Text(
                      '兴趣标签(可多选,命中其一即可)',
                      style: AppText.subtitle.copyWith(color: colors.textPrimary),
                    ),
                    SizedBox(height: tokens.space12),
                    TagSelector(
                      key: const Key('filter.tags'),
                      selectedIds: _tagIds,
                      onChanged: (ids) => setState(() => _tagIds = {...ids}),
                    ),
                  ],
                ),
              ),
            ),
            Padding(
              padding: EdgeInsets.fromLTRB(
                tokens.space20,
                0,
                tokens.space20,
                tokens.space16,
              ),
              child: Row(
                children: [
                  Expanded(
                    child: EmberButton(
                      key: const Key('filter.reset'),
                      label: '重置',
                      variant: EmberButtonVariant.secondary,
                      expand: true,
                      // 重置 = 回到「完全按偏好」,并立刻关面板让候选池重拉
                      onPressed: () => Navigator.of(context).pop(DiscoveryFilter.none),
                    ),
                  ),
                  SizedBox(width: tokens.space12),
                  Expanded(
                    child: EmberButton(
                      key: const Key('filter.apply'),
                      label: '应用',
                      expand: true,
                      onPressed: () => Navigator.of(context).pop(_compose()),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
