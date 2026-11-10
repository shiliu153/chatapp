import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/theme/app_radius.dart';
import '../../../core/theme/app_shadows.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/theme/app_typography.dart';
import '../../../core/theme/heart_theme_context.dart';
import '../discovery_controller.dart';
import '../models.dart';

/// 「今日精选」区块(批次 S,discovery.md §3.11)。
///
/// 横向滚动的 6 张迷你卡,点一张进对方资料页。三态处理刻意「安静」:
/// 加载中 / 失败 / 后端给空数组都**整块不渲染** —— 它是滑卡主流程之上的加餐,
/// 不该为它抢走注意力,也不该因为它挂在首页顶部而把滑卡挡住。
class DailyStrip extends ConsumerWidget {
  const DailyStrip({super.key});

  /// 卡片尺寸(横向列表高度 + 单卡宽度):够放下「昵称,年龄 + 城市」两行。
  static const _cardWidth = 112.0;
  static const _cardHeight = 156.0;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final candidates = ref.watch(dailyProvider).value?.candidates ?? const <Candidate>[];
    if (candidates.isEmpty) return const SizedBox.shrink();
    final colors = context.heart;
    return Column(
      key: const Key('discovery.daily'),
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(
              AppSpacing.pageH, 0, AppSpacing.pageH, AppSpacing.sm),
          child: Row(
            children: [
              Icon(Icons.auto_awesome_rounded, size: 16, color: colors.brand),
              const SizedBox(width: AppSpacing.xs),
              Text('今日精选', style: AppText.subtitle.copyWith(color: colors.text1)),
            ],
          ),
        ),
        SizedBox(
          height: _cardHeight,
          child: ListView.separated(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.symmetric(horizontal: AppSpacing.pageH),
            itemCount: candidates.length,
            separatorBuilder: (_, _) => const SizedBox(width: AppSpacing.sm),
            itemBuilder: (context, index) =>
                _DailyCard(candidate: candidates[index], width: _cardWidth),
          ),
        ),
        const SizedBox(height: AppSpacing.md),
      ],
    );
  }
}

/// 精选里的一张迷你卡:照片全出血 + 底部 scrim 叠昵称/年龄/城市。
class _DailyCard extends StatelessWidget {
  const _DailyCard({required this.candidate, required this.width});

  final Candidate candidate;
  final double width;

  @override
  Widget build(BuildContext context) {
    final colors = context.heart;
    final photo = candidate.photos.isEmpty ? null : candidate.photos.first;
    final title = candidate.age == null
        ? candidate.nickname
        : '${candidate.nickname},${candidate.age}';
    return Semantics(
      button: true,
      label: '$title,今日精选',
      child: GestureDetector(
        key: Key('discovery.daily.card.${candidate.userId}'),
        behavior: HitTestBehavior.opaque,
        onTap: () => context.push('/users/${candidate.userId}'),
        child: Container(
          width: width,
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(AppRadius.card),
            boxShadow: AppShadows.card,
          ),
          child: Material(
            color: colors.bgCard,
            borderRadius: BorderRadius.circular(AppRadius.card),
            clipBehavior: Clip.antiAlias,
            child: Stack(
              fit: StackFit.expand,
              children: [
                if (photo == null)
                  Center(
                    child: Icon(Icons.person_rounded, size: 40, color: colors.text3),
                  )
                else
                  Image.network(
                    photo.url,
                    key: ValueKey('daily.photo.${photo.id}'),
                    fit: BoxFit.cover,
                    errorBuilder: (context, error, stack) => Center(
                      child: Icon(Icons.person_rounded, size: 40, color: colors.text3),
                    ),
                  ),
                Positioned(
                  left: 0,
                  right: 0,
                  bottom: 0,
                  child: Container(
                    padding: const EdgeInsets.fromLTRB(
                        AppSpacing.sm, AppSpacing.xl, AppSpacing.sm, AppSpacing.sm),
                    decoration: BoxDecoration(
                      gradient: LinearGradient(
                        begin: Alignment.topCenter,
                        end: Alignment.bottomCenter,
                        colors: [Colors.transparent, colors.photoScrim],
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
                              color: Colors.white, fontWeight: FontWeight.w600),
                        ),
                        if (candidate.city.isNotEmpty)
                          Text(
                            candidate.city,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: AppText.micro.copyWith(
                                color: Colors.white.withValues(alpha: 0.72)),
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
    );
  }
}
