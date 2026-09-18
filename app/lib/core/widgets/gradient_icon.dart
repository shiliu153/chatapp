import 'package:flutter/material.dart';

import '../theme/app_gradients.dart';

/// ShaderMask 渐变着色图标(「心跳」规则 §4 选中态)。
class GradientIcon extends StatelessWidget {
  const GradientIcon(this.icon, {super.key, this.size = 22, this.gradient = AppGradients.heart});

  final IconData icon;
  final double size;
  final Gradient gradient;

  @override
  Widget build(BuildContext context) => ShaderMask(
        blendMode: BlendMode.srcIn,
        shaderCallback: (rect) => gradient.createShader(rect),
        child: Icon(icon, size: size, color: Colors.white),
      );
}
