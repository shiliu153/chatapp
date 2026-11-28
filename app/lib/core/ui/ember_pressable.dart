import 'package:flutter/material.dart';
import 'package:flutter/physics.dart';

import '../theme/ember_colors.dart';
import '../theme/ember_motion.dart';
import '../theme/ember_theme_context.dart';
import '../theme/tokens.g.dart' as tokens;

/// 按压 / 聚焦 / 语义三件事的公共外壳(spec §7.2 微交互 + §8.4 无障碍)。
///
/// 为什么单独抽一层:§8.3 要求每个可点组件的 `pressed` 都用**弹簧**缩到 .97
/// (卡片 .98),而弹簧要用 [AnimationController.animateWith] + [SpringSimulation],
/// 每个组件各写一遍必然走味;焦点环(§8.4「2px brand + 2px 间隙」)同理。
///
/// 三个状态通过 [builder] 回传,组件据此改底色 / 光晕 —— 状态取值表是验收尺子,
/// 状态本身不能藏在私有实现里:
///
/// ```dart
/// EmberPressable(
///   onTap: onTap,
///   builder: (context, state) => ColoredBox(
///     color: state.pressed ? colors.surfaceSunken : colors.surfaceCard,
///     child: Text(label),
///   ),
/// )
/// ```
///
/// 减弱动态效果(§7.3 / §8.4)时**不缩放**,直接取终态。
class EmberPressable extends StatefulWidget {
  const EmberPressable({
    super.key,
    required this.builder,
    this.onTap,
    this.onLongPress,
    this.enabled = true,
    this.pressedScale = 0.97,
    this.borderRadius,
    this.semanticLabel,
    this.excludeChildSemantics = false,
    this.semanticButton = true,
    this.autofocus = false,
    this.focusNode,
    this.focusColor,
  });

  /// 内容构造器;拿到当前 pressed / focused / hovered 三态。
  final Widget Function(BuildContext context, EmberPressState state) builder;

  /// 点击回调;`null` 表示不可点(disabled)。
  final VoidCallback? onTap;

  /// 长按回调。
  final VoidCallback? onLongPress;

  /// 是否可交互。`onTap == null` 时自动为 false。
  final bool enabled;

  /// 按下时的缩放比例(按钮 .97 / 卡片 .98)。
  final double pressedScale;

  /// 焦点环与点击水波的形状;`null` 表示直角。
  final BorderRadius? borderRadius;

  /// 读屏播报用的标签(图标按钮必须有,§8.4)。`null` 时不额外包一层 Semantics。
  final String? semanticLabel;

  /// 给了 [semanticLabel] 时,是否**丢弃子节点的语义**。
  ///
  /// 只在「标签就是子节点里那句可见文字」时传 `true`(`EmberButton` 就是这种):
  /// 否则同一句话会被念两遍 —— 外层 `Semantics(label:)` 一份、内层 `Text` 又一份,
  /// 读屏上是「退出登录 + 换行 + 退出登录」(2026-11-28 真机实测,#513)。
  ///
  /// **内容比标签更丰富的场景必须保持 `false`**(例如通知行:标签只写标题与计数,
  /// 日期与正文由子节点给)。那种情况正确的做法是让页面把完整信息拼进 [semanticLabel],
  /// 而不是把子节点语义丢掉。
  final bool excludeChildSemantics;

  /// 是否按「按钮」播报(卡片应传 false)。
  final bool semanticButton;

  /// 是否自动取得焦点(键盘用户从外部 Tab 进来)。
  final bool autofocus;

  /// 外部可控焦点(测试与表单联动用)。
  final FocusNode? focusNode;

  /// 焦点环颜色;`null` 取 `brand.default`(危险按钮按 §8.3 改用 `status.danger`)。
  final Color? focusColor;

  @override
  State<EmberPressable> createState() => _EmberPressableState();
}

/// [EmberPressable] 回传给 builder 的状态三元组。
@immutable
class EmberPressState {
  const EmberPressState({
    required this.pressed,
    required this.focused,
    required this.hovered,
    required this.enabled,
  });

  /// 手指/鼠标按住。
  final bool pressed;

  /// 键盘焦点高亮(§8.4 禁止去掉焦点环)。
  final bool focused;

  /// 指针悬停(桌面端;移动端恒为 false)。
  final bool hovered;

  /// 是否可交互。
  final bool enabled;
}

class _EmberPressableState extends State<EmberPressable>
    with SingleTickerProviderStateMixin {
  late final AnimationController _scale =
      AnimationController(vsync: this, value: 1, duration: const Duration(milliseconds: 1));

  var _pressed = false;
  var _hovered = false;
  var _focused = false;

  bool get _enabled => widget.enabled && widget.onTap != null;

  @override
  void dispose() {
    _scale.dispose();
    super.dispose();
  }

  /// 用 spring 把缩放推到 [target](§7.1 `spring.fast`);减弱动态效果时取终态。
  void _animateTo(double target) {
    if (EmberMotion.reducedOf(context)) {
      _scale.value = target;
      return;
    }
    _scale.animateWith(
      SpringSimulation(EmberMotion.fast, _scale.value, target, _scale.velocity),
    );
  }

  void _setPressed(bool pressed) {
    if (!_enabled) return;
    setState(() => _pressed = pressed);
    _animateTo(pressed ? widget.pressedScale : 1);
  }

  @override
  Widget build(BuildContext context) {
    final state = EmberPressState(
      pressed: _pressed,
      focused: _focused,
      hovered: _hovered,
      enabled: _enabled,
    );

    Widget content = AnimatedBuilder(
      animation: _scale,
      builder: (context, child) => Transform.scale(scale: _scale.value, child: child),
      child: widget.builder(context, state),
    );

    if (state.focused) {
      content = EmberFocusRing(
        borderRadius: widget.borderRadius,
        color: widget.focusColor,
        child: content,
      );
    }

    content = MouseRegion(
      cursor: _enabled ? SystemMouseCursors.click : SystemMouseCursors.basic,
      onEnter: (_) => setState(() => _hovered = true),
      onExit: (_) => setState(() => _hovered = false),
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTapDown: (_) => _setPressed(true),
        onTapUp: (_) => _setPressed(false),
        onTapCancel: () => _setPressed(false),
        onTap: _enabled ? widget.onTap : null,
        onLongPress: _enabled ? widget.onLongPress : null,
        child: content,
      ),
    );

    content = FocusableActionDetector(
      enabled: _enabled,
      autofocus: widget.autofocus,
      focusNode: widget.focusNode,
      // 用 onFocusChange 而不是 onShowFocusHighlight:后者只在「键盘高亮模式」下触发,
      // 而高亮模式由最近一次输入设备决定,会让同一个组件在鼠标/键盘之间行为不一致。
      onFocusChange: (value) => setState(() => _focused = value),
      actions: {
        ActivateIntent: CallbackAction<ActivateIntent>(
          onInvoke: (_) {
            widget.onTap?.call();
            return null;
          },
        ),
      },
      child: content,
    );

    final label = widget.semanticLabel;
    if (label == null) return content;
    return Semantics(
      container: true,
      button: widget.semanticButton,
      enabled: _enabled,
      label: label,
      // `true` 时外层标签是唯一事实:子节点的 `Text` 不再贡献第二份同名标签(#513)。
      // **但排除子语义会连 `GestureDetector` 贡献的 tap action 一起丢掉** ——
      // 那样读屏只能念、点不动(2026-11-28 实测 `clickable` 从 true 变 false),
      // 所以必须由这一层自己补上 onTap。
      excludeSemantics: widget.excludeChildSemantics,
      onTap: widget.excludeChildSemantics && _enabled ? widget.onTap : null,
      child: content,
    );
  }
}

/// 焦点环:2px `brand.default` + 2px 间隙(spec §8.3 / §8.4)。
///
/// 画法是把环放在内容**外侧 4px** 的 Stack 上:环本身 2px 宽,于是环内缘与内容之间
/// 正好留出 2px 间隙,且不占布局空间(不会让按钮在聚焦时抖一下)。
class EmberFocusRing extends StatelessWidget {
  const EmberFocusRing({
    super.key,
    required this.child,
    this.borderRadius,
    this.color,
  });

  /// 被包住的内容。
  final Widget child;

  /// 环的形状;`null` 表示直角。
  final BorderRadius? borderRadius;

  /// 环颜色;`null` 取 `brand.default`。
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    return Stack(
      clipBehavior: Clip.none,
      children: [
        child,
        Positioned(
          left: -4,
          top: -4,
          right: -4,
          bottom: -4,
          child: IgnorePointer(
            child: DecoratedBox(
              decoration: BoxDecoration(
                borderRadius: (borderRadius ??
                        BorderRadius.circular(tokens.radiusSm))
                    .add(const BorderRadius.all(Radius.circular(4))),
                border: Border.all(
                  color: color ?? colors.brandDefault,
                  width: 2,
                ),
              ),
            ),
          ),
        ),
      ],
    );
  }
}

/// 把 [EmberColors] 转成 `BorderRadius`(统一取 token 的圆角档位)。
BorderRadius emberRadius(double radius) => BorderRadius.circular(radius);
