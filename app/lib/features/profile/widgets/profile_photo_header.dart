import 'package:flutter/material.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/theme/app_typography.dart';
import '../../../core/widgets/avatar_hero.dart';
import '../../../core/widgets/breathing_dot.dart';

/// 「心跳」附录 C.4 资料页照片头图:全出血照片 + 底部 scrim 叠字 + 顶部 scrim
/// 供透明顶栏(C.5)兜底可读性。无照片时走内容占位(非空态)。
class ProfilePhotoHeader extends StatelessWidget {
  const ProfilePhotoHeader({
    super.key,
    required this.photoUrl,
    required this.nickname,
    this.age,
    this.city = '',
    this.online = false,
    this.heroTag,
  });

  final String? photoUrl;
  final String nickname;
  final int? age;
  final String city;
  final bool online;

  /// Hero tag(C.7);为 null(无来源/深链)时不包 Hero。
  final String? heroTag;

  static const _ratio = 1.15; // 屏宽 × 1.15
  static const _maxHeight = 420.0;
  static const _topScrimAlpha = 0.45;

  @override
  Widget build(BuildContext context) {
    final width = MediaQuery.sizeOf(context).width;
    final height = width * _ratio > _maxHeight ? _maxHeight : width * _ratio;
    final url = photoUrl;
    return SizedBox(
      height: height,
      width: double.infinity,
      child: Stack(
        fit: StackFit.expand,
        children: [
          AvatarHero(
            tag: heroTag,
            imageUrl: url,
            child: url == null || url.isEmpty
                ? const _PhotoPlaceholder()
                : Image.network(
                    url,
                    fit: BoxFit.cover,
                    errorBuilder: (_, _, _) => const _PhotoPlaceholder(),
                  ),
          ),
          // 顶部 scrim:透明顶栏(返回/⋯ 为白色图标)在浅色照片上的可读性兜底
          DecoratedBox(
            decoration: BoxDecoration(
              gradient: LinearGradient(
                begin: Alignment.topCenter,
                end: Alignment.bottomCenter,
                colors: [
                  Colors.black.withValues(alpha: _topScrimAlpha),
                  Colors.transparent,
                ],
              ),
            ),
          ),
          // 底部 scrim:叠字对比度(与附录 A.2 同源)
          Positioned(
            left: 0,
            right: 0,
            bottom: 0,
            child: Container(
              padding: const EdgeInsets.fromLTRB(AppSpacing.lg, 46, AppSpacing.lg, 14),
              decoration: const BoxDecoration(
                gradient: LinearGradient(
                  begin: Alignment.topCenter,
                  end: Alignment.bottomCenter,
                  colors: [Colors.transparent, AppColors.photoScrim],
                ),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    age == null ? nickname : '$nickname,$age',
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: AppText.display.copyWith(color: Colors.white),
                  ),
                  if (online) ...[
                    const SizedBox(height: AppSpacing.xs),
                    Row(
                      children: [
                        const BreathingDot(
                          key: Key('user.onlineDot'),
                          size: 11,
                          borderColor: Colors.white,
                        ),
                        const SizedBox(width: AppSpacing.sm),
                        Text('在线',
                            style: AppText.micro
                                .copyWith(color: Colors.white.withValues(alpha: 0.88))),
                      ],
                    ),
                  ],
                  if (city.isNotEmpty) ...[
                    const SizedBox(height: AppSpacing.xs),
                    Text(city,
                        style: AppText.caption
                            .copyWith(color: Colors.white.withValues(alpha: 0.72))),
                  ],
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// 无照片/加载失败的内容占位(与发现卡同款;非空态,§7 禁灰色图标做空态不适用)。
class _PhotoPlaceholder extends StatelessWidget {
  const _PhotoPlaceholder();

  @override
  Widget build(BuildContext context) => const ColoredBox(
        color: AppColors.divider,
        child: Center(
          child: Icon(Icons.person_rounded, size: 64, color: AppColors.text3),
        ),
      );
}
