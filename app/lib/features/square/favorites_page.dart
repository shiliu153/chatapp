import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_exception.dart';
import '../../core/theme/heart_theme_context.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/widgets/app_empty_state.dart';
import '../../core/widgets/app_error_view.dart';
import '../../core/widgets/app_sub_page_bar.dart';
import '../../core/widgets/app_toast.dart';
import '../chat/widgets/photo_viewer.dart';
import '../presence/presence_controller.dart';
import '../profile/profile_controller.dart';
import 'feed_repository.dart';
import 'models.dart';
import 'post_actions.dart';
import 'square_controller.dart';
import 'widgets/post_card.dart';
import 'widgets/square_skeleton.dart';

/// 我的收藏(`/favorites`):按收藏时间倒序的动态卡流,不参与 Hero。
///
/// 收藏是**私密书签**:不给作者发通知、不产生灰条,所以这里除了「取消收藏」
/// 之外没有任何对外动作。
class FavoritesPage extends ConsumerStatefulWidget {
  const FavoritesPage({super.key});

  @override
  ConsumerState<FavoritesPage> createState() => _FavoritesPageState();
}

class _FavoritesPageState extends ConsumerState<FavoritesPage> {
  final _scroll = ScrollController();

  @override
  void initState() {
    super.initState();
    _scroll.addListener(() {
      if (_scroll.position.extentAfter < 300) {
        ref.read(favoritesProvider.notifier).loadMore();
      }
    });
  }

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _toggleFavorite(Post post) async {
    final wasFavorited = post.isFavorited;
    try {
      await ref.read(favoritesProvider.notifier).toggleFavorite(post);
      if (!mounted) return;
      AppToast.show(context, wasFavorited ? '已取消收藏' : '已收藏');
    } on ApiException catch (error) {
      if (mounted) AppToast.show(context, error.message);
    }
  }

  Future<void> _deletePost(Post post) async {
    final confirmed = await confirmDeletePost(context);
    if (!confirmed || !mounted) return;
    try {
      await ref.read(feedRepositoryProvider).deletePost(post.id);
      await ref.read(favoritesProvider.notifier).reload();
      ref.invalidate(squareProvider);
      ref.invalidate(myPostsProvider);
      if (mounted) AppToast.show(context, '已删除');
    } on ApiException catch (error) {
      if (mounted) AppToast.show(context, error.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.heart;
    final posts = ref.watch(favoritesProvider);
    final presenceById = ref.watch(presenceProvider);
    final myId = ref.watch(profileProvider).value?.userId;
    return Scaffold(
      backgroundColor: colors.bgPage,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            const AppSubPageBar(
              title: '我的收藏',
              backKey: Key('favorites.back'),
            ),
            Expanded(
              child: posts.when(
                loading: () => const Padding(
                  padding: EdgeInsets.symmetric(horizontal: AppSpacing.pageH),
                  child: SquareSkeleton(key: Key('favorites.skeleton')),
                ),
                error: (error, _) => AppErrorView(
                  message: apiMessageOf(error),
                  retryKey: const Key('favorites.retry'),
                  onRetry: () => ref.invalidate(favoritesProvider),
                ),
                data: (items) => items.isEmpty
                    ? const Center(
                        child: AppEmptyState(
                          key: Key('favorites.empty'),
                          emoji: '🔖',
                          title: '还没有收藏',
                          description: '在动态的「···」里点收藏,想回看的都在这里',
                        ),
                      )
                    : ListView.separated(
                        key: const Key('favorites.list'),
                        controller: _scroll,
                        padding: const EdgeInsets.fromLTRB(AppSpacing.pageH,
                            AppSpacing.xs, AppSpacing.pageH, AppSpacing.xxl),
                        itemCount: items.length,
                        separatorBuilder: (_, _) =>
                            const SizedBox(height: AppSpacing.cardGap),
                        itemBuilder: (context, index) {
                          final post = items[index];
                          return PostCard(
                            post: post,
                            isMine: post.author.userId == myId,
                            online:
                                presenceById[post.author.userId]?.online == true,
                            // 二级页无飞行源:不参与任何 Hero(附录 C.7)
                            onTapAuthor: post.author.userId == myId
                                ? null
                                : () => context.push('/users/${post.author.userId}'),
                            // 详情页里可能取消了收藏:回来后重拉一页,
                            // 已取消的条目不该继续留在「我的收藏」里
                            onTap: () async {
                              await context.push('/posts/${post.id}');
                              if (mounted) {
                                await ref
                                    .read(favoritesProvider.notifier)
                                    .reload();
                              }
                            },
                            onTapLikes: () =>
                                context.push('/posts/${post.id}/likes'),
                            onOpenImage: (i) => openPhotoViewer(context,
                                urls: post.images, initialIndex: i),
                            menuAction: (action) => switch (action) {
                              'favorite' || 'unfavorite' => _toggleFavorite(post),
                              'delete' => _deletePost(post),
                              _ => reportPostFromSheet(context, ref, post.id),
                            },
                          );
                        },
                      ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
