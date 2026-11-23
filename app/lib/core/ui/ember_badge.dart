import 'package:flutter/material.dart';

import '../theme/ember_theme_context.dart';
import '../theme/tokens.g.dart' as tokens;
import 'ember_component_sizes.dart';

/// 角标:底 `brand.default` + 字 `brand.on` 11/w700 + `radius.pill` + min 18×18,
/// 数字 ≥100 显示「99+」(spec §8.3)。
///
/// 「颜色不是唯一线索」(§8.4)这条在这里的落地方式是**读屏标签**:角标自己带
/// `Semantics(label: '3 条未读')`,不指望颜色把信息传出去。
class EmberBadge extends StatelessWidget {
  /// 构造数字角标。
  const EmberBadge({
    super.key,
    required this.count,
    this.dot = false,
    this.maxCount = 99,
    this.semanticLabel,
  });

  /// 数量;`<= 0` 时整个角标不渲染(未读清零后的常态)。
  final int count;

  /// 是否只画一个圆点(有未读但不想给数字的场景,如「有人在线」)。
  final bool dot;

  /// 超过它就显示「{maxCount}+」。
  final int maxCount;

  /// 覆盖读屏标签;`null` 时按数量自动生成。
  final String? semanticLabel;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    if (count <= 0) return const SizedBox.shrink();

    final label = semanticLabel ?? '$count 条未读';
    if (dot) {
      return Semantics(
        label: label,
        child: Container(
          width: EmberComponentSizes.badgeDot,
          height: EmberComponentSizes.badgeDot,
          decoration: BoxDecoration(
            color: colors.brandDefault,
            shape: BoxShape.circle,
          ),
        ),
      );
    }

    final text = count > maxCount ? '$maxCount+' : '$count';
    return Semantics(
      label: label,
      child: Container(
        constraints: const BoxConstraints(
          minWidth: EmberComponentSizes.badgeMin,
          minHeight: EmberComponentSizes.badgeMin,
        ),
        padding: const EdgeInsets.symmetric(
          horizontal: EmberComponentSizes.badgePadding,
        ),
        decoration: BoxDecoration(
          color: colors.brandDefault,
          borderRadius: BorderRadius.circular(tokens.radiusPill),
        ),
        // 不用 Container.alignment:有界约束下会撑满整格(ListTile trailing 断言)。
        child: Center(
          widthFactor: 1,
          child: Text(
            text,
            // §8.4:`micro` 档**不跟随**系统字号缩放(角标固定,避免撑破容器)。
            textScaler: TextScaler.noScaling,
            style: TextStyle(
              fontSize: tokens.fontSizeMicro,
              fontWeight: FontWeight.w700,
              height: 1.3,
              color: colors.brandOn,
            ),
          ),
        ),
      ),
    );
  }
}
