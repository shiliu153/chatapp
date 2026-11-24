/// 资料表单字段(Ember 口径,page spec §3):编辑资料页与完善资料向导共用。
///
/// 每个字段 = 可见标签(caption 13 / `text.secondary`)+ 控件本体:
/// - 文本输入走 `EmberField`(高 52、`surface.card` + 1px `border.divider`、
///   focus 2px `brand.default` + 2px 外扩、error 2px `status.danger` **且必须带文字**);
/// - 单选(性别)走 `EmberChip`(选中 = `brand.default` 实底 + `brand.on` 字);
/// - 选择器(生日)是「长得像输入框的按钮」,取值同 §8.3 输入框 default / error 两态。
///
/// **校验失败只在字段下方给 `status.danger` 文字 + 描边转红,不弹全局 Toast**
/// (page spec §5「表单校验失败」)。错误文字由字段自己渲染,页面只负责把 `errorText`
/// 传下来。
///
/// 读屏口径(page spec §6 第 3 条):字段读「标签,值」,错误态读「标签,错误说明」。
/// 所以**可见标签**一律 `ExcludeSemantics`(它的文字已经进了控件的 `label`),错误态
/// 把说明并进同一条 `label` —— 一句完整播报,而不是「标签」「值」「说明」三条碎念。
/// 唯一的例外是 `EmberField` 自己画的那行错误文字(组件在 core 层,本单不改):
/// 它会作为一条独立节点再被念一遍,PR「遗留」记了这条。
library;

import 'package:flutter/material.dart';
import 'package:phosphor_glyphs/phosphor_glyphs.dart';

import '../../../core/format.dart';
import '../../../core/theme/ember_theme_context.dart';
import '../../../core/theme/tokens.g.dart' as tokens;
import '../../../core/ui/ember_ui.dart';
import 'tag_selector.dart';

/// 字段的读屏标签:错误态并上说明(page spec §6「标签,错误说明」)。
String _reading({required String label, String? errorText}) =>
    errorText == null || errorText.isEmpty ? label : '$label，$errorText';

/// 字段外壳:可见标签 + 控件。
class _FieldShell extends StatelessWidget {
  const _FieldShell({
    required this.label,
    required this.child,
    this.labelInSemantics = true,
  });

  /// 字段名(可见文字)。
  final String label;

  /// 控件本体。
  final Widget child;

  /// 可见标签是否从语义树里摘掉。
  ///
  /// 文本输入 / 选择器把标签放进了控件自己的 `label`(读成一条),这里摘掉避免重复;
  /// 成组的控件(chip)没有单一 `label` 可挂,标签要留在树里当组名。
  final bool labelInSemantics;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    final labelText = Text(
      label,
      style: TextStyle(
        fontSize: tokens.fontSizeCaption,
        height: tokens.fontLineHeightCaption,
        color: colors.textSecondary,
      ),
    );
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        labelInSemantics ? ExcludeSemantics(child: labelText) : labelText,
        SizedBox(height: tokens.space8),
        child,
      ],
    );
  }
}

/// 字段下方的一行错误说明(13 / `status.danger`),给成组控件自己用。
///
/// 说明文字已并进控件的读屏标签,所以这里 `ExcludeSemantics`:视觉上要有,读屏不重复。
class _FieldError extends StatelessWidget {
  const _FieldError(this.message);

  final String message;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.only(top: tokens.space4),
      child: ExcludeSemantics(
        child: Text(
          message,
          style: TextStyle(
            fontSize: tokens.fontSizeCaption,
            height: tokens.fontLineHeightCaption,
            color: context.ember.statusDanger,
          ),
        ),
      ),
    );
  }
}

/// 昵称(≤ 20 字)。
class NicknameField extends StatelessWidget {
  const NicknameField({super.key, required this.controller, this.errorText});

  /// 文本控制器。
  final TextEditingController controller;

  /// 校验失败的中文说明;非空即 error 态(描边转红 + 下方红字)。
  final String? errorText;

  @override
  Widget build(BuildContext context) => _FieldShell(
        label: '昵称',
        child: EmberField(
          fieldKey: const Key('edit.nickname'),
          controller: controller,
          placeholder: '20 字以内',
          label: _reading(label: '昵称', errorText: errorText),
          errorText: errorText,
          maxLength: 20,
        ),
      );
}

/// 性别(男 / 女单选)。
class GenderSelector extends StatelessWidget {
  const GenderSelector({
    super.key,
    required this.value,
    required this.onChanged,
    this.errorText,
  });

  /// 当前取值(`male` / `female` / `null` 未选)。
  final String? value;

  /// 选择回调。
  final ValueChanged<String> onChanged;

  /// 校验失败的中文说明。
  final String? errorText;

  @override
  Widget build(BuildContext context) => _FieldShell(
        label: '性别',
        // 成组控件:标签留在语义树里当组名(chip 各自读「男,已选中」)。
        labelInSemantics: false,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Wrap(
              spacing: tokens.space8,
              children: [
                EmberChip(
                  label: '男',
                  selected: value == 'male',
                  onTap: () => onChanged('male'),
                ),
                EmberChip(
                  label: '女',
                  selected: value == 'female',
                  onTap: () => onChanged('female'),
                ),
              ],
            ),
            if (errorText != null) _FieldError(errorText!),
          ],
        ),
      );
}

/// 生日(日期选择器;未满 18 岁的日期选不出来)。
class BirthdayField extends StatelessWidget {
  const BirthdayField({
    super.key,
    required this.value,
    required this.onChanged,
    this.errorText,
  });

  /// 当前取值。
  final DateTime? value;

  /// 选择回调。
  final ValueChanged<DateTime> onChanged;

  /// 校验失败的中文说明。
  final String? errorText;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    final hasError = errorText != null && errorText!.isNotEmpty;
    final text = value == null ? null : formatDate(value!);
    return _FieldShell(
      label: '生日',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          EmberPressable(
            key: const Key('edit.birthday'),
            // 选择器没有可编辑的值,标签 + 取值(或错误说明)合成一句播报。
            semanticLabel: hasError ? '生日，$errorText' : (text == null ? '生日，未选择' : '生日，$text'),
            pressedScale: 0.97,
            borderRadius: BorderRadius.circular(tokens.radiusMd),
            onTap: () => _pick(context),
            builder: (context, state) => Container(
              height: tokens.sizeControlHeight,
              padding: EdgeInsets.symmetric(horizontal: tokens.space16),
              decoration: BoxDecoration(
                color: colors.surfaceCard,
                borderRadius: BorderRadius.circular(tokens.radiusMd),
                // 与 §8.3 输入框同口径:error 2px `status.danger`,其余 1px `border.divider`。
                border: Border.all(
                  color: hasError ? colors.statusDanger : colors.borderDivider,
                  width: hasError ? 2 : 1,
                ),
              ),
              child: Row(
                children: [
                  Expanded(
                    child: Text(
                      text ?? '选择生日',
                      style: TextStyle(
                        fontSize: tokens.fontSizeBody,
                        color: text == null
                            ? colors.textTertiary
                            : colors.textPrimary,
                      ),
                    ),
                  ),
                  Icon(
                    PhosphorIconsRegular.caretDown,
                    size: tokens.sizeIcon16,
                    color: colors.textTertiary,
                  ),
                ],
              ),
            ),
          ),
          if (hasError) _FieldError(errorText!),
        ],
      ),
    );
  }

  /// 弹系统日期选择器;上限卡在 18 年前(未满 18 岁选不出来,与改版前一致)。
  Future<void> _pick(BuildContext context) async {
    final now = DateTime.now();
    final picked = await showDatePicker(
      context: context,
      initialDate: value ?? DateTime(now.year - 25, now.month, now.day),
      firstDate: DateTime(now.year - 100),
      lastDate: DateTime(now.year - 18, now.month, now.day),
      helpText: '选择生日',
    );
    if (picked != null) onChanged(picked);
  }
}

/// 城市(≤ 50 字)。
class CityField extends StatelessWidget {
  const CityField({super.key, required this.controller, this.errorText});

  /// 文本控制器。
  final TextEditingController controller;

  /// 校验失败的中文说明。
  final String? errorText;

  @override
  Widget build(BuildContext context) => _FieldShell(
        label: '城市',
        child: EmberField(
          fieldKey: const Key('edit.city'),
          controller: controller,
          placeholder: '例如:杭州',
          label: _reading(label: '城市', errorText: errorText),
          errorText: errorText,
          maxLength: 50,
        ),
      );
}

/// 简介(≤ 200 字,三行)。
class BioField extends StatelessWidget {
  const BioField({super.key, required this.controller, this.errorText});

  /// 文本控制器。
  final TextEditingController controller;

  /// 校验失败的中文说明。
  final String? errorText;

  @override
  Widget build(BuildContext context) => _FieldShell(
        label: '简介',
        child: EmberField(
          fieldKey: const Key('edit.bio'),
          controller: controller,
          placeholder: '介绍一下自己',
          label: _reading(label: '简介', errorText: errorText),
          errorText: errorText,
          maxLines: 3,
          maxLength: 200,
        ),
      );
}

/// 标签多选(胶囊,选中 = `brand.default` 实底 + `brand.on` 字,§8.3 Chip)。
///
/// 标签本身由 [`TagSelector`] 拉取并渲染(加载 / 失败态也在它内部),这里只补一层
/// 「标签」这个可见组名;组名留在语义树里当组头(chip 各自读「运动,已选中」)。
class TagField extends StatelessWidget {
  const TagField({super.key, required this.selectedIds, required this.onChanged});

  /// 已选标签 id。
  final Set<int> selectedIds;

  /// 选择变化回调。
  final ValueChanged<Set<int>> onChanged;

  @override
  Widget build(BuildContext context) => _FieldShell(
        label: '标签',
        labelInSemantics: false,
        child: TagSelector(selectedIds: selectedIds, onChanged: onChanged),
      );
}

/// 提交失败提示条:表单底部一条 `status.danger` 描边 + 图标 + 文案(page spec §5
/// 「提交失败 → 表单底部提示条 + 保留已填内容」)。
///
/// 用 `liveRegion` 播报:提交失败往往伴随一次网络往返,读屏用户不会主动去翻表单底部。
class FormErrorBanner extends StatelessWidget {
  const FormErrorBanner({super.key, required this.message});

  /// 失败原因(后端中文文案)。
  final String message;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    return Semantics(
      liveRegion: true,
      label: '保存失败，$message',
      child: Container(
        padding: EdgeInsets.symmetric(
          horizontal: tokens.space12,
          vertical: tokens.space8,
        ),
        decoration: BoxDecoration(
          color: colors.surfaceCard,
          borderRadius: BorderRadius.circular(tokens.radiusMd),
          border: Border.all(color: colors.statusDanger),
        ),
        child: Row(
          children: [
            Icon(
              PhosphorIconsRegular.warningCircle,
              size: tokens.sizeIcon16,
              color: colors.statusDanger,
            ),
            SizedBox(width: tokens.space8),
            Expanded(
              child: Text(
                message,
                style: TextStyle(
                  fontSize: tokens.fontSizeCaption,
                  height: tokens.fontLineHeightCaption,
                  color: colors.statusDanger,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
