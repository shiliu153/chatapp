import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:phosphor_glyphs/phosphor_glyphs.dart';

import '../../../core/theme/app_typography.dart';
import '../../../core/theme/ember_theme_context.dart';
import '../../../core/theme/tokens.g.dart' as tokens;
import '../../../core/theme/theme_controller.dart';
import '../../../core/ui/ember_ui.dart';

/// 「外观」三选一卡(F-4,E-5.6b 迁移到 Ember):跟随系统 / 浅色 / 深色。
///
/// 为什么不是开关:三态用 `Switch` 表达不了。形态 = 卡片里「图标 + 标题」一行 +
/// 三个 [`EmberChip`](spec §8.3「Chip selected = `brand.default` + `brand.on`」),
/// 三枚等宽铺满,选中靠实底 + 加粗字(§8.4「颜色不是唯一线索」)。
///
/// 读屏:`EmberChip` 自带「跟随系统,已选中」这类标签,本卡不再叠一层语义。
class ThemeModeRow extends ConsumerWidget {
  /// 构造外观卡。
  const ThemeModeRow({super.key});

  /// 三个选项(顺序即界面顺序)。
  static const options = <(ThemeMode, String)>[
    (ThemeMode.system, '跟随系统'),
    (ThemeMode.light, '浅色'),
    (ThemeMode.dark, '深色'),
  ];

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final colors = context.ember;
    final mode = ref.watch(themeModeProvider);
    return EmberCard(
      key: const Key('settings.row.theme'),
      padding: EdgeInsets.symmetric(
        horizontal: tokens.space20,
        vertical: tokens.space16,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                PhosphorIconsRegular.circleHalf,
                size: tokens.sizeIcon20,
                color: colors.textSecondary,
              ),
              SizedBox(width: tokens.space8),
              Text(
                '外观',
                style: AppText.subtitle.copyWith(color: colors.textPrimary),
              ),
            ],
          ),
          SizedBox(height: tokens.space12),
          Row(
            children: [
              for (final (value, label) in options)
                Expanded(
                  child: Padding(
                    // 相邻胶囊之间 8(§5.2 的 4 基数档),首尾不留外距
                    padding: EdgeInsets.only(
                      right: label == options.last.$2 ? 0 : tokens.space8,
                    ),
                    child: EmberChip(
                      label: label,
                      selected: mode == value,
                      onTap: () =>
                          ref.read(themeModeProvider.notifier).setMode(value),
                    ),
                  ),
                ),
            ],
          ),
        ],
      ),
    );
  }
}
