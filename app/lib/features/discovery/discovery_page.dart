import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:phosphor_glyphs/phosphor_glyphs.dart';

import '../../core/api_exception.dart';
import '../../core/theme/app_typography.dart';
import '../../core/theme/ember_theme_context.dart';
import '../../core/theme/tokens.g.dart' as tokens;
import '../../core/ui/ember_ui.dart';
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
import 'widgets/daily_strip.dart';
import 'widgets/deck_skeleton.dart';
import 'widgets/discovery_filter_sheet.dart';
import 'widgets/discovery_illustration.dart';
import 'widgets/match_overlay.dart';
import 'widgets/swipe_deck.dart';
import 'widgets/undo_button.dart';

/// 额度用完时的统一提示(discovery.md §3.10)。
const likeQuotaExhaustedHint = '今日喜欢次数已用完,明天再来';

/// 遇见(发现)页(「余烬 Ember」§9.1 主轴 + E-5.2 page spec §1 / §3)。
///
/// 本单只换视觉与动效,业务逻辑零改动:`discoveryProvider` / `likeQuotaProvider` /
/// `swipeUndoProvider` 的请求与状态机一行没动。
///
/// 与心跳期的三处明显差别(page spec §1 的「用户可见的变化」表):
/// 1. 页面标题「发现」→ **「遇见」**(与底栏 tab 对齐,§9.1);
/// 2. 页内边距 16 → **20**(§5.2),顶部入口换 Phosphor 图标;
/// 3. 筛选入口自绘胶囊 → **[EmberChip]**(§8.3 Chip 行,本单在 `core/ui` 新增)。
class DiscoveryPage extends ConsumerWidget {
  /// 构造页面。
  const DiscoveryPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final colors = context.ember;
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
              padding: EdgeInsets.fromLTRB(
                tokens.space20,
                tokens.space16,
                tokens.space20,
                tokens.space12,
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      // `display` 32 / Fraunces(§4.2 Tab 大标题档)。
                      Text(
                        '遇见',
                        style: AppText.display.copyWith(color: colors.textPrimary),
                      ),
                      Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          _TopEntry(
                            entryKey: const Key('discovery.likes'),
                            icon: PhosphorIconsRegular.heart,
                            selectedIcon: PhosphorIconsFill.heart,
                            label: '喜欢我的人',
                            count: ref.watch(likesReceivedCountProvider).value ?? 0,
                            onTap: () => context.push('/likes'),
                          ),
                          SizedBox(width: tokens.space8),
                          _TopEntry(
                            entryKey: const Key('discovery.visits'),
                            icon: PhosphorIconsRegular.eye,
                            selectedIcon: PhosphorIconsFill.eye,
                            label: '谁看过我',
                            count: ref.watch(visitsCountProvider).value ?? 0,
                            onTap: () => context.push('/visits'),
                          ),
                        ],
                      ),
                    ],
                  ),
                  SizedBox(height: tokens.space8),
                  // 筛选入口单独占一行:三个入口 + 计数角标挤在标题行里,
                  // 360dp 窄屏会溢出(标题行保持原样不动)。
                  Row(
                    children: [
                      const _FilterEntry(),
                      const Spacer(),
                      if (remaining != null)
                        Text(
                          '今日还可喜欢 $remaining 次',
                          key: const Key('discovery.quota'),
                          style: AppText.caption.copyWith(color: colors.textSecondary),
                        ),
                    ],
                  ),
                ],
              ),
            ),
            // 今日精选(批次 S):空/失败/加载中都整块不渲染,不抢滑卡的注意力
            if (profile.value?.isComplete == true) const DailyStrip(),
            Expanded(
              child: profile.when(
                loading: () => const DeckSkeleton(),
                error: (error, _) => _ErrorView(
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

/// 加载失败:unDraw「Connection lost」+ 说明 + 主按钮「重试」(§5 / §8.3 空态错误形态)。
class _ErrorView extends StatelessWidget {
  const _ErrorView({required this.message, required this.onRetry});

  /// 后端 / 网络给的文案(页面不再自己编)。
  final String message;

  /// 重试回调。
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return _CenteredScrollable(
      child: EmberEmpty(
        illustration: const DiscoveryIllustration(
          DiscoveryIllustrationKind.loadFailed,
        ),
        title: '没能拉到人',
        description: message,
        actionLabel: '重试',
        actionKey: const Key('discovery.retry'),
        onAction: onRetry,
      ),
    );
  }
}

/// 空 / 错 / 引导三态的**矮屏包装**:放得下就居中,放不下就能滚。
///
/// 为什么需要:顶部有标题行 + 「今日精选」区块之后,卡组区在矮屏(600dp 上下)只剩
/// 两百多像素,而空态是「插画 96 + 标题 + 说明 + 主按钮」一整列 —— 直接 `Center`
/// 会抛 `RenderFlex overflowed`(紫黑条)。这是布局兜底,不是视觉的一部分。
class _CenteredScrollable extends StatelessWidget {
  const _CenteredScrollable({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) => SingleChildScrollView(
        child: ConstrainedBox(
          constraints: BoxConstraints(minHeight: constraints.maxHeight),
          child: Center(
            child: Padding(
              padding: EdgeInsets.all(tokens.space24),
              child: child,
            ),
          ),
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
    return _CenteredScrollable(
      child: EmberEmpty(
        illustration: const DiscoveryIllustration(
          DiscoveryIllustrationKind.profileIncomplete,
        ),
        title: '完善资料后就能开始滑卡',
        description: '还差:${profile.missingFields.map(missingFieldLabel).join('、')}',
        actionLabel: '去完善',
        actionKey: const Key('discovery.goOnboarding'),
        onAction: () => context.go('/onboarding'),
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
      EmberToast.show(context, likeQuotaExhaustedHint);
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
        EmberToast.show(context,
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
      if (context.mounted) EmberToast.show(context, '已撤销');
    } on ApiException catch (error) {
      if (error.code == undoSwipeUnavailableCode) {
        ref.read(swipeUndoProvider.notifier).forget();
        if (context.mounted) EmberToast.show(context, '没有可撤销的操作');
        return;
      }
      if (context.mounted) EmberToast.show(context, error.message);
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
      error: (error, _) => _ErrorView(
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
                // 卡照片 → 资料页的 Hero(E-5.4 落地):tag 与卡面照片层、
                // 资料页头图三处同名,资料页的 loading 骨架也带同名 Hero,
                // 所以首帧就能找到落点(否则 Hero 只在 push 后一帧扫描,永远不飞)。
                onOpenProfile: (candidate) => context.push(
                  '/users/${candidate.userId}',
                  extra: 'photo-user-${candidate.userId}',
                ),
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
    return _CenteredScrollable(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          EmberEmpty(
            illustration: const DiscoveryIllustration(
              DiscoveryIllustrationKind.emptyNearby,
            ),
            title: '附近暂时没有新的人了',
            description: '过会儿再来看看吧',
            actionLabel: '刷新',
            actionKey: const Key('discovery.refresh'),
            onAction: onRefresh,
          ),
          if (undo != null) ...[
            SizedBox(height: tokens.space16),
            undo,
          ],
        ],
      ),
    );
  }
}

/// 「筛选」入口(批次 S):[EmberChip],已生效时切到选中态,提示「现在不是默认池子」。
///
/// 点开面板 → 拿到用户选好的筛选(或重置)→ 写进 [discoveryFilterProvider];
/// 筛选态一变,候选池 provider 会自己重拉,这里不用手动 reload。
class _FilterEntry extends ConsumerWidget {
  const _FilterEntry();

  Future<void> _open(BuildContext context, WidgetRef ref) async {
    // 面板默认值来自偏好;偏好随 `GET /users/me` 一起来,不必再单独拉一次
    final preference = ref.read(profileProvider).value?.preference ?? const Preference();
    final picked = await showDiscoveryFilterSheet(
      context,
      preference: preference,
      initial: ref.read(discoveryFilterProvider),
    );
    if (picked == null) return; // 用户直接关掉面板:筛选态不变
    ref.read(discoveryFilterProvider.notifier).apply(picked);
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final active = !ref.watch(discoveryFilterProvider).isEmpty;
    return EmberChip(
      key: const Key('discovery.filter'),
      label: '筛选',
      icon: PhosphorIconsRegular.slidersHorizontal,
      selected: active,
      // 选中态自己会读「筛选,已选中」;这里只补「有筛选在生效」这层语义。
      semanticLabel: active ? '筛选，已生效' : '筛选',
      onTap: () => _open(context, ref),
    );
  }
}

/// 发现页右上角入口:图标 + 文案 + 角标;窄屏(<360dp)只留图标,靠 Semantics 读屏。
///
/// 图标口径(§6):未选中 = Regular + `text.tertiary`;有计数时切 **Fill + `brand.default`**
/// —— 那正是「选中 / 未读」那一行,计数本身就说明有内容等着看。
class _TopEntry extends StatelessWidget {
  const _TopEntry({
    required this.entryKey,
    required this.icon,
    required this.selectedIcon,
    required this.label,
    required this.count,
    required this.onTap,
  });

  final Key entryKey;
  final IconData icon;
  final IconData selectedIcon;
  final String label;
  final int count;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    final showLabel = MediaQuery.sizeOf(context).width >= 360;
    final active = count > 0;
    final semantic = active ? '$label，$count 人' : label;
    return EmberPressable(
      key: entryKey,
      onTap: onTap,
      pressedScale: 0.97,
      borderRadius: BorderRadius.circular(tokens.radiusPill),
      semanticLabel: semantic,
      builder: (context, state) => SizedBox(
        // 热区 ≥48×48(§8.4):图标本体 20,靠内边距把可点区域撑起来。
        height: tokens.sizeTouchApp,
        child: Padding(
          padding: EdgeInsets.symmetric(horizontal: tokens.space8),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(
                active ? selectedIcon : icon,
                size: tokens.sizeIcon20,
                color: active ? colors.brandDefault : colors.textTertiary,
              ),
              if (showLabel) ...[
                SizedBox(width: tokens.space4),
                Text(
                  label,
                  style: AppText.caption.copyWith(color: colors.textSecondary),
                ),
              ],
              if (active) ...[
                SizedBox(width: tokens.space4),
                // 计数已经写进外层 `Semantics(label:)`(「喜欢我的人，3 人」),
                // 角标自己再播一次会重复,所以只让它出画面、不出声。
                ExcludeSemantics(child: EmberBadge(count: count)),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
