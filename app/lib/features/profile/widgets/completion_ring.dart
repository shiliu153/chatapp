import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_gradients.dart';
import '../../../core/theme/app_typography.dart';

/// 「心跳」附录 C.2 完成度环:底环 3px divider + 渐变进度弧 3px + 中央 done/total。
/// 它是「我的」页唯一的渐变高音,把视线引到「去完善」。
class CompletionRing extends StatelessWidget {
  const CompletionRing({
    super.key,
    required this.done,
    required this.total,
    this.size = 44,
  });

  final int done;
  final int total;
  final double size;

  static const _stroke = 3.0;

  @override
  Widget build(BuildContext context) {
    // total=0 时不画弧,避免除零
    final progress = total <= 0 ? 0.0 : (done / total).clamp(0.0, 1.0);
    return SizedBox.square(
      key: const Key('my.ring'),
      dimension: size,
      child: Stack(
        alignment: Alignment.center,
        children: [
          CustomPaint(
            size: Size.square(size),
            painter: _RingPainter(progress: progress, stroke: _stroke),
          ),
          Text('$done/$total', style: AppText.micro.copyWith(color: AppColors.text1)),
        ],
      ),
    );
  }
}

class _RingPainter extends CustomPainter {
  const _RingPainter({required this.progress, required this.stroke});

  final double progress;
  final double stroke;

  @override
  void paint(Canvas canvas, Size size) {
    final rect =
        Rect.fromLTWH(stroke / 2, stroke / 2, size.width - stroke, size.height - stroke);
    final base = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = stroke
      ..color = AppColors.divider;
    canvas.drawArc(rect, 0, math.pi * 2, false, base);

    if (progress <= 0) return;
    final arc = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = stroke
      ..strokeCap = StrokeCap.round
      ..shader = AppGradients.heartSweep.createShader(rect);
    // 从 12 点方向起画,顺时针
    canvas.drawArc(rect, -math.pi / 2, math.pi * 2 * progress, false, arc);
  }

  @override
  bool shouldRepaint(_RingPainter old) =>
      old.progress != progress || old.stroke != stroke;
}
