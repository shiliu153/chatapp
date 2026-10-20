import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_exception.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_radius.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/theme/app_typography.dart';
import '../../core/widgets/app_badge.dart';
import '../../core/widgets/app_button.dart';
import '../../core/widgets/app_empty_state.dart';
import '../../core/widgets/app_error_view.dart';
import '../../core/widgets/heart_ripple.dart';
import '../chat/match_cache.dart';
import '../presence/presence_controller.dart';
import '../profile/models.dart';
import '../profile/profile_controller.dart';
import 'discovery_controller.dart';
import 'likes_received_controller.dart';
import 'models.dart';
import 'widgets/deck_skeleton.dart';
import 'widgets/match_overlay.dart';
import 'widgets/swipe_deck.dart';

class DiscoveryPage extends ConsumerWidget {
  const DiscoveryPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final profile = ref.watch(profileProvider);
    return Scaffold(
      body: SafeArea(
        bottom: false,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(
                  AppSpacing.pageH, AppSpacing.lg, AppSpacing.pageH, AppSpacing.md),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text('发现', style: AppText.display.copyWith(color: AppColors.text1)),
                  _LikesEntry(count: ref.watch(likesReceivedCountProvider).value ?? 0),
                ],
              ),
            ),
            Expanded(
              child: profile.when(
                loading: () => const DeckSkeleton(),
                error: (error, _) => AppErrorView(
                  message: apiMessageOf(error),
                  onRetry: () => ref.read(profileProvider.notifier).reload(),
                ),
                data: (data) =>
                    data.isComplete ? const _DeckView() : _IncompleteView(profile: data),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// 资料不全时不能滑卡,先把人引去向导。
class _IncompleteView extends StatelessWidget {
  const _IncompleteView({required this.profile});

  final Profile profile;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.xxl),
        child: AppEmptyState(
          mark: const HeartRipple(),
          title: '完善资料后就能开始滑卡',
          description: '还差:${profile.missingFields.map(missingFieldLabel).join('、')}',
          action: AppButton(
            key: const Key('discovery.goOnboarding'),
            label: '去完善',
            onPressed: () => context.go('/onboarding'),
          ),
        ),
      ),
    );
  }
}

class _DeckView extends ConsumerWidget {
  const _DeckView();

  Future<bool> _decide(BuildContext context, WidgetRef ref, Candidate candidate,
      {required bool like}) async {
    try {
      final matched =
          await ref.read(discoveryProvider.notifier).decide(candidate, like: like);
      if (matched && context.mounted) {
        final me = ref.read(profileProvider).value;
        ref.invalidate(matchCacheProvider); // 刚配对的人,昵称/头像要立刻能显示
        await showMatchOverlay(
          context,
          candidate: candidate,
          myAvatarUrl: me?.avatar?.url,
          onGoChat: () => context.push('/chat/u${candidate.userId}'),
        );
      }
      return matched;
    } on ApiException catch (error) {
      if (context.mounted) {
        ScaffoldMessenger.of(context)
          ..hideCurrentSnackBar()
          ..showSnackBar(SnackBar(content: Text(error.message)));
      }
      return false;
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final deck = ref.watch(discoveryProvider);
    final presenceById = ref.watch(presenceProvider);
    return deck.when(
      loading: () => const DeckSkeleton(),
      error: (error, _) => AppErrorView(
        message: apiMessageOf(error),
        onRetry: () => ref.read(discoveryProvider.notifier).reload(),
      ),
      data: (candidates) {
        ref.read(presenceProvider.notifier).track(
            'discovery', [for (final candidate in candidates) candidate.userId]);
        return candidates.isEmpty
            ? _EmptyView(
                onRefresh: () => ref.read(discoveryProvider.notifier).reload())
            : SwipeDeck(
                candidates: candidates,
                presenceById: presenceById,
                onDecide: (candidate, {required like}) =>
                    _decide(context, ref, candidate, like: like),
              );
      },
    );
  }
}

class _EmptyView extends StatelessWidget {
  const _EmptyView({required this.onRefresh});

  final VoidCallback onRefresh;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.xxl),
        child: AppEmptyState(
          mark: const HeartRipple(),
          title: '附近暂时没有新的人了',
          description: '过会儿再来看看吧',
          action: AppButton(
            key: const Key('discovery.refresh'),
            label: '刷新',
            onPressed: onRefresh,
          ),
        ),
      ),
    );
  }
}


/// 发现页右上角入口:心形 + 收到喜欢的数量。
class _LikesEntry extends StatelessWidget {
  const _LikesEntry({required this.count});

  final int count;

  @override
  Widget build(BuildContext context) => InkWell(
        key: const Key('discovery.likes'),
        borderRadius: BorderRadius.circular(AppRadius.full),
        onTap: () => context.push('/likes'),
        child: Padding(
          padding: const EdgeInsets.symmetric(
              horizontal: AppSpacing.sm, vertical: AppSpacing.xs),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.favorite_rounded, size: 20, color: AppColors.brand),
              const SizedBox(width: AppSpacing.xs),
              Text('喜欢我的人',
                  style: AppText.caption.copyWith(color: AppColors.text2)),
              if (count > 0) ...[
                const SizedBox(width: AppSpacing.xs),
                AppBadge(count: count),
              ],
            ],
          ),
        ),
      );
}
