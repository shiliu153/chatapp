import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_motion.dart';
import '../theme/app_radius.dart';
import '../theme/app_spacing.dart';
import '../theme/app_typography.dart';

/// 「心跳」规则 §7 输入框:白底 `bgCard`、R16、描边 1px `divider`,
/// 聚焦 1.5px `brand` + 光晕 `brand@12%`(= 规则里的 rgba(255,44,85,.12))。
///
/// 单行盒高恒为 [singleLineHeight];`label` 渲染在盒子**上方**(不用 Material 的
/// 浮动 label,避免与自绘盒子打架);`maxLength` 的计数自己画
/// (不用 `InputDecoration.counterText`,否则样式被主题接管)。
///
/// key 挂在**本组件**上即可 —— `tester.enterText` 会向下找 `EditableText`
/// (`matchRoot: true`),不要给内部 `TextField` 再挂同一个 key。
class AppTextField extends StatefulWidget {
  const AppTextField({
    super.key,
    this.controller,
    this.label,
    this.hint,
    this.errorText,
    this.keyboardType,
    this.maxLength,
    this.counterKey,
    this.maxLines = 1,
    this.minLines,
    this.onChanged,
    this.suffix,
    this.enabled = true,
    this.autofocus = false,
    this.focusNode,
    this.textInputAction,
    this.borderless = false,
  });

  final TextEditingController? controller;
  final String? label;
  final String? hint;
  final String? errorText;
  final TextInputType? keyboardType;
  final int? maxLength;

  /// `maxLength != null` 时计数文本的 key(测试用)。
  final Key? counterKey;
  final int maxLines;
  final int? minLines;
  final ValueChanged<String>? onChanged;
  final Widget? suffix;
  final bool enabled;
  final bool autofocus;
  final FocusNode? focusNode;
  final TextInputAction? textInputAction;

  /// 无边框变体(发动态正文):去掉底色/描边/圆角,只留文字与 hint。
  final bool borderless;

  static const singleLineHeight = 52.0;

  @override
  State<AppTextField> createState() => _AppTextFieldState();
}

class _AppTextFieldState extends State<AppTextField> {
  late final FocusNode _node = widget.focusNode ?? FocusNode();
  late final bool _ownsNode = widget.focusNode == null;
  late int _length = widget.controller?.text.length ?? 0;
  var _focused = false;

  @override
  void initState() {
    super.initState();
    _node.addListener(_onFocusChanged);
  }

  @override
  void dispose() {
    _node.removeListener(_onFocusChanged);
    if (_ownsNode) _node.dispose();
    super.dispose();
  }

  void _onFocusChanged() {
    if (_focused == _node.hasFocus) return;
    setState(() => _focused = _node.hasFocus);
  }

  @override
  Widget build(BuildContext context) {
    final counter = widget.maxLength == null
        ? null
        : Text(
            '$_length/${widget.maxLength}',
            key: widget.counterKey,
            style: AppText.micro.copyWith(color: AppColors.text3),
          );

    if (widget.borderless) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _field(),
          if (counter != null) ...[
            const SizedBox(height: AppSpacing.xs),
            Align(alignment: Alignment.centerRight, child: counter),
          ],
        ],
      );
    }

    final borderColor = widget.errorText != null
        ? AppColors.danger
        : (_focused ? AppColors.brand : AppColors.divider);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (widget.label != null) ...[
          Text(widget.label!,
              style: AppText.caption.copyWith(color: AppColors.text2)),
          const SizedBox(height: AppSpacing.xs),
        ],
        AnimatedContainer(
          duration: AppMotion.fast,
          constraints:
              const BoxConstraints(minHeight: AppTextField.singleLineHeight),
          padding: const EdgeInsets.symmetric(
            horizontal: AppSpacing.lg,
            vertical: AppSpacing.sm,
          ),
          decoration: BoxDecoration(
            color: widget.enabled ? AppColors.bgCard : AppColors.divider,
            borderRadius: BorderRadius.circular(AppRadius.input),
            border: Border.all(
              color: borderColor,
              width: (_focused || widget.errorText != null) ? 1.5 : 1,
            ),
            boxShadow: _focused
                ? [
                    BoxShadow(
                      color: AppColors.brand.withValues(alpha: .12),
                      spreadRadius: 3,
                    ),
                  ]
                : null,
          ),
          child: Row(
            children: [
              Expanded(child: _field()),
              if (widget.suffix != null) ...[
                const SizedBox(width: AppSpacing.md),
                widget.suffix!,
              ],
            ],
          ),
        ),
        if (widget.errorText != null) ...[
          const SizedBox(height: AppSpacing.xs),
          Text(widget.errorText!,
              style: AppText.micro.copyWith(color: AppColors.danger)),
        ],
        if (counter != null) ...[
          const SizedBox(height: AppSpacing.xs),
          Align(alignment: Alignment.centerRight, child: counter),
        ],
      ],
    );
  }

  Widget _field() => TextField(
        controller: widget.controller,
        focusNode: _node,
        enabled: widget.enabled,
        autofocus: widget.autofocus,
        keyboardType: widget.keyboardType,
        textInputAction: widget.textInputAction,
        maxLength: widget.maxLength,
        maxLines: widget.maxLines,
        minLines: widget.minLines,
        onChanged: (value) {
          setState(() => _length = value.length);
          widget.onChanged?.call(value);
        },
        style: AppText.body.copyWith(color: AppColors.text1),
        decoration: InputDecoration(
          isDense: true,
          border: InputBorder.none,
          contentPadding: EdgeInsets.zero,
          counterText: '', // 计数自己画
          hintText: widget.hint,
          hintStyle: AppText.body.copyWith(color: AppColors.text3),
        ),
      );
}
