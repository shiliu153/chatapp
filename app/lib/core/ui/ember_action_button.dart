import 'package:flutter/material.dart';

import '../theme/app_shadows.dart';
import '../theme/ember_colors.dart';
import '../theme/ember_theme_context.dart';
import '../theme/tokens.g.dart' as tokens;
import 'ember_component_sizes.dart';
import 'ember_glow.dart';
import 'ember_pressable.dart';

/// 圆形操作钮的两种形态(E-5.2 page spec §4「喜欢钮 / 跳过钮」)。
enum EmberActionButtonVariant {
  /// 主操作(喜欢):`brand.default` 实底 + `brand.on` 图标 + `emberGlow`。
  primary,

  /// 次操作(跳过):`surface.card` 底 + 1px `border.divider` + `text.tertiary` 图标。
  neutral,
}

/// 圆形操作钮的两档直径(E-5.2 page spec §3「圆形 56 / 64」)。
enum EmberActionButtonSize {
  /// 56(次操作:跳过)。
  small,

  /// 64(主操作:喜欢)。
  large,
}

/// 「余烬 Ember」圆形操作钮:滑卡的喜欢 / 跳过,也可以是任何「单个动作」的圆钮。
///
/// 逐格对齐 E-5.2 page spec §4 的状态表:
///
/// | 状态 | 主(喜欢) | 次(跳过) |
/// |---|---|---|
/// | default | `brand.default` 实底 + `brand.on` 图标 24 + `emberGlow` | `surface.card` + 1px `border.divider` + `text.tertiary` 图标 |
/// | pressed | `scale .97` + 光晕降至 50% | `surface.sunken` 底 + `scale .97` |
/// | disabled(额度用完) | `surface.sunken` 底 + `text.tertiary` 图标 + `border.divider` 描边,**无光晕无按压** | 同「主」的置灰取值 |
/// | loading | 保持底与图标,尾随 16 转圈,禁点击 | 同左,转圈取 `brand.default` |
///
/// 三条实现纪律:
/// 1. **没有渐变、没有循环动画**:心跳期「粉橙渐变 + 心跳脉冲」已被 spec §7.3 取消
///    (装饰性循环动画只允许在线点呼吸与骨架屏);
/// 2. 光晕只属于主操作且一屏最多一处(§2 `emberGlow`),禁用态连光晕一起撤掉;
/// 3. 图标按钮必须有读屏标签(§8.4),所以 [semanticLabel] 是必填项。
class EmberActionButton extends StatelessWidget {
  /// 构造圆钮。
  const EmberActionButton({
    super.key,
    required this.icon,
    required this.semanticLabel,
    this.onPressed,
    this.variant = EmberActionButtonVariant.neutral,
    this.size = EmberActionButtonSize.small,
    this.loading = false,
    this.autofocus = false,
  });

  /// 图标(按 §6 取 Phosphor;常规 24 档)。
  final IconData icon;

  /// 读屏标签(§8.4:图标按钮必须有),同时也是按下时可读的「按钮」语义。
  final String semanticLabel;

  /// 点击回调;`null` 即 disabled(额度用完 / 请求在飞),此时无光晕、无按压反馈。
  final VoidCallback? onPressed;

  /// 形态。
  final EmberActionButtonVariant variant;

  /// 直径档位。
  final EmberActionButtonSize size;

  /// 是否处于 loading:保持底与图标,尾随 16 转圈,**禁点击**(§8.3 按钮 loading 行)。
  final bool loading;

  /// 是否自动取得焦点(键盘用户)。
  final bool autofocus;

  /// 直径(像素),按 [size] 档位取 [EmberComponentSizes] 里的定值。
  static double diameterOf(EmberActionButtonSize size) =>
      switch (size) {
        EmberActionButtonSize.small => EmberComponentSizes.actionButtonSmall,
        EmberActionButtonSize.large => EmberComponentSizes.actionButtonLarge,
      };

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final disabled = onPressed == null;
    final interactive = !disabled && !loading;
    final diameter = diameterOf(size);
    final radius = BorderRadius.circular(tokens.radiusPill);

    return EmberPressable(
      onTap: interactive ? onPressed : null,
      enabled: interactive,
      pressedScale: 0.97,
      borderRadius: radius,
      autofocus: autofocus,
      semanticLabel: loading ? '$semanticLabel，处理中' : semanticLabel,
      builder: (context, state) {
        final visuals = _resolve(colors, state, disabled: disabled, isDark: isDark);
        Widget content = SizedBox.square(
          dimension: diameter,
          child: DecoratedBox(
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: visuals.background,
              border: visuals.border,
              boxShadow: visuals.shadow,
            ),
            child: Center(
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(icon, size: tokens.sizeIcon24, color: visuals.foreground),
                  if (loading) ...[
                    SizedBox(width: tokens.space4),
                    _spinner(
                      variant == EmberActionButtonVariant.primary
                          ? colors.brandOn
                          : colors.brandDefault,
                    ),
                  ],
                ],
              ),
            ),
          ),
        );

        // 光晕只属于主操作,且按下时降到 50%(§8.3);禁用态连光晕一起撤掉。
        if (variant != EmberActionButtonVariant.primary || disabled) return content;
        content = EmberGlow(
          shape: EmberGlowShape.circle,
          opacity: state.pressed ? 0.06 : 0.12,
          spread: tokens.space8,
          child: content,
        );
        return content;
      },
    );
  }

  Widget _spinner(Color color) => SizedBox(
        width: tokens.sizeIcon16,
        height: tokens.sizeIcon16,
        child: CircularProgressIndicator(strokeWidth: 2, color: color),
      );

  /// 按形态 + 状态解析底色 / 前景 / 描边 / 阴影(E-5.2 page spec §4)。
  _ActionVisuals _resolve(
    EmberColors colors,
    EmberPressState state, {
    required bool disabled,
    required bool isDark,
  }) {
    // 深色模式不用阴影,改 1px 描边 + 表面色差分层的口径(§5.3)—— 对两个形态都成立。
    final neutralBorder = Border.all(color: colors.borderDivider);
    if (disabled) {
      return _ActionVisuals(
        background: colors.surfaceSunken,
        foreground: colors.textTertiary,
        border: neutralBorder,
      );
    }
    return switch (variant) {
      EmberActionButtonVariant.primary => _ActionVisuals(
          background: colors.brandDefault,
          foreground: colors.brandOn,
        ),
      EmberActionButtonVariant.neutral => _ActionVisuals(
          background: state.pressed ? colors.surfaceSunken : colors.surfaceCard,
          foreground: colors.textTertiary,
          border: neutralBorder,
          // 浅色给一张 elev.1(浮起来的次要操作),深色靠描边分层,不加阴影。
          shadow: isDark ? null : AppShadows.card,
        ),
    };
  }
}

/// 一次状态解析的结果(底色 / 前景 / 描边 / 阴影)。
@immutable
class _ActionVisuals {
  const _ActionVisuals({
    required this.background,
    required this.foreground,
    this.border,
    this.shadow,
  });

  final Color background;
  final Color foreground;
  final BoxBorder? border;
  final List<BoxShadow>? shadow;
}
