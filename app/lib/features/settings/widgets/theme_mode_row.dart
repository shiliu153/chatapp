import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/theme/app_radius.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/theme/app_typography.dart';
import '../../../core/theme/heart_theme_context.dart';
import '../../../core/theme/theme_controller.dart';

/// 「外观」三选一行(F-4):跟随系统 / 浅色 / 深色。
///
/// 为什么不用 Switch:三态用开关表达不了。这里用「标题 + 下方分段控件」的形态,
/// 沿用设置页既有行样式(高 64、左侧图标、标题 text1),分段控件本身走 token。
class ThemeModeRow extends ConsumerWidget {
  const ThemeModeRow({super.key});

  static const options = <(ThemeMode, String)>[
    (ThemeMode.system, '跟随系统'),
    (ThemeMode.light, '浅色'),
    (ThemeMode.dark, '深色'),
  ];

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final colors = context.heart;
    final mode = ref.watch(themeModeProvider);
    return Padding(
      key: const Key('settings.row.theme'),
      padding: const EdgeInsets.fromLTRB(
          AppSpacing.lg, AppSpacing.md, AppSpacing.lg, AppSpacing.md),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(Icons.brightness_6_rounded, size: 20, color: colors.text2),
              const SizedBox(width: AppSpacing.md),
              Text('外观',
                  style: AppText.body.copyWith(
                      color: colors.text1, fontWeight: FontWeight.w600)),
            ],
          ),
          const SizedBox(height: AppSpacing.md),
          Container(
            padding: const EdgeInsets.all(AppSpacing.xs),
            decoration: BoxDecoration(
              color: colors.bgPage,
              borderRadius: BorderRadius.circular(AppRadius.chip),
            ),
            child: Row(
              children: [
                for (final (value, label) in options)
                  Expanded(
                    child: _Segment(
                      label: label,
                      selected: mode == value,
                      onTap: () => ref.read(themeModeProvider.notifier).setMode(value),
                    ),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// 分段控件的一段:选中态用卡片底 + 主色字(与「心跳」§4 选中态一致)。
class _Segment extends StatelessWidget {
  const _Segment({required this.label, required this.selected, required this.onTap});

  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = context.heart;
    return Semantics(
      selected: selected,
      button: true,
      child: GestureDetector(
        onTap: onTap,
        behavior: HitTestBehavior.opaque,
        child: Container(
          height: 36,
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: selected ? colors.bgCard : Colors.transparent,
            borderRadius: BorderRadius.circular(AppRadius.chip),
          ),
          child: Text(
            label,
            style: AppText.body.copyWith(
              color: selected ? colors.brand : colors.text2,
              fontWeight: selected ? FontWeight.w600 : FontWeight.w400,
            ),
          ),
        ),
      ),
    );
  }
}
