import 'package:flutter/material.dart';

import '../theme/ember_theme_context.dart';
import '../theme/tokens.g.dart' as tokens;
import 'ember_button.dart';
import 'ember_component_sizes.dart';

/// 空态 / 错误态:插画 72–96 + 标题 17/w600 + 说明 13 `text.secondary` + 可选主按钮
/// (spec §8.3)。
///
/// **禁止灰色图标占位**(§6 / §8.3):所以 [illustration] 是必填的,而且不接受
/// `IconData` —— 逼调用方拿一张插画(unDraw 改主色)或暖色几何体,而不是顺手塞个
/// `Icons.inbox` 灰色图标。
class EmberEmpty extends StatelessWidget {
  /// 构造空态。
  const EmberEmpty({
    super.key,
    required this.illustration,
    required this.title,
    this.description,
    this.actionLabel,
    this.onAction,
  });

  /// 插画(尺寸建议落在 72–96 之间,由调用方按内容选)。
  final Widget illustration;

  /// 标题(17/w600)。
  final String title;

  /// 说明(13/`text.secondary`)。
  final String? description;

  /// 主按钮文案;与 [onAction] 同时给出才渲染。
  final String? actionLabel;

  /// 主按钮回调。
  final VoidCallback? onAction;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    final hasAction = actionLabel != null && onAction != null;
    return Semantics(
      // 空态本身不是一个可操作控件,但要把标题 + 说明读出来(§8.4「读屏播报」)。
      container: true,
      label: [title, ?description].join('，'),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          ConstrainedBox(
            constraints: const BoxConstraints(
              minWidth: EmberComponentSizes.illustrationMin,
              minHeight: EmberComponentSizes.illustrationMin,
              maxWidth: EmberComponentSizes.illustrationMax,
              maxHeight: EmberComponentSizes.illustrationMax,
            ),
            child: Center(child: illustration),
          ),
          SizedBox(height: tokens.space20),
          Text(
            title,
            textAlign: TextAlign.center,
            style: TextStyle(
              fontSize: tokens.fontSizeSubtitle,
              fontWeight: FontWeight.w600,
              height: tokens.fontLineHeightSubtitle,
              color: colors.textPrimary,
            ),
          ),
          if (description != null) ...[
            SizedBox(height: tokens.space8),
            Text(
              description!,
              textAlign: TextAlign.center,
              style: TextStyle(
                fontSize: tokens.fontSizeCaption,
                height: tokens.fontLineHeightCaption,
                color: colors.textSecondary,
              ),
            ),
          ],
          if (hasAction) ...[
            SizedBox(height: tokens.space24),
            EmberButton(label: actionLabel!, onPressed: onAction),
          ],
        ],
      ),
    );
  }
}
