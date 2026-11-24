import 'package:flutter/material.dart';
import 'package:phosphor_glyphs/phosphor_glyphs.dart';

import '../../../core/theme/app_typography.dart';
import '../../../core/theme/ember_theme_context.dart';
import '../../../core/theme/tokens.g.dart' as tokens;
import '../../../core/ui/ember_ui.dart';

/// 「＋」面板里的动作(E-5.3 page spec §3:`更多面板 → EmberSheet`)。
enum MoreSheetAction {
  /// 从相册选图并直接发送。
  image,
}

/// 输入栏「＋」入口拉起的弹层内容:目前只有「相册」,后续入口加在这里。
///
/// 形态由 [EmberSheet] 提供(`surface.card` + 上圆角 24 + 拖把 36×4);本组件只管内容,
/// 选完即 `pop(动作)`,由聊天页执行(心跳期那版是塞在输入栏下方的常驻面板)。
class MoreSheet extends StatelessWidget {
  /// 构造面板。
  const MoreSheet({super.key});

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    return Padding(
      key: const Key('chat.more.panel'),
      padding: EdgeInsets.all(tokens.space20),
      child: Align(
        alignment: Alignment.topLeft,
        child: EmberPressable(
          key: const Key('chat.more.image'),
          onTap: () => Navigator.of(context).pop(MoreSheetAction.image),
          pressedScale: 0.97,
          borderRadius: BorderRadius.circular(tokens.radiusMd),
          semanticLabel: '相册',
          builder: (context, state) => Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(
                width: EmberComponentSizes.actionButtonSmall,
                height: EmberComponentSizes.actionButtonSmall,
                decoration: BoxDecoration(
                  color: colors.surfaceSunken,
                  borderRadius: BorderRadius.circular(tokens.radiusMd),
                ),
                child: Icon(
                  PhosphorIconsRegular.image,
                  size: tokens.sizeIcon24,
                  color: colors.brandDefault,
                ),
              ),
              SizedBox(height: tokens.space8),
              Text(
                '相册',
                style: AppText.caption.copyWith(color: colors.textSecondary),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
