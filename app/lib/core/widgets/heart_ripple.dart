import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_gradients.dart';

/// 「心跳」规则附录 A.3 涟漪空态元素:三圈同心渐变环 + 中心光点。
/// 纯静态(不用动画控制器);空态/引导态的大号彩色元素。
class HeartRipple extends StatelessWidget {
  const HeartRipple({super.key, this.size = 96});

  final double size;

  @override
  Widget build(BuildContext context) {
    final mid = Color.lerp(AppColors.brand, AppColors.heartOrange, 0.5)!;
    return SizedBox.square(
      dimension: size,
      child: Stack(
        alignment: Alignment.center,
        children: [
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

  Widget _ring(double diameter, Color color) => Container(
        width: diameter,
        height: diameter,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          border: Border.all(color: color, width: 2),
        ),
      );
}
