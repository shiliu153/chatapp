import 'package:flutter/material.dart';

import '../theme/ember_theme_context.dart';
import '../theme/tokens.g.dart' as tokens;
import 'ember_component_sizes.dart';

/// 底部弹层:`surface.card` + 上圆角 24 + 顶部拖把 36×4 `border.divider`,
/// 进入用 `spring.gentle`(spec §8.3 Sheet)。
///
/// 层级选择规则(§9.3):单一字段编辑 / 筛选才用 sheet,需要专注完成的流程走独立
/// 二级页,破坏性确认走 Dialog —— 这里只提供形态,选择留给调用方。
abstract final class EmberSheet {
  /// 弹出一个底部弹层,返回它的结果(与 `showModalBottomSheet` 同构)。
  ///
  /// 参数说明:
  /// - [context] 用于取主题与 Navigator。
  /// - [child] 弹层内容。
  /// - [maxHeightRatio] 最高占屏比,§9.3 建议 ≤0.6(筛选、单字段编辑)。
  /// - [dismissible] 是否允许点遮罩 / 下拉关闭(加载中应传 false)。
  static Future<T?> show<T>(
    BuildContext context, {
    required Widget child,
    double maxHeightRatio = 0.6,
    bool dismissible = true,
  }) {
    final colors = context.ember;
    return showModalBottomSheet<T>(
      context: context,
      // scrim 用 overlay.scrim(§8.3),不用 Material 默认黑。
      barrierColor: colors.overlayScrim,
      isDismissible: dismissible,
      enableDrag: dismissible,
      isScrollControlled: true,
      backgroundColor: colors.surfaceCard,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(
          top: Radius.circular(tokens.radiusXl),
        ),
      ),
      builder: (context) => ConstrainedBox(
        constraints: BoxConstraints(
          maxHeight: MediaQuery.sizeOf(context).height * maxHeightRatio,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const EmberSheetHandle(),
            Flexible(child: child),
          ],
        ),
      ),
    );
  }
}

/// 弹层顶部的拖把(36×4,`border.divider`),也给自绘弹层复用。
class EmberSheetHandle extends StatelessWidget {
  /// 构造拖把。
  const EmberSheetHandle({super.key});

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    // 拖把是纯装饰:读屏不该念它(spec §8.4「纯装饰图形标 `excludeSemantics`」)。
    return ExcludeSemantics(
      child: Padding(
        padding: EdgeInsets.symmetric(vertical: tokens.space8),
        child: Container(
          width: EmberComponentSizes.sheetHandleWidth,
          height: EmberComponentSizes.sheetHandleHeight,
          decoration: BoxDecoration(
            color: colors.borderDivider,
            borderRadius: BorderRadius.circular(tokens.radiusPill),
          ),
        ),
      ),
    );
  }
}
