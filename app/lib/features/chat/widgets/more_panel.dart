import 'package:flutter/material.dart';

import '../../../core/theme/app_radius.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/theme/app_typography.dart';
import '../../../core/theme/heart_theme_context.dart';

/// ＋面板:目前只有「相册」,后续入口加在这里。
class MorePanel extends StatelessWidget {
  const MorePanel({super.key, required this.onPickImage});

  final VoidCallback onPickImage;

  @override
  Widget build(BuildContext context) {
    final colors = context.heart;
    return Container(
        key: const Key('chat.more.panel'),
        height: 160,
        decoration: BoxDecoration(
          color: colors.bgCard,
          border: Border(top: BorderSide(color: colors.divider)),
        ),
        padding: const EdgeInsets.all(AppSpacing.lg),
        child: Align(
          alignment: Alignment.topLeft,
          child: InkWell(
            key: const Key('chat.more.image'),
            onTap: onPickImage,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Container(
                  width: 56,
                  height: 56,
                  decoration: BoxDecoration(
                    color: colors.brand.withValues(alpha: .12),
                    borderRadius: BorderRadius.circular(AppRadius.input),
                  ),
                  child: Icon(Icons.photo_library_rounded,
                      size: 26, color: colors.brand),
                ),
                const SizedBox(height: 6),
                Text('相册', style: AppText.micro.copyWith(color: colors.text2)),
              ],
            ),
          ),
        ),
      );
  }
}
