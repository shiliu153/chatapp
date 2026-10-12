import 'package:flutter/material.dart';

import '../theme/app_radius.dart';

/// 「心跳」附录 C.7:Hero 转场包装。
///
/// [tag] 为 null(无来源/深链)或系统开启「减弱动态效果」时**不包 Hero**,
/// 静默降级为普通渲染——两端不同时存在时不会报错。
///
/// [imageUrl] 是飞行途中显示的图。两端取的是**同一张**(后端两侧都取该用户
/// 第一张已过审照片),故对 push/pop 两个方向都正确;为 null 时回退到 child。
class AvatarHero extends StatelessWidget {
  const AvatarHero({
    super.key,
    required this.tag,
    required this.imageUrl,
    required this.child,
    this.fromRadius = AppRadius.chip,
  });

  final String? tag;
  final String? imageUrl;
  final Widget child;

  /// 来源侧圆角;飞行时线性插值到 0(目标是全出血直角头图)。
  final double fromRadius;

  @override
  Widget build(BuildContext context) {
    final heroTag = tag;
    if (heroTag == null || MediaQuery.disableAnimationsOf(context)) return child;
    return Hero(
      tag: heroTag,
      flightShuttleBuilder: (flightContext, animation, direction, fromContext, toContext) {
        // t=0 对应来源(小头像,带圆角),t=1 对应目标(头图,直角)
        final t = direction == HeroFlightDirection.push ? animation.value : 1 - animation.value;
        final url = imageUrl;
        final Widget fallback = direction == HeroFlightDirection.push
            ? (toContext.widget as Hero).child
            : (fromContext.widget as Hero).child;
        final Widget shuttle = (url == null || url.isEmpty)
            ? fallback
            : Image.network(
                url,
                fit: BoxFit.cover,
                errorBuilder: (_, _, _) => fallback,
              );
        return ClipRRect(
          borderRadius: BorderRadius.circular(fromRadius * (1 - t)),
          child: shuttle,
        );
      },
      child: child,
    );
  }
}
