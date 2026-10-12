import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_exception.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_gradients.dart';
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

/// 广场 Tab(附录 D):大标题页壳 + 白卡流 + 渐变 FAB。
class SquarePage extends ConsumerStatefulWidget {
  const SquarePage({super.key});

  @override
  ConsumerState<SquarePage> createState() => _SquarePageState();
}

class _SquarePageState extends ConsumerState<SquarePage> {
  final _scroll = ScrollController();

  /// 正在飞整卡 Hero 的动态 id;null = 无飞行。
  /// 互斥不变式见 spec §5:飞行期间该卡头像 Hero 让位,返回后还原。
  int? _cardHeroPostId;

  @override
  void initState() {
    super.initState();
    _scroll.addListener(() {
      if (_scroll.position.extentAfter < 300) {
        ref.read(squareProvider.notifier).loadMore();
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
      await ref.read(squareProvider.notifier).toggleLike(post);
    } on ApiException catch (error) {
      if (mounted) AppToast.show(context, error.message);
    }
  }

  Future<void> _deletePost(Post post) async {
    final confirmed = await confirmDeletePost(context);
    if (!confirmed || !mounted) return;
    try {
      await ref.read(feedRepositoryProvider).deletePost(post.id);
      await ref.read(squareProvider.notifier).reload();
      ref.invalidate(myPostsProvider);
      if (mounted) AppToast.show(context, '已删除');
    } on ApiException catch (error) {
      if (mounted) AppToast.show(context, error.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    final posts = ref.watch(squareProvider);
    final presenceById = ref.watch(presenceProvider);
    final myId = ref.watch(profileProvider).value?.userId;
    return Scaffold(
      backgroundColor: AppColors.bgPage,
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
                  AppSpacing.pageH, AppSpacing.lg, AppSpacing.pageH, AppSpacing.md),
              child: Text('广场', style: AppText.display.copyWith(color: AppColors.text1)),
            ),
            Expanded(
              child: posts.when(
                loading: () => const Padding(
                  padding: EdgeInsets.symmetric(horizontal: AppSpacing.pageH),
                  child: SquareSkeleton(),
                ),
                error: (error, _) => AppErrorView(
                  message: apiMessageOf(error),
                  retryKey: const Key('square.retry'),
                  onRetry: () => ref.invalidate(squareProvider),
                ),
                data: (items) {
                  ref.read(presenceProvider.notifier).track(
                      'square', [for (final post in items) post.author.userId]);
                  return items.isEmpty
                      ? Center(
                          child: AppEmptyState(
                            mark: const HeartRipple(),
                            title: '还没有动态',
                            description: '发一条,让大家认识你',
                            action: AppButton(
                              key: const Key('square.compose'),
                              label: '发布第一条',
                              variant: AppButtonVariant.secondary,
                              onPressed: () => context.push('/posts/compose'),
                            ),
                          ),
                        )
                      : RefreshIndicator(
                          backgroundColor: AppColors.bgCard,
                          color: AppColors.brand,
                          onRefresh: () =>
                              ref.read(squareProvider.notifier).reload(),
                          child: ListView.separated(
                            key: const Key('square.list'),
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
  Widget build(BuildContext context) => Container(
        key: const Key('square.fab'),
        width: 56,
        height: 56,
        decoration: const BoxDecoration(
          shape: BoxShape.circle,
          gradient: AppGradients.heart,
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
