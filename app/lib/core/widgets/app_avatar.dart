import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_gradients.dart';
import 'breathing_dot.dart';

/// 「心跳」规则 §5.3 头像:一律圆形;可选光晕环(可聊/新配对)与在线绿点。
/// 尺寸档:28/32/40/48/56/96(自由传入,在线点按 ≥48 取 11、否则 8)。
class AppAvatar extends StatelessWidget {
  const AppAvatar({
    super.key,
    this.imageUrl,
    this.size = 48,
    this.halo = false,
    this.showOnlineDot = false,
    this.dotBorderColor = Colors.white,
  });

  final String? imageUrl;
  final double size;
  final bool halo;
  final bool showOnlineDot;
  final Color dotBorderColor;

  @override
  Widget build(BuildContext context) {
    Widget avatar = ClipOval(
      child: SizedBox.square(
        dimension: size,
        child: imageUrl == null
            ? _placeholder()
            : Image.network(
                imageUrl!,
                fit: BoxFit.cover,
                errorBuilder: (_, _, _) => _placeholder(),
              ),
      ),
    );

    if (halo) {
      avatar = Container(
        padding: const EdgeInsets.all(2.5),
        decoration: const BoxDecoration(shape: BoxShape.circle, gradient: AppGradients.heart),
        child: Container(
          padding: const EdgeInsets.all(2),
          decoration: BoxDecoration(shape: BoxShape.circle, color: dotBorderColor),
          child: avatar,
        ),
      );
    }

    if (showOnlineDot) {
      avatar = Stack(
        clipBehavior: Clip.none,
        children: [
          avatar,
          Positioned(
            right: 0,
            bottom: 0,
            child: BreathingDot(
              key: const Key('avatar.onlineDot'),
              size: size >= 48 ? 11 : 8,
              borderColor: dotBorderColor,
            ),
          ),
        ],
      );
    }
    return avatar;
  }

  Widget _placeholder() => Container(
        color: AppColors.divider,
        child: Center(
          child: Icon(Icons.person_rounded, color: AppColors.text3, size: size * 0.6),
        ),
      );
}
