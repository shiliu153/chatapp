import 'package:flutter/material.dart';

import '../theme/ember_theme_context.dart';

/// 品牌签名元素 `emberGlow`(spec §2):一层极浅的朱砂径向光晕。
///
/// 出现场合只有三处,且**一屏最多一处**:
/// ① 主按钮的按压与聚焦;② 配对成功的扩散光;③「新配对」头像环。
///
/// 两条实现纪律:
/// - 它是**径向光晕**,不是 box-shadow —— 旧的粉色投影(§18.5)已作废,因为投影在
///   深色底上不可见,而光晕在深底上反而更明显;
/// - 透明度口径取 §18.6 的「`brand.default` @12%」,由组件层算、不入 token
///   (规范明确写了「当前由组件层算」)。
class EmberGlow extends StatelessWidget {
  /// 构造一层包住 [child] 的光晕。
  const EmberGlow({
    super.key,
    required this.child,
    this.opacity = 0.12,
    this.spread = 12,
    this.shape = EmberGlowShape.rounded,
    this.borderRadius,
  });

  /// 光晕包住的内容。
  final Widget child;

  /// 光晕最外缘的透明度(§18.6 的 12%;按压态按 §8.3 降到 50%)。
  final double opacity;

  /// 光晕向外扩散的距离(像素)。
  final double spread;

  /// 形状:圆角矩形还是正圆(头像环用圆形)。
  final EmberGlowShape shape;

  /// 圆角半径;`null` 时用 `radius.pill`(按钮口径)。
  final BorderRadius? borderRadius;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    final glow = colors.brandDefault.withValues(alpha: opacity);
    final clear = colors.brandDefault.withValues(alpha: 0);
    return Stack(
      clipBehavior: Clip.none,
      children: [
        child,
        // 光晕画在内容外侧的**负偏移**位置:不参与布局,否则按钮会被撑大
        // (高 52 会变成 52 + 2×spread)。
        Positioned(
          left: -spread,
          top: -spread,
          right: -spread,
          bottom: -spread,
          child: IgnorePointer(
            child: DecoratedBox(
              decoration: BoxDecoration(
                shape: shape == EmberGlowShape.circle
                    ? BoxShape.circle
                    : BoxShape.rectangle,
                borderRadius:
                    shape == EmberGlowShape.circle ? null : borderRadius,
                gradient: RadialGradient(
                  colors: [glow, clear],
                  stops: const [0.55, 1],
                ),
              ),
            ),
          ),
        ),
      ],
    );
  }
}

/// [EmberGlow] 的形状口径。
enum EmberGlowShape {
  /// 圆角矩形(按钮、卡片)。
  rounded,

  /// 正圆(头像环、配对扩散光)。
  circle,
}
