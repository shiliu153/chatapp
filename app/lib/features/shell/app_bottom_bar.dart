import 'package:flutter/material.dart';

import '../../core/theme/app_colors.dart';
import '../../core/theme/app_gradients.dart';
import '../../core/theme/app_motion.dart';
import '../../core/theme/app_shadows.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/theme/app_typography.dart';
import '../../core/widgets/app_badge.dart';

/// 「心跳」规则 §7 悬浮胶囊底栏(4 tab)。几何按 §7:白底 R22 高 64、外距 12/10;
/// 选中=渐变胶囊 68×40 R20 内白图标 20 + 白字 10/w700;未选中=描边图标 22 text3 + 文字 10。
class AppBottomBar extends StatelessWidget {
  const AppBottomBar({
    super.key,
    required this.currentIndex,
    required this.onTap,
    this.unreadCount = 0,
  });

  final int currentIndex;
  final ValueChanged<int> onTap;
  final int unreadCount;

  static const _labels = ['发现', '广场', '消息', '我的'];
  static const _icons = [
    Icons.style_rounded,
    Icons.grid_view_rounded,
    Icons.chat_bubble_rounded,
    Icons.person_rounded,
  ];
  static const _outlines = [
    Icons.style_outlined,
    Icons.grid_view_outlined,
    Icons.chat_bubble_outlined,
    Icons.person_outlined,
  ];
  static const _barHeight = 64.0;
  static const _capsuleWidth = 68.0;
  static const _capsuleHeight = 40.0;
  static const _messageTabIndex = 2;

  @override
  Widget build(BuildContext context) {
    final reduceMotion = MediaQuery.disableAnimationsOf(context);
    final moveDuration = reduceMotion ? Duration.zero : AppMotion.medium;
    final popDuration = reduceMotion ? Duration.zero : AppMotion.base;

    return SafeArea(
      top: false,
      child: Container(
        height: _barHeight,
        margin: const EdgeInsets.fromLTRB(AppSpacing.md, 0, AppSpacing.md, 10), // 底外距 10(§7)
        decoration: BoxDecoration(
          color: AppColors.bgCard,
          borderRadius: BorderRadius.circular(22), // R22(§7)
          boxShadow: AppShadows.floatingBar,
        ),
        child: LayoutBuilder(
          builder: (context, constraints) {
            final slot = constraints.maxWidth / _labels.length;
            return Stack(
              children: [
                AnimatedPositioned(
                  duration: moveDuration,
                  curve: AppMotion.easeOut,
                  left: currentIndex * slot + (slot - _capsuleWidth) / 2,
                  top: (_barHeight - _capsuleHeight) / 2,
                  child: Container(
                    width: _capsuleWidth,
                    height: _capsuleHeight,
                    decoration: BoxDecoration(
                      gradient: AppGradients.heart,
                      borderRadius: BorderRadius.circular(20), // R20(§7)
                    ),
                  ),
                ),
                Row(
                  children: [
                    for (var i = 0; i < _labels.length; i++)
                      Expanded(
                        child: _BarItem(
                          label: _labels[i],
                          icon: _icons[i],
                          outline: _outlines[i],
                          selected: i == currentIndex,
                          popDuration: popDuration,
                          badgeCount: i == _messageTabIndex ? unreadCount : 0,
                          onTap: () => onTap(i),
                        ),
                      ),
                  ],
                ),
              ],
            );
          },
        ),
      ),
    );
  }
}

class _BarItem extends StatelessWidget {
  const _BarItem({
    required this.label,
    required this.icon,
    required this.outline,
    required this.selected,
    required this.popDuration,
    required this.badgeCount,
    required this.onTap,
  });

  final String label;
  final IconData icon;
  final IconData outline;
  final bool selected;
  final Duration popDuration;
  final int badgeCount;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: onTap,
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Stack(
            clipBehavior: Clip.none,
            children: [
              AnimatedScale(
                scale: selected ? 1.1 : 1,
                duration: popDuration,
                curve: AppMotion.easeOutBack,
                child: Icon(
                  selected ? icon : outline,
                  size: selected ? 20 : 22,
                  color: selected ? Colors.white : AppColors.text3,
                ),
              ),
              if (badgeCount > 0)
                Positioned(
                  top: -6,
                  right: -12,
                  child: AppBadge(count: badgeCount),
                ),
            ],
          ),
          const SizedBox(height: AppSpacing.xs),
          Text(
            label,
            style: selected
                ? AppText.navLabelSelected.copyWith(color: Colors.white)
                : AppText.navLabel.copyWith(color: AppColors.text3),
          ),
        ],
      ),
    );
  }
}
