import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_exception.dart';
import '../../core/theme/heart_theme_context.dart';
import '../../core/theme/app_radius.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/theme/app_typography.dart';
import '../../core/widgets/app_badge.dart';
import '../../core/widgets/app_button.dart';
import '../../core/widgets/app_empty_state.dart';
import '../../core/widgets/app_error_view.dart';
import '../../core/widgets/app_toast.dart';
import '../../core/widgets/heart_ripple.dart';
import '../chat/match_cache.dart';
import '../presence/presence_controller.dart';
import '../profile/models.dart';
import '../profile/profile_controller.dart';
import 'discovery_clock.dart';
import 'discovery_controller.dart';
import 'like_quota_controller.dart';
import 'likes_received_controller.dart';
import 'models.dart';
import 'swipe_undo_controller.dart';
import 'visits_controller.dart';
import 'widgets/deck_skeleton.dart';
import 'widgets/match_overlay.dart';
import 'widgets/swipe_deck.dart';
import 'widgets/undo_button.dart';

/// 额度用完时的统一提示(discovery.md §3.10)。
const likeQuotaExhaustedHint = '今日喜欢次数已用完,明天再来';

class DiscoveryPage extends ConsumerWidget {
  const DiscoveryPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final colors = context.heart;
    final profile = ref.watch(profileProvider);
    // 每日喜欢额度(discovery.md §3.10)。只有当 `like_limit > 0` 时才有文案,
    // 后端默认不限(0)—— 那种情况下 provider 返回 null,整行不渲染。
    // 资料没完善时滑不了卡,也就没必要为它多拉一次额度。
    final remaining = profile.value?.isComplete == true
        ? ref.watch(likeQuotaProvider).likesRemaining
        : null;
    return Scaffold(
      body: SafeArea(
        bottom: false,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(
                  AppSpacing.pageH, AppSpacing.lg, AppSpacing.pageH, AppSpacing.md),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Text('发现', style: AppText.display.copyWith(color: colors.text1)),
                      Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          _TopEntry(
                            entryKey: const Key('discovery.likes'),
                            icon: Icons.favorite_rounded,
                            iconColor: colors.brand,
                            label: '喜欢我的人',
                            count: ref.watch(likesReceivedCountProvider).value ?? 0,
                            onTap: () => context.push('/likes'),
                          ),
                          const SizedBox(width: AppSpacing.xs),
                          _TopEntry(
                            entryKey: const Key('discovery.visits'),
                            icon: Icons.visibility_rounded,
                            iconColor: colors.text2,
                            label: '谁看过我',
                            count: ref.watch(visitsCountProvider).value ?? 0,
                            onTap: () => context.push('/visits'),
                          ),
                        ],
                      ),
                    ],
                  ),
                  if (remaining != null) ...[
                    const SizedBox(height: AppSpacing.xs),
                    Text(
                      '今日还可喜欢 $remaining 次',
                      key: const Key('discovery.quota'),
                      style: AppText.caption.copyWith(color: colors.text2),
                    ),
                  ],
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

  /// 现在能不能点喜欢:`42904` 之后的冷却窗内不能(discovery.md §3.10)。
  bool _likeBlocked(WidgetRef ref) =>
      ref.read(likeQuotaProvider).isBlockedAt(ref.read(discoveryClockProvider)());

  /// 喜欢 / 跳过一张卡。
  ///
  /// 只有**成功**的滑卡才记进「最近一次可撤销」(失败的那次根本没落库);喜欢成功
  /// 顺手把额度文案减一,遇到 `42904` 则按 `Retry-After` 关掉喜欢按钮。
  Future<bool> _decide(BuildContext context, WidgetRef ref, Candidate candidate,
      {required bool like}) async {
    if (like && _likeBlocked(ref)) {
      // 按钮已经置灰,这条是拖拽右滑的兜底:不去撞后端,直接告诉用户今天没了
      AppToast.show(context, likeQuotaExhaustedHint);
      return false;
    }
    try {
      final result =
          await ref.read(discoveryProvider.notifier).decide(candidate, like: like);
      // 已配对的滑卡后端一律拒绝撤销(§3.9),这时按钮也不该出现;没配对的才记一笔
      if (result.matched) {
        ref.read(swipeUndoProvider.notifier).forget();
      } else {
        ref.read(swipeUndoProvider.notifier).remember(candidate);
      }
      if (like) ref.read(likeQuotaProvider.notifier).consumeOne();
      if (result.matched && context.mounted) {
        final me = ref.read(profileProvider).value;
        ref.invalidate(matchCacheProvider); // 刚配对的人,昵称/头像要立刻能显示
        await showMatchOverlay(
          context,
          candidate: candidate,
          myAvatarUrl: me?.avatar?.url,
          sharedTags: result.sharedTags,
          myCity: me?.city ?? '',
          onGoChat: () => context.push('/chat/u${candidate.userId}'),
        );
      }
      return result.matched;
    } on ApiException catch (error) {
      if (error.code == likeQuotaExceededCode) {
        final quota = ref.read(likeQuotaProvider.notifier);
        quota.blockFor(error.retryAfter);
        unawaited(quota.refresh()); // 顺手把「还剩 0 次」拉回来,别再显示旧数字
      }
      if (context.mounted) {
        AppToast.show(context,
            error.code == likeQuotaExceededCode ? likeQuotaExhaustedHint : error.message);
      }
      return false;
    }
  }

  /// 撤销最近一次滑卡(discovery.md §3.9)。
  ///
  /// 成功的卡由控制器放回卡堆顶部,这里只管提示;`40003` 意味着「没得撤」
  /// (超 30 秒 / 已配对 / 连撤两次),顺手把按钮收起来。
  Future<void> _undo(BuildContext context, WidgetRef ref) async {
    try {
      await ref.read(swipeUndoProvider.notifier).undo();
      if (context.mounted) AppToast.show(context, '已撤销');
    } on ApiException catch (error) {
      if (error.code == undoSwipeUnavailableCode) {
        ref.read(swipeUndoProvider.notifier).forget();
        if (context.mounted) AppToast.show(context, '没有可撤销的操作');
        return;
      }
      if (context.mounted) AppToast.show(context, error.message);
    }
  }

  /// 撤销按钮:key 跟着「这一次滑卡」走,换一张卡就让倒计时从 30 秒重新开始。
  Widget _undoButton(BuildContext context, WidgetRef ref, UndoableSwipe undo) {
    final now = ref.read(discoveryClockProvider)();
    return UndoButton(
      key: ValueKey(undo),
      remaining: swipeUndoWindow - now.difference(undo.at),
      onUndo: () => _undo(context, ref),
    );
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final deck = ref.watch(discoveryProvider);
    final presenceById = ref.watch(presenceProvider);
    final quota = ref.watch(likeQuotaProvider);
    final undo = ref.watch(swipeUndoProvider);
    final undoAction = undo == null ? null : _undoButton(context, ref, undo);
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
                onRefresh: () => ref.read(discoveryProvider.notifier).reload(),
                undoAction: undoAction,
              )
            : SwipeDeck(
                candidates: candidates,
                presenceById: presenceById,
                likeBlocked: quota.isBlockedAt(ref.read(discoveryClockProvider)()),
                undoAction: undoAction,
                onDecide: (candidate, {required like}) =>
                    _decide(context, ref, candidate, like: like),
              );
      },
    );
  }
}

class _EmptyView extends StatelessWidget {
  const _EmptyView({required this.onRefresh, this.undoAction});

  final VoidCallback onRefresh;

  /// 撤销按钮:把最后一张也划掉时,卡组空了但还应该能把那张要回来。
  final Widget? undoAction;

  @override
  Widget build(BuildContext context) {
    final undo = undoAction;
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.xxl),
        child: AppEmptyState(
          mark: const HeartRipple(),
          title: '附近暂时没有新的人了',
          description: '过会儿再来看看吧',
          action: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              AppButton(
                key: const Key('discovery.refresh'),
                label: '刷新',
                onPressed: onRefresh,
              ),
              if (undo != null) ...[
                const SizedBox(height: AppSpacing.lg),
                undo,
              ],
            ],
          ),
        ),
      ),
    );
  }
}


/// 发现页右上角入口:图标 + 文案 + 角标;窄屏(<360dp)只留图标,靠 Semantics 读屏。
class _TopEntry extends StatelessWidget {
  const _TopEntry({
    required this.entryKey,
    required this.icon,
    required this.iconColor,
    required this.label,
    required this.count,
    required this.onTap,
  });

  final Key entryKey;
  final IconData icon;
  final Color iconColor;
  final String label;
  final int count;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = context.heart;
    final showLabel = MediaQuery.sizeOf(context).width >= 360;
    final semantic = count > 0 ? '$label,$count 人' : label;
    return Semantics(
      button: true,
      label: semantic,
      child: InkWell(
        key: entryKey,
        borderRadius: BorderRadius.circular(AppRadius.full),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(
              horizontal: AppSpacing.xs, vertical: AppSpacing.xs),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon, size: 20, color: iconColor),
              if (showLabel) ...[
                const SizedBox(width: AppSpacing.xs),
                Text(label, style: AppText.caption.copyWith(color: colors.text2)),
              ],
              if (count > 0) ...[
                const SizedBox(width: AppSpacing.xs),
                AppBadge(count: count),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
