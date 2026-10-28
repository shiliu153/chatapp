import 'package:flutter/material.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_radius.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/theme/app_typography.dart';

/// 录音浮层:显示已录秒数与「松开发送 / 上滑取消」提示。
class VoiceRecordOverlay extends StatelessWidget {
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
  Widget build(BuildContext context) => Container(
        key: const Key('voice.overlay'),
        padding: const EdgeInsets.symmetric(
            horizontal: AppSpacing.lg, vertical: AppSpacing.md),
        decoration: BoxDecoration(
          color: AppColors.text1.withValues(alpha: 0.86),
          borderRadius: BorderRadius.circular(AppRadius.card),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              cancelArmed ? Icons.delete_rounded : Icons.mic_rounded,
              color: cancelArmed ? AppColors.danger : Colors.white,
              size: 28,
            ),
            const SizedBox(height: AppSpacing.xs),
            Text('$seconds″', style: AppText.title.copyWith(color: Colors.white)),
            const SizedBox(height: AppSpacing.xs),
            Text(
              cancelArmed ? '松开取消' : '松开发送,上滑取消',
              style: AppText.micro.copyWith(color: Colors.white70),
            ),
          ],
        ),
      );
}
