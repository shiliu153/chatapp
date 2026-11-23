import 'package:flutter/material.dart';

import '../theme/ember_colors.dart';
import '../theme/ember_theme_context.dart';
import '../theme/tokens.g.dart' as tokens;
import 'ember_glow.dart';
import 'ember_pressable.dart';

/// 按钮的四种形态(spec §8.2 / §8.3)。
enum EmberButtonVariant {
  /// 主按钮:`brand.default` 实底 + `brand.on` 文字 + `emberGlow`。
  primary,

  /// 次按钮:`surface.card` 底 + 1px `border.divider` + `text.primary` 文字。
  secondary,

  /// 文字按钮:`brand.default` 文字,无底。
  text,

  /// 危险按钮:`status.danger` 描边(实底只在二次确认后出现)。
  danger,
}

/// 「余烬 Ember」按钮:高 52、`radius.pill`、按压 `scale .97`(spec §8.2)。
///
/// 逐格对齐 §8.3 的**按钮**状态表:
///
/// | 状态 | 主 | 次 | 文字 | 危险 |
/// |---|---|---|---|---|
/// | default | brand 实底 + brand.on + 光晕 | card 底 + divider 描边 | brand 文字无底 | danger 描边 |
/// | pressed | scale .97 + 光晕降至 50% | sunken 底 + scale .97 | sunken 底 | danger 实底 + onDanger |
/// | focus | 外扩 2px brand + 2px 间隙 | 同左 | 同左 | 外扩 2px danger |
/// | disabled | sunken 底 + tertiary 字 + 无光晕 | 同左 + 描边透明 | tertiary 字 | 同左 |
/// | loading | 保持底与字 + 尾随 16 转圈,禁点击 | 同左,转圈取 brand | 转圈替换文字 | 同主按钮 |
///
/// **规格缺口(本单按 §8.3 就近落地,留给 flow 栈补 token)**:§3.4 与 §8.2 写的是
/// 「按钮文字 16px / w700」,而 `design/tokens/scale.json` 只有 `font.size.body` = 15,
/// 没有 16 这一档。为了守住「禁止裸字号」,这里用 `fontSizeBody` + `w700`,
/// 1px 的字号差记在 PR 的「遗留」里 —— 补 token 才是正解,不该在组件里写 16。
class EmberButton extends StatelessWidget {
  /// 构造按钮。
  const EmberButton({
    super.key,
    required this.label,
    this.onPressed,
    this.variant = EmberButtonVariant.primary,
    this.loading = false,
    this.icon,
    this.expand = false,
    this.autofocus = false,
    this.semanticsLabel,
  });

  /// 按钮文字(也是读屏默认标签)。
  final String label;

  /// 点击回调;`null` 即 disabled(§8.3 disabled 的判据就是「不可点」)。
  final VoidCallback? onPressed;

  /// 形态。
  final EmberButtonVariant variant;

  /// 是否处于 loading:保持底与字,尾随 16 转圈,**禁点击**。
  final bool loading;

  /// 可选的左侧图标(20px,§6 尺寸档)。
  final IconData? icon;

  /// 是否撑满父容器宽度。
  final bool expand;

  /// 是否自动取得焦点(键盘用户)。
  final bool autofocus;

  /// 覆盖读屏标签(默认用 [label];loading 时会自动补「处理中」)。
  final String? semanticsLabel;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    // loading 与 disabled 是两回事(§8.3):loading 保持底与字,只是禁点击。
    final disabled = onPressed == null;
    final interactive = !disabled && !loading;
    final radius = BorderRadius.circular(tokens.radiusPill);
    final labelStyle = TextStyle(
      fontSize: tokens.fontSizeBody,
      fontWeight: FontWeight.w700,
      // 行高取正文档(1.55 的松行距在按钮里会撑高按钮,这里按 §8.2 的「高 52」收住)。
      height: 1.2,
    );

    return EmberPressable(
      onTap: interactive ? onPressed : null,
      enabled: interactive,
      pressedScale: 0.97,
      borderRadius: radius,
      autofocus: autofocus,
      focusColor: variant == EmberButtonVariant.danger ? colors.statusDanger : null,
      semanticLabel: semanticsLabel ?? (loading ? '$label，处理中' : label),
      builder: (context, state) {
        final visuals = _resolve(colors, state, disabled: disabled);
        Widget content = Row(
          mainAxisSize: expand ? MainAxisSize.max : MainAxisSize.min,
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            if (icon != null && !(loading && variant == EmberButtonVariant.text)) ...[
              Icon(icon, size: tokens.sizeIcon20, color: visuals.foreground),
              SizedBox(width: tokens.space8),
            ],
            if (loading && variant == EmberButtonVariant.text)
              _spinner(visuals.foreground)
            else
              Flexible(
                child: Text(
                  label,
                  style: labelStyle.copyWith(color: visuals.foreground),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            if (loading && variant != EmberButtonVariant.text) ...[
              SizedBox(width: tokens.space8),
              _spinner(visuals.foreground),
            ],
          ],
        );

        final body = Container(
          height: tokens.sizeControlHeight,
          padding: EdgeInsets.symmetric(horizontal: tokens.space24),
          decoration: BoxDecoration(
            color: visuals.background,
            borderRadius: radius,
            border: visuals.border,
          ),
          child: Center(widthFactor: expand ? null : 1, child: content),
        );

        // 光晕只属于主按钮,且按下时降到 50%(§8.3);禁用态没有光晕(loading 有)。
        final glow = switch (variant) {
          EmberButtonVariant.primary =>
            disabled ? null : (state.pressed ? 0.06 : 0.12),
          _ => null,
        };
        if (glow == null) return body;
        return EmberGlow(
          opacity: glow,
          spread: tokens.space4,
          borderRadius: radius,
          child: body,
        );
      },
    );
  }

  Widget _spinner(Color color) => SizedBox(
        width: tokens.sizeIcon16,
        height: tokens.sizeIcon16,
        child: CircularProgressIndicator(strokeWidth: 2, color: color),
      );

  /// 按形态 + 状态解析底色 / 描边 / 前景色(§8.3 的按钮表)。
  _ButtonVisuals _resolve(
    EmberColors colors,
    EmberPressState state, {
    required bool disabled,
  }) {
    return switch (variant) {
      EmberButtonVariant.primary => _ButtonVisuals(
          background: disabled ? colors.surfaceSunken : colors.brandDefault,
          foreground: disabled ? colors.textTertiary : colors.brandOn,
        ),
      EmberButtonVariant.secondary => _ButtonVisuals(
          background: state.pressed || disabled ? colors.surfaceSunken : colors.surfaceCard,
          foreground: disabled ? colors.textTertiary : colors.textPrimary,
          border: disabled
              ? Border.all(color: colors.surfaceSunken)
              : Border.all(color: colors.borderDivider),
        ),
      EmberButtonVariant.text => _ButtonVisuals(
          background: state.pressed && !disabled ? colors.surfaceSunken : Colors.transparent,
          foreground: disabled ? colors.textTertiary : colors.brandDefault,
        ),
      // 危险按钮的实底只在「按下」出现(§8.3:实底仅限二次确认之后,本组件承担
      // 的是按下这一瞬的反馈;真正的确认流程由调用方用 Dialog 保证)。
      EmberButtonVariant.danger => _ButtonVisuals(
          background: disabled
              ? colors.surfaceSunken
              : (state.pressed ? colors.statusDanger : Colors.transparent),
          foreground: disabled
              ? colors.textTertiary
              : (state.pressed ? colors.statusOnDanger : colors.statusDanger),
          border: disabled
              ? Border.all(color: colors.surfaceSunken)
              : Border.all(color: colors.statusDanger),
        ),
    };
  }
}

/// 一次状态解析的结果(底色 / 前景 / 描边)。
@immutable
class _ButtonVisuals {
  const _ButtonVisuals({
    required this.background,
    required this.foreground,
    this.border,
  });

  final Color background;
  final Color foreground;
  final BoxBorder? border;
}
