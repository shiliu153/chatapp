import 'package:flutter/material.dart';
import 'package:phosphor_glyphs/phosphor_glyphs.dart';

import '../../../core/theme/app_typography.dart';
import '../../../core/theme/ember_theme_context.dart';
import '../../../core/theme/tokens.g.dart' as tokens;

/// 录音浮层:显示已录秒数与「松开发送 / 上滑取消」提示。
///
/// 视觉按 §8.3 Toast 的浮层口径取 `overlay.scrim` + `radius.md`(浮层只有这两档,
/// 不另造);前景用纯白 —— 与 `ToastPill` 同源,深色遮罩上两种模式都过线。
class VoiceRecordOverlay extends StatelessWidget {
  /// 构造浮层。
  const VoiceRecordOverlay({
    super.key,
    required this.seconds,
    required this.cancelArmed,
  });

  /// 已录秒数(向上取整)。
  final int seconds;

  /// 手指已上滑到取消区。
  final bool cancelArmed;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    return Container(
      key: const Key('voice.overlay'),
      padding: EdgeInsets.symmetric(
        horizontal: tokens.space16,
        vertical: tokens.space12,
      ),
      decoration: BoxDecoration(
        color: colors.overlayScrim,
        borderRadius: BorderRadius.circular(tokens.radiusMd),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(
            cancelArmed ? PhosphorIconsRegular.trash : PhosphorIconsRegular.microphone,
            color: cancelArmed ? colors.statusDanger : Colors.white,
            size: tokens.sizeIcon24,
          ),
          SizedBox(height: tokens.space4),
          Text('$seconds″', style: AppText.title.copyWith(color: Colors.white)),
          SizedBox(height: tokens.space4),
          Text(
            cancelArmed ? '松开取消' : '松开发送,上滑取消',
            style: AppText.micro.copyWith(color: Colors.white70),
          ),
        ],
      ),
    );
  }
}
