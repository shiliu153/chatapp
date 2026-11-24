import 'package:flutter/material.dart';

import '../theme/ember_colors.dart';
import '../theme/ember_theme_context.dart';
import '../theme/tokens.g.dart' as tokens;
import 'ember_component_sizes.dart';
import 'ember_pressable.dart';

/// 「余烬 Ember」Chip:胶囊 + 三态(spec §8.3「Chip」行)。
///
/// 逐格对齐状态表:
///
/// | 状态 | 取值 |
/// |---|---|
/// | default | 底 `surface.sunken` / 字 `text.secondary` |
/// | selected | 底 `brand.default` / 字 `brand.on` |
/// | disabled | 底 `surface.sunken` / 字 `text.tertiary` |
/// | pressed | `scale .97`(`spring.fast`,由 [EmberPressable] 提供) |
/// | focus | 外扩 2px `brand.default` + 2px 间隙(同上) |
///
/// **不画描边**:§8.3 的 Chip 行只给底色与字色两种变化 —— 选中态靠实底表达,
/// 再加一圈描边就成了规范里没有的第三种视觉。
///
/// 尺寸:胶囊可视高 [EmberComponentSizes.chipHeight](36),可点区域补到 token
/// `size.touch.app`(48)—— §8.4「图标本体可以小,热区不能缩」。
///
/// 用法(发现页的筛选入口):
///
/// ```dart
/// EmberChip(
///   label: '筛选',
///   icon: PhosphorIconsRegular.slidersHorizontal,
///   selected: filterActive,
///   onTap: openFilterSheet,
/// )
/// ```
class EmberChip extends StatelessWidget {
  /// 构造 chip。
  const EmberChip({
    super.key,
    required this.label,
    this.selected = false,
    this.onTap,
    this.icon,
    this.semanticLabel,
    this.autofocus = false,
  });

  /// 文案(也是读屏默认标签)。
  final String label;

  /// 是否选中(§8.3 selected = `brand.default` + `brand.on`)。
  final bool selected;

  /// 点击回调;`null` 即 disabled(§8.3 disabled 的判据就是「不可点」)。
  final VoidCallback? onTap;

  /// 可选的前置图标(16 档,§6「行内 16」)。
  final IconData? icon;

  /// 覆盖读屏标签;`null` 时按选中态自动补「已选中」。
  final String? semanticLabel;

  /// 是否自动取得焦点(键盘用户)。
  final bool autofocus;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    final disabled = onTap == null;
    return EmberPressable(
      onTap: onTap,
      enabled: !disabled,
      pressedScale: 0.97,
      borderRadius: BorderRadius.circular(tokens.radiusPill),
      autofocus: autofocus,
      semanticLabel: semanticLabel ?? (selected ? '$label，已选中' : label),
      builder: (context, state) {
        final visuals = _resolve(colors, state, disabled: disabled);
        // 外层是 48 的热区,内层才是 36 的胶囊:热区够大,视觉不臃肿(§8.4)。
        return SizedBox(
          height: tokens.sizeTouchApp,
          child: Center(
            widthFactor: 1,
            child: Container(
              height: EmberComponentSizes.chipHeight,
              padding: EdgeInsets.symmetric(horizontal: tokens.space12),
              decoration: BoxDecoration(
                color: visuals.background,
                borderRadius: BorderRadius.circular(tokens.radiusPill),
              ),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  if (icon != null) ...[
                    Icon(icon, size: tokens.sizeIcon16, color: visuals.foreground),
                    SizedBox(width: tokens.space8),
                  ],
                  Text(
                    label,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      fontSize: tokens.fontSizeCaption,
                      // 选中态加粗一档:颜色之外再给一条线索(§8.4「颜色不是唯一线索」)。
                      fontWeight: visuals.emphasized ? FontWeight.w600 : FontWeight.w500,
                      height: tokens.fontLineHeightCaption,
                      color: visuals.foreground,
                    ),
                  ),
                ],
              ),
            ),
          ),
        );
      },
    );
  }

  /// 按状态解析底色 / 前景(§8.3 Chip 行)。
  _ChipVisuals _resolve(
    EmberColors colors,
    EmberPressState state, {
    required bool disabled,
  }) {
    if (disabled) {
      return _ChipVisuals(
        background: colors.surfaceSunken,
        foreground: colors.textTertiary,
      );
    }
    if (selected) {
      return _ChipVisuals(
        background: colors.brandDefault,
        foreground: colors.brandOn,
        emphasized: true,
      );
    }
    return _ChipVisuals(
      // 未选中在按下时压到 surface.card(比 sunken 更「浮」一档),给一次可感知的反馈。
      background: state.pressed ? colors.surfaceCard : colors.surfaceSunken,
      foreground: colors.textSecondary,
    );
  }
}

/// 一次状态解析的结果(底色 / 前景 / 是否加粗)。
@immutable
class _ChipVisuals {
  const _ChipVisuals({
    required this.background,
    required this.foreground,
    this.emphasized = false,
  });

  final Color background;
  final Color foreground;
  final bool emphasized;
}
