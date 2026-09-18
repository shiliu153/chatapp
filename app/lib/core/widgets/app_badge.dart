import 'package:flutter/material.dart';

import '../theme/app_gradients.dart';
import '../theme/app_shadows.dart';
import '../theme/app_typography.dart';

/// 「心跳」规则 §7 角标:渐变胶囊;min 18×18;≥100 → 99+。
class AppBadge extends StatelessWidget {
  const AppBadge({super.key, required this.count});

  final int count;

  @override
  Widget build(BuildContext context) {
    if (count <= 0) return const SizedBox.shrink();
    return Container(
      constraints: const BoxConstraints(minWidth: 18, minHeight: 18),
      padding: const EdgeInsets.symmetric(horizontal: 5),
      alignment: Alignment.center,
      decoration: BoxDecoration(
        gradient: AppGradients.heart,
        borderRadius: BorderRadius.circular(9),
        boxShadow: AppShadows.primaryButton,
      ),
      child: Text(
        count >= 100 ? '99+' : '$count',
        style: AppText.badge.copyWith(color: Colors.white),
      ),
    );
  }
}
