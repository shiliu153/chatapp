import 'package:flutter/material.dart';

import '../../../core/theme/app_motion.dart';
import '../../../core/theme/app_radius.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/theme/heart_colors.dart';
import '../../../core/theme/heart_theme_context.dart';

/// 发现页加载骨架:与卡面等大的呼吸块 + 操作钮位。
/// 无限动画:可见状态的测试只用有限 pump,禁 pumpAndSettle。
class DeckSkeleton extends StatefulWidget {
  const DeckSkeleton({super.key});

  @override
  State<DeckSkeleton> createState() => _DeckSkeletonState();
}

class _DeckSkeletonState extends State<DeckSkeleton> with SingleTickerProviderStateMixin {
  late final AnimationController _c =
      AnimationController(vsync: this, duration: AppMotion.loop)..repeat(reverse: true);

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.heart;
    return AnimatedBuilder(
        animation: _c,
        builder: (context, _) => Opacity(
          opacity: 0.5 + 0.5 * _c.value,
          child: Column(
            children: [
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(
                      AppSpacing.pageH, AppSpacing.sm, AppSpacing.pageH, 0),
                  child: Container(
                    decoration: BoxDecoration(
                      color: colors.divider,
                      borderRadius: BorderRadius.circular(AppRadius.discoveryCard),
                    ),
                    child: Align(
                      alignment: Alignment.bottomLeft,
                      child: Padding(
                        padding: const EdgeInsets.all(AppSpacing.lg),
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            _bar(0.62, colors),
                            const SizedBox(height: 9),
                            _bar(0.38, colors),
                            const SizedBox(height: 9),
                            _bar(0.84, colors),
                            const SizedBox(height: AppSpacing.md),
                            const Row(children: [_Chip(), SizedBox(width: 6), _Chip()]),
                          ],
                        ),
                      ),
                    ),
                  ),
                ),
              ),
              const SizedBox(
                height: 88,
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    _Circle(44),
                    SizedBox(width: 44),
                    _Circle(44),
                  ],
                ),
              ),
              const SizedBox(height: AppSpacing.lg),
            ],
          ),
        ),
      );
  }

  Widget _bar(double widthFactor, HeartColors colors) => FractionallySizedBox(
        alignment: Alignment.centerLeft,
        widthFactor: widthFactor,
        child: Container(
          height: 10,
          decoration: BoxDecoration(
            color: colors.bgCard.withValues(alpha: 0.75),
            borderRadius: BorderRadius.circular(5),
          ),
        ),
      );
}

class _Chip extends StatelessWidget {
  const _Chip();

  @override
  Widget build(BuildContext context) {
    final colors = context.heart;
    return Container(
        width: 44,
        height: 16,
        decoration: BoxDecoration(
          color: colors.bgCard.withValues(alpha: 0.75),
          borderRadius: BorderRadius.circular(AppRadius.chip),
        ),
      );
  }
}

class _Circle extends StatelessWidget {
  const _Circle(this.size);

  final double size;

  @override
  Widget build(BuildContext context) {
    final colors = context.heart;
    return Container(
        width: size,
        height: size,
        decoration: BoxDecoration(color: colors.divider, shape: BoxShape.circle),
      );
  }
}
