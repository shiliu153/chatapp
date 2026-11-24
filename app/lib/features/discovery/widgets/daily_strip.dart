import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:phosphor_glyphs/phosphor_glyphs.dart';

import '../../../core/theme/app_shadows.dart';
import '../../../core/theme/app_typography.dart';
import '../../../core/theme/ember_theme_context.dart';
import '../../../core/theme/tokens.g.dart' as tokens;
import '../../../core/ui/ember_ui.dart';
import '../discovery_controller.dart';
import '../models.dart';

/// 「今日精选」区块(批次 S,discovery.md §3.11;视觉迁到 Ember,E-5.2 page spec §3)。
///
/// 横向滚动的迷你卡,点一张进对方资料页。三态处理刻意「安静」:
/// 加载中 / 失败 / 后端给空数组都**整块不渲染** —— 它是滑卡主流程之上的加餐,
/// 不该为它抢走注意力,也不该因为它挂在首页顶部而把滑卡挡住。
class DailyStrip extends ConsumerWidget {
  /// 构造「今日精选」。
  const DailyStrip({super.key});

  /// 卡片尺寸(横向列表高度 + 单卡宽度):够放下「昵称,年龄 + 城市」两行。
  static const cardWidth = 112.0;

  /// 横向列表高度。
  static const cardHeight = 156.0;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final candidates = ref.watch(dailyProvider).value?.candidates ?? const <Candidate>[];
    if (candidates.isEmpty) return const SizedBox.shrink();
    final colors = context.ember;
    return Column(
      key: const Key('discovery.daily'),
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: EdgeInsets.fromLTRB(
            tokens.space20,
            0,
            tokens.space20,
            tokens.space8,
          ),
          child: Row(
            children: [
              // 精选标识走 `status.warning`(§6「会员 / 精选」),图标取 Phosphor `sparkle`。
              Icon(
                PhosphorIconsRegular.sparkle,
                size: tokens.sizeIcon16,
                color: colors.statusWarning,
              ),
              SizedBox(width: tokens.space8),
              Text(
                '今日精选',
                // `subtitle` 17 / w600(§4.2 区块小标题)。
                style: AppText.subtitle.copyWith(color: colors.textPrimary),
              ),
            ],
          ),
        ),
        SizedBox(
          height: DailyStrip.cardHeight,
          child: ListView.separated(
            scrollDirection: Axis.horizontal,
            padding: EdgeInsets.symmetric(horizontal: tokens.space20),
            itemCount: candidates.length,
            separatorBuilder: (_, _) => SizedBox(width: tokens.space12),
            itemBuilder: (context, index) =>
                _DailyCard(candidate: candidates[index], width: DailyStrip.cardWidth),
          ),
        ),
        SizedBox(height: tokens.space12),
      ],
    );
  }
}

/// 精选里的一张迷你卡:照片全出血 + 底部 scrim 叠昵称/年龄/城市。
///
/// 层级与主卡一致(§5.3):浅色 `elev.1`,深色 `border.divider` 1px 分层;
/// 圆角 `radius.lg`(113×156 的小卡用 `lg`,大卡才用 `xl`)。
class _DailyCard extends StatelessWidget {
  const _DailyCard({required this.candidate, required this.width});

  final Candidate candidate;
  final double width;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final photo = candidate.photos.isEmpty ? null : candidate.photos.first;
    final title = candidate.age == null
        ? candidate.nickname
        : '${candidate.nickname},${candidate.age}';
    return EmberPressable(
      key: Key('discovery.daily.card.${candidate.userId}'),
      semanticLabel: '$title,今日精选',
      pressedScale: EmberComponentSizes.cardPressedScale,
      borderRadius: BorderRadius.circular(tokens.radiusLg),
      onTap: () => context.push('/users/${candidate.userId}'),
      builder: (context, state) => SizedBox(
        width: width,
        child: DecoratedBox(
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(tokens.radiusLg),
            boxShadow: isDark ? null : AppShadows.card,
            border: isDark ? Border.all(color: colors.borderDivider) : null,
          ),
          child: ClipRRect(
            borderRadius: BorderRadius.circular(tokens.radiusLg),
            child: Material(
              color: colors.surfaceCard,
              child: Stack(
                fit: StackFit.expand,
                children: [
                  if (photo == null)
                    Center(
                      child: Icon(
                        PhosphorIconsRegular.user,
                        size: tokens.sizeIcon24,
                        color: colors.textTertiary,
                      ),
                    )
                  else
                    Image.network(
                      photo.url,
                      key: ValueKey('daily.photo.${photo.id}'),
                      fit: BoxFit.cover,
                      errorBuilder: (context, error, stack) => Center(
                        child: Icon(
                          PhosphorIconsRegular.user,
                          size: tokens.sizeIcon24,
                          color: colors.textTertiary,
                        ),
                      ),
                    ),
                  Positioned(
                    left: 0,
                    right: 0,
                    bottom: 0,
                    child: Container(
                      padding: EdgeInsets.fromLTRB(
                        tokens.space8,
                        tokens.space24,
                        tokens.space8,
                        tokens.space8,
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
                            title,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: AppText.caption.copyWith(
                              color: Colors.white,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                          if (candidate.city.isNotEmpty)
                            Text(
                              candidate.city,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              textScaler: TextScaler.noScaling,
                              style: AppText.micro.copyWith(
                                color: Colors.white.withValues(alpha: 0.72),
                              ),
                            ),
                        ],
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
