import 'package:flutter/material.dart';

/// 「心跳」规则 §6.1 时长/曲线。
abstract final class AppMotion {
  static const fast = Duration(milliseconds: 150);
  static const base = Duration(milliseconds: 220);
  static const medium = Duration(milliseconds: 320);
  static const hero = Duration(milliseconds: 380);
  static const cinematic = Duration(milliseconds: 1200); // 900–1400 取中值
  static const loop = Duration(milliseconds: 1200); // 呼吸循环
  static const easeOut = Curves.easeOutCubic;
  static const easeOutBack = Curves.easeOutBack;
}
