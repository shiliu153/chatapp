import 'package:flutter/material.dart';

import '../theme/app_gradients.dart';
import '../theme/app_typography.dart';
import 'breathing_dot.dart';
import '../theme/heart_theme_context.dart';
import '../theme/heart_colors.dart';

/// 「心跳」规则 §5.3 头像:一律圆形;可选光晕环(可聊/新配对)与在线绿点。
/// 尺寸档:28/32/40/48/56/96(自由传入,在线点按 ≥48 取 11、否则 8)。
class AppAvatar extends StatelessWidget {
  const AppAvatar({
    super.key,
    this.imageUrl,
    this.size = 48,
    this.halo = false,
    this.showOnlineDot = false,
    this.dotBorderColor = Colors.white,
    this.fallbackText,
  });

  final String? imageUrl;
  final double size;
  final bool halo;
  final bool showOnlineDot;
  final Color dotBorderColor;

  /// 无图时的首字占位(附录 B.7);为空则保持人形图标占位。
  final String? fallbackText;

  /// 首字占位的取色环(附录 B.7)。随主题走,所以不能是 static const。
  static List<Color> _fallbackTints(HeartColors colors) => [
        colors.brand,
        colors.violet,
        colors.green,
        colors.amber,
      ];

  @override
  Widget build(BuildContext context) {
    final colors = context.heart;
    Widget avatar = ClipOval(
      child: SizedBox.square(
        dimension: size,
        child: imageUrl == null
            ? _placeholder(colors)
            : Image.network(
                imageUrl!,
                fit: BoxFit.cover,
                errorBuilder: (_, _, _) => _placeholder(colors),
              ),
      ),
    );

    if (halo) {
      avatar = Container(
        padding: const EdgeInsets.all(2.5),
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          gradient: AppGradients.heartOf(colors),
        ),
        child: Container(
          padding: const EdgeInsets.all(2),
          decoration: BoxDecoration(shape: BoxShape.circle, color: dotBorderColor),
          child: avatar,
        ),
      );
    }

    if (showOnlineDot) {
      avatar = Stack(
        clipBehavior: Clip.none,
        children: [
          avatar,
          Positioned(
            right: 0,
            bottom: 0,
            child: BreathingDot(
              key: const Key('avatar.onlineDot'),
              size: size >= 48 ? 11 : 8,
              borderColor: dotBorderColor,
            ),
          ),
        ],
      );
    }
    return avatar;
  }

  Widget _placeholder(HeartColors colors) {
    final text = fallbackText;
    if (text == null || text.isEmpty) {
      return Container(
        color: colors.divider,
        child: Center(
          child: Icon(Icons.person_rounded, color: colors.text3, size: size * 0.6),
        ),
      );
    }
    // 按名字内容稳定取色:同一人始终同色(不依赖 hashCode 的跨版本稳定性)
    final tints = _fallbackTints(colors);
    final tint =
        tints[text.codeUnits.fold<int>(0, (sum, unit) => sum + unit) % tints.length];
    return Container(
      color: tint.withValues(alpha: 0.12),
      child: Center(
        child: Text(
          text.substring(0, 1),
          style: AppText.subtitle.copyWith(fontSize: size * 0.38, color: colors.text1),
        ),
      ),
    );
  }
}
