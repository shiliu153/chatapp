import 'package:flutter/material.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_radius.dart';
import '../../../core/theme/app_shadows.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/theme/app_typography.dart';
import '../../../core/widgets/breathing_dot.dart';
import '../../presence/models.dart';
import '../models.dart';

/// 单张候选卡(附录 A「沉浸照片版」):照片全出血 + 底部 scrim 叠字;
/// 多张照片时点左右两侧切换 + 顶部胶囊点指示。
class ProfileCard extends StatefulWidget {
  const ProfileCard({super.key, required this.candidate, this.presence});

  final Candidate candidate;
  final Presence? presence;

  @override
  State<ProfileCard> createState() => _ProfileCardState();
}

class _ProfileCardState extends State<ProfileCard> {
  int _photoIndex = 0;

  @override
  void didUpdateWidget(covariant ProfileCard oldWidget) {
    super.didUpdateWidget(oldWidget);
    // 换成另一个人的卡了,照片从第一张重新看起
    if (oldWidget.candidate.userId != widget.candidate.userId) _photoIndex = 0;
  }

  void _shiftPhoto(int delta) {
    final count = widget.candidate.photos.length;
    if (count < 2) return;
    setState(() => _photoIndex = (_photoIndex + delta + count) % count);
  }

  @override
  Widget build(BuildContext context) {
    final candidate = widget.candidate;
    final photos = candidate.photos;
    final photo = photos.isEmpty ? null : photos[_photoIndex];
    final online = widget.presence?.online ?? false;
    final statusLabel = presenceLabel(widget.presence);
    return Container(
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(AppRadius.discoveryCard),
        boxShadow: AppShadows.card,
      ),
      child: Material(
        color: AppColors.bgCard,
        borderRadius: BorderRadius.circular(AppRadius.discoveryCard),
        clipBehavior: Clip.antiAlias,
        child: Stack(
          fit: StackFit.expand,
          children: [
            if (photo == null)
              Container(
                color: AppColors.divider,
                child: const Center(
                  child: Icon(Icons.person_rounded, size: 64, color: AppColors.text3),
                ),
              )
            else
              Image.network(
                photo.url,
                key: ValueKey('card.photo.${photo.id}'),
                fit: BoxFit.cover,
                errorBuilder: (context, error, stack) => Container(
                  color: AppColors.divider,
                  child: const Center(
                    child: Icon(Icons.person_rounded, size: 64, color: AppColors.text3),
                  ),
                ),
              ),
            if (photos.length > 1) ...[
              Positioned(
                left: 0,
                top: 0,
                bottom: 0,
                width: 56,
                child: GestureDetector(
                  key: const Key('card.prevPhoto'),
                  behavior: HitTestBehavior.translucent,
                  onTap: () => _shiftPhoto(-1),
                ),
              ),
              Positioned(
                right: 0,
                top: 0,
                bottom: 0,
                width: 56,
                child: GestureDetector(
                  key: const Key('card.nextPhoto'),
                  behavior: HitTestBehavior.translucent,
                  onTap: () => _shiftPhoto(1),
                ),
              ),
              Positioned(
                top: 8,
                left: 0,
                right: 0,
                child: Row(
                  key: const Key('card.dots'),
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    for (var i = 0; i < photos.length; i++)
                      Container(
                        width: i == _photoIndex ? 18 : 6, // 当前张:18×6 胶囊
                        height: 6,
                        margin: const EdgeInsets.symmetric(horizontal: 2.5),
                        decoration: BoxDecoration(
                          borderRadius: BorderRadius.circular(3),
                          color: i == _photoIndex
                              ? Colors.white
                              : Colors.white.withValues(alpha: 0.45),
                          // 浅色照片上白点会隐身,加一圈轻微投影兜底可读性(手测发现)
                          boxShadow: [
                            BoxShadow(
                              color: Colors.black.withValues(alpha: 0.28),
                              blurRadius: 3,
                              offset: const Offset(0, 1),
                            ),
                          ],
                        ),
                      ),
                  ],
                ),
              ),
            ],
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
                    Row(
                      children: [
                        Flexible(
                          child: Text(
                            candidate.age == null
                                ? candidate.nickname
                                : '${candidate.nickname},${candidate.age}',
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: AppText.display.copyWith(color: Colors.white),
                          ),
                        ),
                        if (online) ...[
                          const SizedBox(width: AppSpacing.sm),
                          const BreathingDot(
                            key: Key('card.onlineDot'),
                            size: 8,
                            borderColor: Colors.white,
                          ),
                          const SizedBox(width: AppSpacing.xs),
                          Text(
                            '在线',
                            style: AppText.micro.copyWith(
                                color: Colors.white.withValues(alpha: 0.88)),
                          ),
                        ] else if (statusLabel != null) ...[
                          const SizedBox(width: AppSpacing.sm),
                          Text(
                            statusLabel,
                            style: AppText.caption.copyWith(
                                color: Colors.white.withValues(alpha: 0.72)),
                          ),
                        ],
                      ],
                    ),
                    if (candidate.city.isNotEmpty)
                      Padding(
                        padding: const EdgeInsets.only(top: 2),
                        child: Text(
                          candidate.city,
                          style: AppText.caption.copyWith(
                              color: Colors.white.withValues(alpha: 0.72)),
                        ),
                      ),
                    if (candidate.bio.isNotEmpty) ...[
                      const SizedBox(height: 6),
                      Text(
                        candidate.bio,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: AppText.body.copyWith(
                            color: Colors.white.withValues(alpha: 0.93)),
                      ),
                    ],
                    if (candidate.tags.isNotEmpty) ...[
                      const SizedBox(height: AppSpacing.sm),
                      Wrap(
                        spacing: 6,
                        runSpacing: 6,
                        children: [
                          for (final tag in candidate.tags)
                            Container(
                              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                              decoration: BoxDecoration(
                                color: Colors.white.withValues(alpha: 0.22),
                                borderRadius: BorderRadius.circular(AppRadius.chip),
                              ),
                              child: Text(
                                tag.name,
                                style: AppText.micro.copyWith(color: Colors.white),
                              ),
                            ),
                        ],
                      ),
                    ],
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
