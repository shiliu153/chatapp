import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../../../core/theme/app_typography.dart';
import '../../../core/theme/ember_colors.dart';
import '../../../core/theme/ember_theme_context.dart';

/// 资料完善度环(E-5.4 page spec §3 / 上游 §18.5)。
///
/// 底环 3px `border.divider` + 进度弧 3px `brand.default` + 中央 `done/total`。
///
/// **不再用渐变弧**:心跳期(`AppGradients.heartSweepOf`)是「唯一的渐变高音」,
/// 而 Ember §18.5 把渐变主视觉整体作废 —— 单一强调色只出现在引导视线处,
/// 这里就用 `brand.default` 实色。深色下 `brand.default` 自动翻成浅朱砂(§3.3),
/// 不需要第二套取值。
class CompletionRing extends StatelessWidget {
  /// 构造完成度环。
  const CompletionRing({
    super.key,
    required this.done,
    required this.total,
    this.size = 44,
  });

  /// 已完成项数。
  final int done;

  /// 总项数。
  final int total;

  /// 直径。
  final double size;

  /// 环宽 3px(规范未覆盖,**保留现形态**)。
  static const _stroke = 3.0;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    // total=0 时不画弧,避免除零
    final progress = total <= 0 ? 0.0 : (done / total).clamp(0.0, 1.0);
    return Semantics(
      container: true,
      label: '资料完成度，$done/$total',
      child: ExcludeSemantics(
        child: SizedBox.square(
          key: const Key('my.ring'),
          dimension: size,
          child: Stack(
            alignment: Alignment.center,
            children: [
              CustomPaint(
                size: Size.square(size),
                painter:
                    _RingPainter(progress: progress, stroke: _stroke, colors: colors),
              ),
              Text('$done/$total', style: AppText.micro.copyWith(color: colors.textPrimary)),
            ],
          ),
        ),
      ),
    );
  }
}

/// 画底环与进度弧;自绘发生在 paint 阶段(拿不到 BuildContext),色板由外部注入。
class _RingPainter extends CustomPainter {
  /// 构造画笔。
  _RingPainter({
    required this.progress,
    required this.stroke,
    required this.colors,
  });

  /// 进度 0–1。
  final double progress;

  /// 环宽。
  final double stroke;

  /// 语义色板(由 widget 从 `context.ember` 取好传进来)。
  final EmberColors colors;

  @override
  void paint(Canvas canvas, Size size) {
    final rect =
        Rect.fromLTWH(stroke / 2, stroke / 2, size.width - stroke, size.height - stroke);
    final base = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = stroke
      ..color = colors.borderDivider;
    canvas.drawArc(rect, 0, math.pi * 2, false, base);

    if (progress <= 0) return;
    final arc = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = stroke
      ..strokeCap = StrokeCap.round
      ..color = colors.brandDefault;
    // 从 12 点方向起画,顺时针
    canvas.drawArc(rect, -math.pi / 2, math.pi * 2 * progress, false, arc);
  }

  @override
  bool shouldRepaint(_RingPainter old) =>
      old.progress != progress || old.stroke != stroke || old.colors != colors;
}
