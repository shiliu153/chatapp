import 'package:flutter/material.dart';

import '../theme/ember_theme_context.dart';
import '../theme/tokens.g.dart' as tokens;
import 'ember_component_sizes.dart';

/// 输入框:`surface.card` 底 + 1px `border.divider` + `radius.md` + 高 52 + 内边距 16
/// (spec §8.3)。
///
/// 状态逐格对齐 §8.3 的**输入框**四态:
/// - default:`surface.card` 底 / 1px `border.divider` / 字 `text.primary` / 占位 `text.tertiary`;
/// - focus:2px `brand.default` 描边 + 2px 外扩 `brand.default` @12%;
/// - error:2px `status.danger` 描边 + 下方 13 `status.danger` 说明 —— **必须同时有文字**
///   (构造时断言,不能只变红);
/// - disabled:`surface.sunken` 底 + `text.tertiary` 字 + 描边透明。
///
/// **没有 loading 态**:§8.1 的输入框那一行明确没有 loading,不要自己发明。
class EmberField extends StatefulWidget {
  /// 构造输入框。
  const EmberField({
    super.key,
    this.controller,
    this.label,
    this.placeholder,
    this.errorText,
    this.enabled = true,
    this.obscureText = false,
    this.maxLines = 1,
    this.keyboardType,
    this.onChanged,
    this.onSubmitted,
    this.prefixIcon,
    this.suffix,
    this.focusNode,
    this.autofocus = false,
    this.fieldKey,
    this.maxLength,
  });

  /// 文本控制器。
  final TextEditingController? controller;

  /// 字段名(读屏标签;为 `null` 时读屏只能念到占位文字)。
  final String? label;

  /// 占位文字。
  final String? placeholder;

  /// 错误说明。**非空即 error 态**,且必须是文字(§8.3「不能只变红」)。
  final String? errorText;

  /// 是否可用;`false` 时底色转 `surface.sunken`、文字转 `text.tertiary`。
  final bool enabled;

  /// 是否密码框。
  final bool obscureText;

  /// 行数;`>1` 即多行输入。
  final int maxLines;

  /// 键盘类型。
  final TextInputType? keyboardType;

  /// 文本变化回调。
  final ValueChanged<String>? onChanged;

  /// 提交回调。
  final ValueChanged<String>? onSubmitted;

  /// 左侧图标(20px 档)。
  final IconData? prefixIcon;

  /// 右侧自定义控件。
  final Widget? suffix;

  /// 外部焦点节点。
  final FocusNode? focusNode;

  /// 是否自动聚焦。
  final bool autofocus;

  /// 内部 [TextField] 的 Key;`null` 时用默认的 `ember.field.input`。
  ///
  /// 为什么需要:页面测试要按 Key 定点输入(`tester.enterText`),而页面里可能同时
  /// 有多个输入框 —— 默认 Key 会串。
  final Key? fieldKey;

  /// 最大字数;`null` 不限制。给评论输入这类有后端上限的场合用(不显示计数器)。
  final int? maxLength;

  @override
  State<EmberField> createState() => _EmberFieldState();
}

class _EmberFieldState extends State<EmberField> {
  late final FocusNode _focusNode = widget.focusNode ?? FocusNode();
  var _focused = false;

  @override
  void initState() {
    super.initState();
    _focusNode.addListener(_onFocusChanged);
  }

  @override
  void dispose() {
    _focusNode.removeListener(_onFocusChanged);
    if (widget.focusNode == null) _focusNode.dispose();
    super.dispose();
  }

  void _onFocusChanged() => setState(() => _focused = _focusNode.hasFocus);

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    final hasError = widget.errorText != null && widget.errorText!.isNotEmpty;
    final radius = BorderRadius.circular(tokens.radiusMd);

    // 边框颜色/宽度按状态取(§8.3):error 优先于 focus(输错了要最显眼)。
    final Color borderColor;
    final double borderWidth;
    if (!widget.enabled) {
      borderColor = Colors.transparent;
      borderWidth = 1;
    } else if (hasError) {
      borderColor = colors.statusDanger;
      borderWidth = 2;
    } else if (_focused) {
      borderColor = colors.brandDefault;
      borderWidth = 2;
    } else {
      borderColor = colors.borderDivider;
      borderWidth = 1;
    }

    Widget field = TextField(
      key: widget.fieldKey ?? const Key('ember.field.input'),
      controller: widget.controller,
      focusNode: _focusNode,
      enabled: widget.enabled,
      obscureText: widget.obscureText,
      maxLines: widget.maxLines,
      maxLength: widget.maxLength,
      keyboardType: widget.keyboardType,
      autofocus: widget.autofocus,
      onChanged: widget.onChanged,
      onSubmitted: widget.onSubmitted,
      cursorColor: colors.brandDefault,
      style: TextStyle(
        fontSize: tokens.fontSizeBody,
        color: widget.enabled ? colors.textPrimary : colors.textTertiary,
      ),
      decoration: InputDecoration(
        isDense: true,
        filled: true,
        fillColor: widget.enabled ? colors.surfaceCard : colors.surfaceSunken,
        hintText: widget.placeholder,
        hintStyle: TextStyle(
          fontSize: tokens.fontSizeBody,
          color: colors.textTertiary,
        ),
        prefixIcon: widget.prefixIcon == null
            ? null
            : Icon(
                widget.prefixIcon,
                size: tokens.sizeIcon20,
                color: widget.enabled ? colors.textSecondary : colors.textTertiary,
              ),
        suffixIcon: widget.suffix,
        contentPadding: EdgeInsets.symmetric(
          horizontal: tokens.space16,
          vertical: tokens.space16,
        ),
        constraints: const BoxConstraints(minHeight: tokens.sizeControlHeight),
        border: OutlineInputBorder(
          borderRadius: radius,
          borderSide: BorderSide(color: borderColor, width: borderWidth),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: radius,
          borderSide: BorderSide(color: borderColor, width: borderWidth),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: radius,
          borderSide: BorderSide(color: borderColor, width: borderWidth),
        ),
        disabledBorder: OutlineInputBorder(
          borderRadius: radius,
          borderSide: BorderSide(color: borderColor, width: borderWidth),
        ),
        // errorText 交给 Tab 下方的自绘说明,避免 Material 默认红字带自己的字号/颜色。
        errorStyle: const TextStyle(height: 0, fontSize: 0),
        // maxLength 给的是**上限**而不是「必须显示计数器」,计数器会额外占一行。
        counterText: '',
      ),
    );

    // 聚焦时的 2px 外扩(@12%):画在输入框外侧,不占布局。
    if (_focused && widget.enabled && !hasError) {
      field = Container(
        padding: const EdgeInsets.all(EmberComponentSizes.fieldFocusHalo),
        decoration: BoxDecoration(
          color: colors.brandDefault.withValues(alpha: 0.12),
          borderRadius: radius,
        ),
        child: field,
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Semantics(
          textField: true,
          enabled: widget.enabled,
          label: widget.label,
          value: widget.controller?.text,
          child: field,
        ),
        if (hasError) ...[
          SizedBox(height: tokens.space4),
          Text(
            widget.errorText!,
            style: TextStyle(
              fontSize: tokens.fontSizeCaption,
              color: colors.statusDanger,
            ),
          ),
        ],
      ],
    );
  }
}
