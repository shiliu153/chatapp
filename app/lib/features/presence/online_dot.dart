import 'package:flutter/material.dart';

/// 头像右下角的在线绿点(白描边);离线时由调用方决定不渲染。
class OnlineDot extends StatelessWidget {
  const OnlineDot({super.key, this.size = 12});

  final double size;

  @override
  Widget build(BuildContext context) => Container(
        width: size,
        height: size,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: const Color(0xFF34C759),
          border: Border.all(color: Colors.white, width: 2),
        ),
      );
}
