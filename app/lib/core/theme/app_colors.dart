import 'package:flutter/material.dart';

/// 「心跳」规则 §2.1 色板。新代码禁止裸 hex,一律从这里取。
abstract final class AppColors {
  static const brand = Color(0xFFFF2C55);
  static const violet = Color(0xFF7C5CFF);
  static const green = Color(0xFF12C48B);
  static const amber = Color(0xFFFFB020);
  static const text1 = Color(0xFF16181D);
  static const text2 = Color(0xFF8A8F9E);
  static const text3 = Color(0xFFB3B7C0);
  static const divider = Color(0xFFEEF0F4);
  static const bgPage = Color(0xFFF6F7FB);
  static const bgCard = Color(0xFFFFFFFF);
  static const danger = Color(0xFFFA5151);
  static const success = green;
  static const warning = amber;
  static const heartOrange = Color(0xFFFF7A45); // 渐变终点(§2.2 可微调)
  static const systemBlue = Color(0xFF4F8CFF);

  /// 照片叠字 scrim:发现卡底部渐变终点 rgba(16,17,20,.87),起点用 Colors.transparent(附录 A.2)。
  static const photoScrim = Color(0xDE101114);
}
