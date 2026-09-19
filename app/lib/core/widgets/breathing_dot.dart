import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_motion.dart';

/// 在线点:green + 呼吸光晕(§5.3/§4);描边色 = 所在背景色。
/// 无限动画:处于可见状态的测试只用有限 pump,禁 pumpAndSettle。
class BreathingDot extends StatefulWidget {
  const BreathingDot({
    super.key,
    this.size = 11,
    this.borderColor = Colors.white,
  });

  final double size;
  final Color borderColor;

  @override
  State<BreathingDot> createState() => _BreathingDotState();
}

class _BreathingDotState extends State<BreathingDot> with SingleTickerProviderStateMixin {
  late final AnimationController _c =
      AnimationController(vsync: this, duration: AppMotion.loop)..repeat(reverse: true);

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
        animation: _c,
        builder: (context, _) => Opacity(
          opacity: 0.55 + 0.45 * _c.value, // 呼吸:透明度 .55↔1
          child: Container(
            width: widget.size,
            height: widget.size,
            decoration: BoxDecoration(
              color: AppColors.green,
              shape: BoxShape.circle,
              border: Border.all(color: widget.borderColor, width: 2),
            ),
          ),
        ),
      );
}
