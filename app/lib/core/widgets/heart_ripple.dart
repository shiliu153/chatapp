import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_gradients.dart';
import '../theme/app_motion.dart';

/// 「心跳」规则附录 A.3 涟漪空态元素:三圈同心渐变环 + 中心光点
/// + 循环扩散波纹(双波错峰,自中心扩散渐隐)。
/// 波纹 2.4s 循环;「减弱动态效果」时静止(不渲染波纹)。
/// 无限动画:处于可见状态的测试只用有限 pump,禁 pumpAndSettle。
class HeartRipple extends StatefulWidget {
  const HeartRipple({super.key, this.size = 96});

  final double size;

  @override
  State<HeartRipple> createState() => _HeartRippleState();
}

class _HeartRippleState extends State<HeartRipple> with SingleTickerProviderStateMixin {
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
    final mid = Color.lerp(AppColors.brand, AppColors.heartOrange, 0.5)!;
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
          _ring(size, AppColors.heartOrange.withValues(alpha: 0.30)),
          _ring(size * 0.69, mid.withValues(alpha: 0.55)),
          _ring(size * 0.42, AppColors.brand.withValues(alpha: 0.90)),
          Container(
            width: size * 0.15,
            height: size * 0.15,
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

  /// 一圈扩散波纹:0.35 → 1.2 倍尺寸,不透明度 .55 → 0;phase 用于双波错峰。
  Widget _ping(int index, double phase) => AnimatedBuilder(
        animation: _c,
        builder: (context, child) {
          final t = (_c.value + phase) % 1.0;
          final scale = 0.35 + 0.85 * Curves.easeOutCubic.transform(t);
          return Opacity(
            opacity: (1 - t) * 0.55,
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

  Widget _ring(double diameter, Color color) => Container(
        width: diameter,
        height: diameter,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          border: Border.all(color: color, width: 2),
        ),
      );
}
