import 'dart:ui' as ui;

import 'package:flutter/material.dart';

import '../../../core/theme/app_colors.dart';

/// 「心跳」附录 B.6 空态插画:渐变大气泡 + 白色小气泡(各带小尾),静态。
/// 消息页/聊天页空态的大号元素;发现页的 HeartRipple 仍归发现页。
class ChatBubblesMark extends StatelessWidget {
  const ChatBubblesMark({super.key, this.size = 118});

  final double size;

  @override
  Widget build(BuildContext context) => SizedBox(
        width: size,
        height: size * 0.88,
        child: CustomPaint(painter: _BubblesPainter()),
      );
}

class _BubblesPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final w = size.width;
    final h = size.height;

    // 白色小气泡(右上,先画、被渐变气泡压住一角)
    final back = RRect.fromRectAndRadius(
      Rect.fromLTWH(w * 0.36, 0, w * 0.62, h * 0.52),
      Radius.circular(w * 0.14),
    );
    final white = Paint()..color = AppColors.bgCard;
    final backTail = Path()
      ..moveTo(w * 0.86, h * 0.44)
      ..lineTo(w * 0.97, h * 0.60)
      ..lineTo(w * 0.78, h * 0.54)
      ..close();
    canvas.drawPath(backTail, white);
    canvas.drawRRect(back, white);
    canvas.drawRRect(
      back,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1
        ..color = AppColors.divider,
    );

    // 渐变大气泡(左下)
    final frontRect = Rect.fromLTWH(0, h * 0.36, w * 0.76, h * 0.60);
    final front = RRect.fromRectAndRadius(frontRect, Radius.circular(w * 0.17));
    final heart = Paint()
      ..shader = ui.Gradient.linear(
        frontRect.topLeft,
        frontRect.bottomRight,
        const [AppColors.brand, AppColors.heartOrange],
      );
    final frontTail = Path()
      ..moveTo(w * 0.20, h * 0.90)
      ..lineTo(w * 0.09, h)
      ..lineTo(w * 0.34, h * 0.955)
      ..close();
    canvas.drawPath(frontTail, heart);
    canvas.drawRRect(front, heart);
  }

  @override
  bool shouldRepaint(covariant _BubblesPainter oldDelegate) => false;
}
