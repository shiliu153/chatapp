import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_motion.dart';
import '../theme/app_radius.dart';

/// 「心跳」规则 §7 骨架屏:divider 色块,透明度 .5↔1,1.2s 循环。
class AppSkeleton extends StatefulWidget {
  const AppSkeleton({
    super.key,
    this.width = double.infinity,
    this.height = 12,
    this.radius = AppRadius.chip,
  });

  final double width;
  final double height;
  final double radius;

  @override
  State<AppSkeleton> createState() => _AppSkeletonState();
}

class _AppSkeletonState extends State<AppSkeleton> with SingleTickerProviderStateMixin {
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
          opacity: 0.5 + 0.5 * _c.value,
          child: Container(
            width: widget.width,
            height: widget.height,
            decoration: BoxDecoration(
              color: AppColors.divider,
              borderRadius: BorderRadius.circular(widget.radius),
            ),
          ),
        ),
      );
}
