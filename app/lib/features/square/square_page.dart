import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_exception.dart';
import '../../core/theme/heart_theme_context.dart';
import '../../core/theme/app_gradients.dart';
import '../../core/theme/app_radius.dart';
import '../../core/theme/app_shadows.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/theme/app_typography.dart';
import '../../core/widgets/app_button.dart';
import '../../core/widgets/app_empty_state.dart';
import '../../core/widgets/app_error_view.dart';
import '../../core/widgets/app_toast.dart';
import '../../core/widgets/heart_ripple.dart';
import '../chat/widgets/photo_viewer.dart';
import '../presence/presence_controller.dart';
import '../profile/profile_controller.dart';
import 'feed_repository.dart';
import 'models.dart';
import 'post_actions.dart';
import 'post_detail_args.dart';
import 'square_controller.dart';
import 'widgets/post_card.dart';
import 'widgets/square_skeleton.dart';

/// 广场顶部的两个 tab(批次 I):推荐 = 现有 `/posts`,关注 = `/feed/following`。
enum SquareTab { recommend, following }

/// 广场 Tab(附录 D):大标题页壳 + 白卡流 + 渐变 FAB。
///
/// 批次 I 起顶部多一排「推荐 / 关注」tab:两个 tab 的数据链路同构
/// (见 `PostFeedController`),切换时换 provider,不重建页面。
class SquarePage extends ConsumerStatefulWidget {
  const SquarePage({super.key});

  @override
  ConsumerState<SquarePage> createState() => _SquarePageState();
}

class _SquarePageState extends ConsumerState<SquarePage> {
  final _scroll = ScrollController();

  /// 当前选中的 tab;默认「推荐」(与改造前行为一致)。
  SquareTab _tab = SquareTab.recommend;

  /// 正在飞整卡 Hero 的动态 id;null = 无飞行。
  /// 互斥不变式见 spec §5:飞行期间该卡头像 Hero 让位,返回后还原。
  int? _cardHeroPostId;

  /// 当前 tab 对应的控制器(两个 tab 共用 [PostFeedController] 接口)。
  PostFeedController get _feed => switch (_tab) {
        SquareTab.recommend => ref.read(squareProvider.notifier),
        SquareTab.following => ref.read(followingProvider.notifier),
      };

  @override
  void initState() {
    super.initState();
    _scroll.addListener(() {
      if (_scroll.position.extentAfter < 300) {
        _feed.loadMore();
      }
    });
  }

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _openDetail(Post post) async {
    // 飞行中忽略新点击(防快速连点把飞行中的 Hero 卸载)
    if (_cardHeroPostId != null) return;
    setState(() => _cardHeroPostId = post.id);
    try {
      await context.push(
        '/posts/${post.id}',
        extra: PostDetailArgs(
          heroTag: 'card-post-${post.id}',
          seed: post,
        ),
      );
    } finally {
      if (mounted) setState(() => _cardHeroPostId = null);
    }
  }

  Future<void> _toggleLike(Post post) async {
    try {
      await _feed.toggleLike(post);
    } on ApiException catch (error) {
      if (mounted) AppToast.show(context, error.message);
    }
  }

  Future<void> _deletePost(Post post) async {
    final confirmed = await confirmDeletePost(context);
    if (!confirmed || !mounted) return;
    try {
      await ref.read(feedRepositoryProvider).deletePost(post.id);
      await _feed.reload();
      ref.invalidate(myPostsProvider);
      if (mounted) AppToast.show(context, '已删除');
    } on ApiException catch (error) {
      if (mounted) AppToast.show(context, error.message);
    }
  }

  /// 切 tab:清掉滚动位置,否则从「推荐」翻到第 5 页再切「关注」会落在列表中间。
  void _switchTab(SquareTab tab) {
    if (tab == _tab) return;
    setState(() => _tab = tab);
    if (_scroll.hasClients) _scroll.jumpTo(0);
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.heart;
    final posts = switch (_tab) {
      SquareTab.recommend => ref.watch(squareProvider),
      SquareTab.following => ref.watch(followingProvider),
    };
    final presenceById = ref.watch(presenceProvider);
    final myId = ref.watch(profileProvider).value?.userId;
    final isFollowingTab = _tab == SquareTab.following;
    return Scaffold(
      backgroundColor: colors.bgPage,
      // FAB 上移 84:默认 endFloat 会压在悬浮胶囊底栏(64+10)上(附录 D)
      floatingActionButtonLocation: FloatingActionButtonLocation.endFloat,
      floatingActionButton: Padding(
        padding: const EdgeInsets.only(bottom: 84),
        child: _ComposeFab(
          onTap: () => context.push('/posts/compose'),
        ),
      ),
      body: SafeArea(
        bottom: false,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(
                  AppSpacing.pageH, AppSpacing.lg, AppSpacing.pageH, AppSpacing.sm),
              child: Text('广场', style: AppText.display.copyWith(color: colors.text1)),
            ),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: AppSpacing.pageH),
              child: _SquareTabs(value: _tab, onChanged: _switchTab),
            ),
            const SizedBox(height: AppSpacing.sm),
            Expanded(
              child: posts.when(
                loading: () => const Padding(
                  padding: EdgeInsets.symmetric(horizontal: AppSpacing.pageH),
                  child: SquareSkeleton(),
                ),
                error: (error, _) => AppErrorView(
                  message: apiMessageOf(error),
                  retryKey: const Key('square.retry'),
                  onRetry: () => switch (_tab) {
                    SquareTab.recommend => ref.invalidate(squareProvider),
                    SquareTab.following => ref.invalidate(followingProvider),
                  },
                ),
                data: (items) {
                  ref.read(presenceProvider.notifier).track(
                      isFollowingTab ? 'square:following' : 'square',
                      [for (final post in items) post.author.userId]);
                  return items.isEmpty
                      ? Center(
                          child: AppEmptyState(
                            mark: const HeartRipple(),
                            title: isFollowingTab ? '还没有关注的人' : '还没有动态',
                            description: isFollowingTab
                                ? '去「推荐」看看,关注感兴趣的人'
                                : '发一条,让大家认识你',
                            action: isFollowingTab
                                ? AppButton(
                                    key: const Key('square.empty.toRecommend'),
                                    label: '去推荐看看',
                                    variant: AppButtonVariant.secondary,
                                    onPressed: () => _switchTab(SquareTab.recommend),
                                  )
                                : AppButton(
                                    key: const Key('square.compose'),
                                    label: '发布第一条',
                                    variant: AppButtonVariant.secondary,
                                    onPressed: () => context.push('/posts/compose'),
                                  ),
                          ),
                        )
                      : RefreshIndicator(
                          backgroundColor: colors.bgCard,
                          color: colors.brand,
                          onRefresh: _feed.reload,
                          child: ListView.separated(
                            key: Key(isFollowingTab
                                ? 'square.following.list'
                                : 'square.list'),
                            controller: _scroll,
                            padding: const EdgeInsets.fromLTRB(AppSpacing.pageH,
                                AppSpacing.xs, AppSpacing.pageH, 96),
                            itemCount: items.length,
                            separatorBuilder: (_, _) =>
                                const SizedBox(height: AppSpacing.cardGap),
                            itemBuilder: (context, index) {
                              final post = items[index];
                              // Hero 互斥(附录 D.4):整卡飞行期间该卡头像让位,
                              // 其余卡(与返回后的自己)保持头像 Hero 态
                              final inCardFlight = _cardHeroPostId == post.id;
                              return PostCard(
                                post: post,
                                // tag 按 postId 派生(不是 userId):同作者多卡各得不同 tag
                                heroTag:
                                    inCardFlight ? null : 'avatar-post-${post.id}',
                                isMine: post.author.userId == myId,
                                online:
                                    presenceById[post.author.userId]?.online == true,
                                onTapAuthor: post.author.userId == myId
                                    ? null
                                    : () => context.push('/users/${post.author.userId}',
                                        extra: 'avatar-post-${post.id}'),
                                onToggleLike: () => _toggleLike(post),
                                onTap: () => _openDetail(post),
                                cardHeroTag: inCardFlight
                                    ? 'card-post-${post.id}'
                                    : null,
                                onOpenImage: (i) => openPhotoViewer(context,
                                    urls: post.images, initialIndex: i),
                                menuAction: (action) => action == 'delete'
                                    ? _deletePost(post)
                                    : reportPostFromSheet(context, ref, post.id),
                              );
                            },
                          ),
                        );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// 渐变圆钮 FAB(附录 D):56 圆 + gradientHeart + 主按钮阴影。
class _ComposeFab extends StatelessWidget {
  const _ComposeFab({required this.onTap});

  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = context.heart;
    return Container(
        key: const Key('square.fab'),
        width: 56,
        height: 56,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          gradient: AppGradients.heartOf(colors),
          boxShadow: AppShadows.primaryButton,
        ),
        child: Material(
          color: Colors.transparent,
          child: InkWell(
            customBorder: const CircleBorder(),
            onTap: onTap,
            child: const Icon(Icons.add_rounded, size: 24, color: Colors.white),
          ),
        ),
      );
  }
}

/// 「推荐 / 关注」两段 tab:文字 + 3px 主色下划线(选中)。
///
/// 为什么不用 `AppOptionGroup`:那是 52 高的胶囊分段,放在大标题下会把列表
/// 顶下去一整屏;这里沿用「心跳」§4 的 tab 形态(文字 + 短下划线),高度 44。
class _SquareTabs extends StatelessWidget {
  const _SquareTabs({required this.value, required this.onChanged});

  final SquareTab value;
  final ValueChanged<SquareTab> onChanged;

  static const _tabs = <(SquareTab, String, String)>[
    (SquareTab.recommend, '推荐', 'square.tab.recommend'),
    (SquareTab.following, '关注', 'square.tab.following'),
  ];

  @override
  Widget build(BuildContext context) {
    final colors = context.heart;
    return Row(
      children: [
        for (final (tab, label, keyName) in _tabs)
          Padding(
            padding: const EdgeInsets.only(right: AppSpacing.xl),
            child: GestureDetector(
              key: Key(keyName),
              behavior: HitTestBehavior.opaque,
              onTap: () => onChanged(tab),
              child: Semantics(
                selected: value == tab,
                button: true,
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Padding(
                      padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
                      child: Text(
                        label,
                        style: AppText.body.copyWith(
                          color: value == tab ? colors.text1 : colors.text2,
                          fontWeight:
                              value == tab ? FontWeight.w700 : FontWeight.w500,
                        ),
                      ),
                    ),
                    Container(
                      height: 3,
                      width: 20,
                      decoration: BoxDecoration(
                        color: value == tab ? colors.brand : Colors.transparent,
                        borderRadius: BorderRadius.circular(AppRadius.full),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
      ],
    );
  }
}
