import 'package:flutter/material.dart';

import '../theme/app_gradients.dart';
import '../theme/app_motion.dart';
import '../theme/app_spacing.dart';
import '../theme/heart_theme_context.dart';

/// 「心跳」分段进度(引导页用):高 4 胶囊,已过段 `gradientHeart`,未过段 `divider`。
/// 第 `i` 段填充当且仅当 `i <= current`(current 为 0 基的当前步骤)。
class AppProgressBar extends StatelessWidget {
  const AppProgressBar({super.key, required this.steps, required this.current});

  final int steps;
  final int current;

  static const height = 4.0;

  @override
  Widget build(BuildContext context) {
    final colors = context.heart;
    return Row(
        children: [
          for (var i = 0; i < steps; i++) ...[
            if (i > 0) const SizedBox(width: AppSpacing.xs),
            Expanded(
              child: AnimatedContainer(
                duration: AppMotion.base,
                height: height,
                decoration: BoxDecoration(
                  gradient: i <= current ? AppGradients.heartOf(colors) : null,
                  color: i <= current ? null : colors.divider,
                  borderRadius: BorderRadius.circular(height / 2),
                ),
              ),
            ),
          ],
        ],
      );
  }
}
