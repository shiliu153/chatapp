import 'package:flutter/material.dart';

import '../theme/ember_motion.dart';
import '../theme/ember_theme_context.dart';
import '../theme/tokens.g.dart' as tokens;

/// 骨架屏色块:底色 `surface.sunken`,透明度 .5↔1,1.2s 循环(spec §8.3)。
///
/// 「1.2s 循环」是规范里**唯一允许的循环动画**之一(另一处是在线点呼吸,§7.3),
/// 所以它不做「可打断」那套;但减弱动态效果时必须静止(§8.4)。
class EmberSkeleton extends StatefulWidget {
  /// 构造骨架块。
  const EmberSkeleton({
    super.key,
    this.width = double.infinity,
    this.height = tokens.fontSizeCaption,
    this.radius = tokens.radiusXs,
    this.shape = BoxShape.rectangle,
  });

  /// 宽度;默认撑满。
  final double width;

  /// 高度。
  final double height;

  /// 圆角(圆形头像骨架传 [shape] = circle 时忽略)。
  final double radius;

  /// 形状。
  final BoxShape shape;

  @override
  State<EmberSkeleton> createState() => _EmberSkeletonState();
}

class _EmberSkeletonState extends State<EmberSkeleton>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller = AnimationController(
    vsync: this,
    duration: EmberMotion.loop,
  );

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    // 减弱动态效果:不呼吸,固定在中值(§8.4「全部 spring 换 120ms 淡入、取消位移」)。
    if (EmberMotion.reducedOf(context)) {
      if (_controller.isAnimating) _controller.stop();
      _controller.value = 0.5;
    } else if (!_controller.isAnimating) {
      _controller.repeat(reverse: true);
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    // 骨架是纯装饰占位:读屏不该念出「色块」,内容区自己的播报交给上层
    // (spec §8.4「纯装饰图形标 `excludeSemantics`」)。
    return ExcludeSemantics(
      child: AnimatedBuilder(
        animation: _controller,
        builder: (context, _) => Opacity(
          opacity: 0.5 + 0.5 * _controller.value,
          child: Container(
            width: widget.width,
            height: widget.height,
            decoration: BoxDecoration(
              color: colors.surfaceSunken,
              shape: widget.shape,
              borderRadius: widget.shape == BoxShape.circle
                  ? null
                  : BorderRadius.circular(widget.radius),
            ),
          ),
        ),
      ),
    );
  }
}
