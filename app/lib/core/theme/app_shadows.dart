import 'package:flutter/material.dart';

/// 「心跳」规则 §5.1 阴影预设(rgba 已折算为 0x 透明度)。
abstract final class AppShadows {
  static const card = [
    BoxShadow(color: Color(0x0F16181D), offset: Offset(0, 6), blurRadius: 18), // rgba(22,24,29,.06)
  ];
  static const floatingBar = [
    BoxShadow(color: Color(0x1A16181D), offset: Offset(0, 10), blurRadius: 24), // rgba(22,24,29,.10)
  ];
  static const primaryButton = [
    BoxShadow(color: Color(0x59FF2C55), offset: Offset(0, 10), blurRadius: 24), // rgba(255,44,85,.35)
  ];
}
