import 'package:flutter/material.dart';

/// 整卡 Hero 包装(§6.2「动态卡 → 动态详情」,附录 D)。
///
/// 与 [AvatarHero] 并列:[tag] 为 null(我的动态/深链,无飞行源)或系统开启
/// 「减弱动态效果」时不包 Hero,静默降级;否则包 [Hero],shuttle 用框架默认
/// (飞行中渲染目标侧 child;两端同为 R20 白卡,无需圆角插值)。
///
/// 纪律(SDK `heroes.dart:412` 硬断言):Hero 的 child 及其后代不得再包含
/// Hero —— 整卡态下卡内头像 Hero 必须让位(调用方保证互斥,见 spec §5)。
class CardHero extends StatelessWidget {
  const CardHero({super.key, required this.tag, required this.child});

  final String? tag;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final heroTag = tag;
    if (heroTag == null || MediaQuery.disableAnimationsOf(context)) return child;
    return Hero(tag: heroTag, child: child);
  }
}
