import 'package:flutter/material.dart';

import '../theme/app_gradients.dart';
import '../theme/heart_theme_context.dart';

/// ShaderMask 渐变着色图标(「心跳」规则 §4 选中态)。
///
/// [gradient] 不传时按当前主题的心跳渐变;因为渐变要跟着暗色走,
/// 所以默认值不能写成 `const`(只能给 null,在 build 里解析)。
class GradientIcon extends StatelessWidget {
  const GradientIcon(this.icon, {super.key, this.size = 22, this.gradient});

  final IconData icon;
  final double size;

  /// 覆盖默认的心跳渐变;为 null 时取 `AppGradients.heartOf(context.heart)`。
  final Gradient? gradient;

  @override
  Widget build(BuildContext context) {
    final colors = context.heart;
    final resolved = gradient ?? AppGradients.heartOf(colors);
    return ShaderMask(
      blendMode: BlendMode.srcIn,
      shaderCallback: (rect) => resolved.createShader(rect),
      child: Icon(icon, size: size, color: Colors.white),
    );
  }
}
