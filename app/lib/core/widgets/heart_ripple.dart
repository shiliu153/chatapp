import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_gradients.dart';
import '../theme/app_motion.dart';

/// 「心跳」规则附录 A.3 涟漪空态元素:中心渐变光点 + 双波循环扩散环
/// (自光点处诞生、扩大渐隐,无静态环)。波纹 2.4s 循环;
/// 「减弱动态效果」时仅剩光点。
/// 无限动画:处于可见状态的测试只用有限 pump,禁 pumpAndSettle。
class HeartRipple extends StatefulWidget {
  const HeartRipple({super.key, this.size = 180});

  final double size;

  @override
  State<HeartRipple> createState() => _HeartRippleState();
}

class _HeartRippleState extends State<HeartRipple> with SingleTickerProviderStateMixin {
  /// 中心光点固定尺寸:不随 [HeartRipple.size] 缩放(手测观感)。
  static const _dotSize = 14.0;

  late final AnimationController _c =
      AnimationController(vsync: this, duration: AppMotion.loop * 2);

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (MediaQuery.disableAnimationsOf(context)) {
      _c.stop();
    } else if (!_c.isAnimating) {
      _c.repeat();
    }
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final size = widget.size;
    final animate = !MediaQuery.disableAnimationsOf(context);
    return SizedBox.square(
      dimension: size,
      child: Stack(
        alignment: Alignment.center,
        children: [
          if (animate) ...[
            _ping(0, 0),
            _ping(1, 0.5),
          ],
          Container(
            width: _dotSize,
            height: _dotSize,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              gradient: AppGradients.heart,
              boxShadow: [
                BoxShadow(color: AppColors.brand.withValues(alpha: 0.65), blurRadius: 16),
              ],
            ),
          ),
        ],
      ),
    );
  }

  /// 一圈扩散波纹:0.2 → 1.0 倍尺寸(自光点溢出),不透明度 .65 → 0;phase 用于双波错峰。
  Widget _ping(int index, double phase) => AnimatedBuilder(
        animation: _c,
        builder: (context, child) {
          final t = (_c.value + phase) % 1.0;
          final scale = 0.2 + 0.8 * Curves.easeOutCubic.transform(t);
          return Opacity(
            opacity: (1 - t) * 0.65,
            child: SizedBox(
              key: Key('ripple.ping$index'),
              width: widget.size * scale,
              height: widget.size * scale,
              child: child,
            ),
          );
        },
        child: DecoratedBox(
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            border: Border.all(color: AppColors.brand, width: 2),
          ),
        ),
      );
}
