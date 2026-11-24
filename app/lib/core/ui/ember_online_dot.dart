import 'package:flutter/material.dart';

import '../theme/ember_motion.dart';
import '../theme/ember_theme_context.dart';
import 'ember_component_sizes.dart';

/// 在线点:`status.success` 圆点 + 2px 背景色描边 + 呼吸(spec §8.3 头像行)。
///
/// 抽成独立组件的原因:它既要跟在头像右下角([EmberAvatar]),也要单独压在照片
/// 叠字旁(E-5.2 卡面「● 在线」)。两处各写一份呼吸控制器就等于两处循环动画口径。
///
/// 两条纪律:
/// - **呼吸只动透明度、不动尺寸**(尺寸一动,头像环会跟着抖);
/// - 减弱动态效果时停在中间值(§8.4),不呼吸。
///
/// 它是规范允许的**唯二循环动画**之一(另一处是骨架屏,§7.3),所以测试里只能
/// 有限 `pump`,禁 `pumpAndSettle`。
class EmberOnlineDot extends StatefulWidget {
  /// 构造在线点。
  const EmberOnlineDot({
    super.key,
    this.size = EmberComponentSizes.onlineDot,
    required this.background,
  });

  /// 直径:常规 11,小场景 8(§8.3)。
  final double size;

  /// 描边色 = 所在背景色;照片叠字场景传白(与照片同底色不可知,取白保可读性)。
  final Color background;

  @override
  State<EmberOnlineDot> createState() => _EmberOnlineDotState();
}

class _EmberOnlineDotState extends State<EmberOnlineDot>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller = AnimationController(
    vsync: this,
    duration: EmberMotion.loop,
  );

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
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
    return AnimatedBuilder(
      animation: _controller,
      builder: (context, _) => Opacity(
        // 呼吸只动透明度,不动尺寸(尺寸一动,头像环会跟着抖)。
        opacity: 0.6 + 0.4 * _controller.value,
        child: Container(
          width: widget.size,
          height: widget.size,
          decoration: BoxDecoration(
            color: colors.statusSuccess,
            shape: BoxShape.circle,
            border: Border.all(
              color: widget.background,
              width: EmberComponentSizes.onlineDotStroke,
            ),
          ),
        ),
      ),
    );
  }
}
