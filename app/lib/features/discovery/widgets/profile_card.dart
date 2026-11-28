import 'package:flutter/material.dart';
import 'package:phosphor_glyphs/phosphor_glyphs.dart';

import '../../../core/theme/app_shadows.dart';
import '../../../core/theme/app_typography.dart';
import '../../../core/theme/ember_theme_context.dart';
import '../../../core/theme/tokens.g.dart' as tokens;
import '../../../core/ui/ember_ui.dart';
import '../../../core/widgets/avatar_hero.dart';
import '../../presence/models.dart';
import '../models.dart';

/// 单张候选卡(「余烬 Ember」§8.2 卡片 + E-5.2 page spec §3 / §4):
/// 照片全出血 + 底部 `overlay.scrim` 渐变叠字;圆角 `radius.xl`、内边距 20;
/// 多张照片时点左右两侧切换 + 顶部胶囊点指示。
///
/// 与心跳期的差别只有视觉:交互(切图、点开资料页)一行没动。
///
/// 层级(§5.3):浅色给 `elev.1` 一张卡片阴影,深色**不用阴影**,改 1px
/// `border.divider` + `surface.card` 的色差分层。
class ProfileCard extends StatefulWidget {
  /// 构造候选卡。
  const ProfileCard({
    super.key,
    required this.candidate,
    this.presence,
    this.heroTag,
  });

  /// 卡上展示的人。
  final Candidate candidate;

  /// 在线状态(拿不到就不画在线点)。
  final Presence? presence;

  /// 照片层的 Hero tag(E-5.4 落地:E-5.2 只做普通 push,转场留给本单)。
  ///
  /// 只包**照片本身**、不包整张卡:飞行途中只该是「同一张图」,叠字、指示点、
  /// 操作钮跟着飞会让字在半路变形。`null`(golden 直出 / 非顶卡)时不包 Hero。
  final String? heroTag;

  /// 照片左右切换热区宽度(spec §4「左右 56 热区切图」)。
  static const photoHotZoneWidth = 56.0;

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
    final colors = context.ember;
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final candidate = widget.candidate;
    final photos = candidate.photos;
    final photo = photos.isEmpty ? null : photos[_photoIndex];
    final online = widget.presence?.online ?? false;
    final statusLabel = presenceLabel(widget.presence);
    return DecoratedBox(
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(tokens.radiusXl),
        // §5.3:浅色 `elev.1`,深色描边分层(深底上阴影不可见)。
        boxShadow: isDark ? null : AppShadows.card,
        border: isDark ? Border.all(color: colors.borderDivider) : null,
      ),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(tokens.radiusXl),
        child: Material(
          color: colors.surfaceCard,
          child: Stack(
            fit: StackFit.expand,
            children: [
              // 照片层:有 heroTag 时包一层 AvatarHero(与资料页头图同 tag 即飞)。
              AvatarHero(
                tag: widget.heroTag,
                imageUrl: photo?.url,
                fromRadius: tokens.radiusXl,
                child: photo == null
                    ? const _PhotoPlaceholder()
                    : Image.network(
                        photo.url,
                        key: ValueKey('card.photo.${photo.id}'),
                        fit: BoxFit.cover,
                        errorBuilder: (context, error, stack) =>
                            const _PhotoPlaceholder(),
                      ),
              ),
              if (photos.length > 1) ...[
                Positioned(
                  left: 0,
                  top: 0,
                  bottom: 0,
                  width: ProfileCard.photoHotZoneWidth,
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
                  width: ProfileCard.photoHotZoneWidth,
                  child: GestureDetector(
                    key: const Key('card.nextPhoto'),
                    behavior: HitTestBehavior.translucent,
                    onTap: () => _shiftPhoto(1),
                  ),
                ),
                Positioned(
                  top: tokens.space8,
                  left: 0,
                  right: 0,
                  child: Row(
                    key: const Key('card.dots'),
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      for (var i = 0; i < photos.length; i++)
                        _PhotoDot(active: i == _photoIndex),
                    ],
                  ),
                ),
              ],
              Positioned(
                left: 0,
                right: 0,
                bottom: 0,
                child: Container(
                  // 内边距 20(§5.2);上沿留 40 让渐变有过渡空间,别让文字贴边。
                  padding: EdgeInsets.fromLTRB(
                    tokens.space20,
                    tokens.space40,
                    tokens.space20,
                    tokens.space20,
                  ),
                  decoration: BoxDecoration(
                    gradient: LinearGradient(
                      begin: Alignment.topCenter,
                      end: Alignment.bottomCenter,
                      // 底部叠字一律压 `overlay.scrim`(§8.3):浅深两套都是深色,
                      // 所以白字在上面都过线,不必再按模式分文案色。
                      colors: [
                        colors.overlayScrim.withValues(alpha: 0),
                        colors.overlayScrim,
                      ],
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
                              // `title` 24 / Fraunces(§4.2「昵称、年龄大字」)。
                              style: AppText.title.copyWith(color: Colors.white),
                            ),
                          ),
                          if (online) ...[
                            SizedBox(width: tokens.space8),
                            EmberOnlineDot(
                              key: const Key('card.onlineDot'),
                              size: EmberComponentSizes.onlineDotSmall,
                              background: Colors.white,
                            ),
                            SizedBox(width: tokens.space4),
                            // 「颜色不是唯一线索」:点 + 文字(§8.4)。
                            Text(
                              '在线',
                              textScaler: TextScaler.noScaling,
                              style: AppText.micro.copyWith(
                                color: Colors.white.withValues(alpha: 0.88),
                              ),
                            ),
                          ] else if (statusLabel != null) ...[
                            SizedBox(width: tokens.space8),
                            Flexible(
                              child: Text(
                                statusLabel,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: AppText.caption.copyWith(
                                  color: Colors.white.withValues(alpha: 0.72),
                                ),
                              ),
                            ),
                          ],
                        ],
                      ),
                      if (candidate.city.isNotEmpty)
                        Padding(
                          padding: EdgeInsets.only(top: tokens.space4),
                          child: Text(
                            candidate.city,
                            style: AppText.caption.copyWith(
                              color: Colors.white.withValues(alpha: 0.72),
                            ),
                          ),
                        ),
                      if (candidate.bio.isNotEmpty) ...[
                        SizedBox(height: tokens.space8),
                        Text(
                          candidate.bio,
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                          style: AppText.body.copyWith(
                            color: Colors.white.withValues(alpha: 0.93),
                          ),
                        ),
                      ],
                      if (candidate.tags.isNotEmpty) ...[
                        SizedBox(height: tokens.space12),
                        Wrap(
                          spacing: tokens.space8,
                          runSpacing: tokens.space8,
                          children: [
                            for (final tag in candidate.tags)
                              Container(
                                padding: EdgeInsets.symmetric(
                                  horizontal: tokens.space8,
                                  vertical: tokens.space4,
                                ),
                                decoration: BoxDecoration(
                                  // 照片上的标签:白 22% 底 + micro 白字(§4 卡面 default)。
                                  color: Colors.white.withValues(alpha: 0.22),
                                  borderRadius: BorderRadius.circular(tokens.radiusXs),
                                ),
                                child: Text(
                                  tag.name,
                                  // micro 档不跟随系统字号缩放(§8.4)。
                                  textScaler: TextScaler.noScaling,
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
      ),
    );
  }
}

/// 无照片 / 图挂了时的**内容占位**(不是空态插画,§4 卡面表):`surface.sunken` 底 +
/// Phosphor `user` 64 `text.tertiary`。
class _PhotoPlaceholder extends StatelessWidget {
  const _PhotoPlaceholder();

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    return ColoredBox(
      color: colors.surfaceSunken,
      child: Center(
        child: Icon(
          PhosphorIconsRegular.user,
          size: 64,
          color: colors.textTertiary,
        ),
      ),
    );
  }
}

/// 照片指示点:当前张 18×6 胶囊、其余 6×6 圆点(规范未覆盖 → 保留现形态)。
///
/// 白点落在浅色照片上会隐身,所以仍带一圈极轻的黑投影兜底可读性(手测发现)。
class _PhotoDot extends StatelessWidget {
  const _PhotoDot({required this.active});

  final bool active;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: active ? 18 : 6,
      height: 6,
      margin: EdgeInsets.symmetric(horizontal: tokens.space4 / 2),
      decoration: BoxDecoration(
        // 胶囊圆角:6px 高度下 `radiusPill` 由绘制期钳到高度一半(= 3),与原先写死的
        // `circular(3)` 逐像素等价,见 `test/core/ui/radius_pill_equivalence_test.dart`。
        borderRadius: BorderRadius.circular(tokens.radiusPill),
        color: active ? Colors.white : Colors.white.withValues(alpha: 0.45),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.28),
            blurRadius: 3,
            offset: const Offset(0, 1),
          ),
        ],
      ),
    );
  }
}
