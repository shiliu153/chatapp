import 'package:flutter/material.dart';

import '../theme/app_shadows.dart';
import '../theme/ember_theme_context.dart';
import '../theme/tokens.g.dart' as tokens;
import 'ember_component_sizes.dart';
import 'ember_pressable.dart';
import 'ember_skeleton.dart';

/// 卡片:`surface.card` + `radius.lg` + `elev.1` + 内边距 20(可点时按压 `scale .98`);
/// 选中 = 2px `brand.default` 描边(不放大,避免布局跳动)(spec §8.2 / §8.3)。
///
/// **深色模式不用阴影**(§5.3):阴影在深底上不可见,这里改成 `border.divider` 描边 +
/// 表面色差分层 —— 不允许两模式套同一套 boxShadow。
class EmberCard extends StatelessWidget {
  /// 构造卡片。
  const EmberCard({
    super.key,
    required this.child,
    this.onTap,
    this.selected = false,
    this.loading = false,
    this.padding,
    this.semanticsLabel,
  });

  /// 卡片内容。
  final Widget child;

  /// 点击回调;`null` 即静态卡片(§8.1 的「Card(可点/静态)」)。
  final VoidCallback? onTap;

  /// 选中态:2px `brand.default` 描边。
  final bool selected;

  /// 加载态:内容换成骨架,形状按目标内容(§8.3 卡片 loading)。
  final bool loading;

  /// 内边距;默认 `space.20`(§8.3「内边距 20」)。
  final EdgeInsetsGeometry? padding;

  /// 覆盖读屏标签(可点卡片建议给出「整行是一件事」的标签)。
  final String? semanticsLabel;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final radius = BorderRadius.circular(tokens.radiusLg);
    final effectivePadding = padding ?? EdgeInsets.all(tokens.space20);

    final decoration = BoxDecoration(
      color: colors.surfaceCard,
      borderRadius: radius,
      // 深色不用阴影(§5.3),改用描边;浅色才用 elev.1。
      boxShadow: isDark ? null : AppShadows.card,
      border: isDark ? Border.all(color: colors.borderDivider) : null,
    );

    var content = loading
        ? _cardSkeleton(effectivePadding)
        : Padding(padding: effectivePadding, child: child);

    if (selected) {
      // 选中环画成**不占布局**的叠加层:§8.3 明写「不放大,避免布局跳动」,
      // 而 BoxDecoration 的 border 会参与 child 的内边距计算(卡片会胖 4px)。
      content = Stack(
        clipBehavior: Clip.none,
        children: [
          content,
          Positioned.fill(
            child: IgnorePointer(
              child: DecoratedBox(
                decoration: BoxDecoration(
                  borderRadius: radius,
                  border: Border.all(color: colors.brandDefault, width: 2),
                ),
              ),
            ),
          ),
        ],
      );
    }

    if (onTap == null) {
      return DecoratedBox(decoration: decoration, child: content);
    }

    return EmberPressable(
      onTap: onTap,
      pressedScale: EmberComponentSizes.cardPressedScale,
      borderRadius: radius,
      semanticButton: false,
      semanticLabel: semanticsLabel,
      // 按压只改缩放(由 EmberPressable 用 spring 推),底色/描边不变 —— §8.3
      // 明写卡片 pressed 是「scale .98(阴影不变)」。
      builder: (context, state) => DecoratedBox(
        decoration: decoration,
        child: content,
      ),
    );
  }

  /// 卡片 loading 的骨架:三行等宽色块(形状按目标内容的行数与行距)。
  Widget _cardSkeleton(EdgeInsetsGeometry padding) => Padding(
        padding: padding,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            EmberSkeleton(height: tokens.fontSizeSubtitle),
            SizedBox(height: tokens.space12),
            EmberSkeleton(height: tokens.fontSizeBody),
            SizedBox(height: tokens.space8),
            EmberSkeleton(height: tokens.fontSizeBody),
          ],
        ),
      );
}
