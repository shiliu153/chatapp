import 'package:flutter/material.dart';
import 'package:phosphor_glyphs/phosphor_glyphs.dart';

import '../../../core/theme/app_typography.dart';
import '../../../core/theme/ember_theme_context.dart';
import '../../../core/theme/tokens.g.dart' as tokens;
import '../../../core/ui/ember_ui.dart';
import '../../../core/widgets/avatar_hero.dart';
import '../profile_component_sizes.dart';

/// 资料页照片头图(E-5.4 page spec §3「照片头图」/ 上游 §8.2 卡片 + §3.3 overlay)。
///
/// 结构:全出血照片 + 底部 `overlay.scrim` 渐变叠字(`title` 24 Fraunces 白字)+
/// 顶部 scrim(透明顶栏的可读性兜底);无照片时走**内容占位**(`surface.sunken` +
/// Phosphor `user` 64 `text.tertiary`)—— 这是 §4 头图表里的一格,不是空态。
///
/// Hero:整块照片参与转场(发现页卡照片 / 对话页头像 → 本页),飞行中只带照片、
/// 不带叠字 —— 叠字跟着飞会让字在半路变形,而 Hero 的 shuttle 只该是「同一张图」。
///
/// 为什么叠字用纯白而不是 `overlay.on`:`overlay.scrim` 在两套主题下都是深色底,
/// 白字在两种模式下对比度一致(`no_raw_colors_test` 的白名单也只放行白 / 黑 / 透明)。
class ProfilePhotoHeader extends StatelessWidget {
  /// 构造头图。
  const ProfilePhotoHeader({
    super.key,
    required this.photoUrl,
    required this.nickname,
    this.age,
    this.city = '',
    this.online = false,
    this.heroTag,
    this.height,
  });

  /// 头图照片地址;`null` / 空串走占位。
  final String? photoUrl;

  /// 昵称(叠字第一行,读屏也用它)。
  final String nickname;

  /// 年龄;有值时叠成「昵称,25」(与发现卡同款格式)。
  final int? age;

  /// 城市(叠字第二行,空则不占行)。
  final String city;

  /// 是否在线(叠字旁 `status.success` 呼吸点 + 「在线」,§8.4「颜色不是唯一线索」)。
  final bool online;

  /// Hero tag;`null`(深链 / 无来源)时不包 Hero。
  final String? heroTag;

  /// 覆盖高度;`null` 时按 [ProfileComponentSizes.headerRatio] 由屏宽推。
  final double? height;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    final width = MediaQuery.sizeOf(context).width;
    final resolvedHeight = height ??
        (width * ProfileComponentSizes.headerRatio >
                ProfileComponentSizes.headerMaxHeight
            ? ProfileComponentSizes.headerMaxHeight
            : width * ProfileComponentSizes.headerRatio);
    final url = photoUrl;
    final hasPhoto = url != null && url.isNotEmpty;

    final Widget photo = hasPhoto
        ? Image.network(
            url,
            fit: BoxFit.cover,
            width: double.infinity,
            height: resolvedHeight,
            errorBuilder: (_, _, _) => const ProfilePhotoPlaceholder(),
          )
        : const ProfilePhotoPlaceholder();

    return SizedBox(
      height: resolvedHeight,
      width: double.infinity,
      child: Stack(
        fit: StackFit.expand,
        children: [
          AvatarHero(
            tag: heroTag,
            imageUrl: hasPhoto ? url : null,
            fromRadius: tokens.radiusXl,
            child: photo,
          ),
          // 顶部 scrim:透明顶栏(白色返回 / ⋯)压在浅色照片上的可读性兜底。
          DecoratedBox(
            decoration: BoxDecoration(
              gradient: LinearGradient(
                begin: Alignment.topCenter,
                end: Alignment.bottomCenter,
                colors: [
                  Colors.black.withValues(alpha: ProfileComponentSizes.topScrimAlpha),
                  Colors.transparent,
                ],
              ),
            ),
          ),
          // 底部叠字:压 `overlay.scrim`,白字在两套模式下对比度一致(§8.3 卡面同源)。
          Positioned(
            left: 0,
            right: 0,
            bottom: 0,
            child: Container(
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
                  Text(
                    age == null ? nickname : '$nickname,$age',
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    // `title` 24 / Fraunces / 白(§4.2「昵称、年龄大字」)。
                    style: AppText.title.copyWith(color: Colors.white),
                  ),
                  if (online) ...[
                    SizedBox(height: tokens.space8),
                    Row(
                      children: [
                        EmberOnlineDot(
                          key: const Key('user.onlineDot'),
                          size: EmberComponentSizes.onlineDot,
                          // 描边取白:照片底色不可知,与叠字同色最稳。
                          background: Colors.white,
                        ),
                        SizedBox(width: tokens.space8),
                        Text(
                          '在线',
                          textScaler: TextScaler.noScaling,
                          style: AppText.micro.copyWith(
                            color: Colors.white.withValues(alpha: 0.88),
                          ),
                        ),
                      ],
                    ),
                  ],
                  if (city.isNotEmpty) ...[
                    SizedBox(height: tokens.space8),
                    Text(
                      city,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: AppText.caption.copyWith(
                        color: Colors.white.withValues(alpha: 0.72),
                      ),
                    ),
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

/// 无照片 / 图挂了时的**内容占位**(page spec §4 头图表):`surface.sunken` 底 +
/// Phosphor `user` 64 `text.tertiary`。
///
/// 它与 §6「空态禁止灰色图标占位」不冲突:那是**空态**(整页无内容)的规矩,
/// 这里是「有内容、只是没有照片」的占位,与发现卡卡面同款。
class ProfilePhotoPlaceholder extends StatelessWidget {
  /// 构造占位。
  const ProfilePhotoPlaceholder({super.key});

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    return ColoredBox(
      key: const Key('profile.photoPlaceholder'),
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
