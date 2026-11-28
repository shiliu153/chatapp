import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_exception.dart';
import '../../core/theme/tokens.g.dart' as tokens;
import '../../core/ui/ember_ui.dart';
import '../chat/widgets/photo_viewer.dart';
import '../presence/presence_controller.dart';
import '../profile/profile_controller.dart';
import '../shell/shell_tab.dart';
import 'feed_repository.dart';
import 'models.dart';
import 'post_actions.dart';
import 'square_controller.dart';
import 'widgets/post_card.dart';
import 'widgets/square_illustration.dart';
import 'widgets/square_skeleton.dart';

/// 我的收藏(`/favorites`):按收藏时间倒序的动态卡流,不参与 Hero。
///
/// 收藏是**私密书签**:不给作者发通知、不产生灰条,所以这里除了「取消收藏」
/// 之外没有任何对外动作。
///
/// E-5.6d 只换皮(page spec §1 D 组):顶栏换 [`EmberPageScaffold`](§9.4)、
/// 空 / 错态换 [`EmberEmpty`] + unDraw、骨架换 [`EmberSkeleton`]、
/// 反馈换 [`EmberToast`];`favoritesProvider` / `feed_repository` 与卡片的
/// 业务逻辑一行没动。
class FavoritesPage extends ConsumerStatefulWidget {
  /// 构造我的收藏页。
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
      EmberToast.show(context, wasFavorited ? '已取消收藏' : '已收藏');
    } on ApiException catch (error) {
      if (mounted) EmberToast.show(context, error.message);
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
      if (mounted) EmberToast.show(context, '已删除');
    } on ApiException catch (error) {
      if (mounted) EmberToast.show(context, error.message);
    }
  }

  /// 空态的「去回声看看」:切到回声 tab 再退回上一层(收藏是从「我」里点进来的
  /// 二级页,留在栈上只会让用户看到同一个空态)。
  void _goSquare() {
    ref.read(shellTabIndexProvider.notifier).select(ShellTab.square);
    Navigator.of(context).maybePop();
  }

  @override
  Widget build(BuildContext context) {
    final posts = ref.watch(favoritesProvider);
    final presenceById = ref.watch(presenceProvider);
    final myId = ref.watch(profileProvider).value?.userId;
    return EmberPageScaffold(
      title: '我的收藏',
      backKey: const Key('favorites.back'),
      body: posts.when(
        loading: () => const SquareSkeleton(key: Key('favorites.skeleton')),
        error: (error, _) => _Centered(
          child: EmberEmpty(
            illustration:
                const SquareIllustration(SquareIllustrationKind.loadFailed),
            title: '加载失败',
            description: apiMessageOf(error),
            actionLabel: '重试',
            actionKey: const Key('favorites.retry'),
            onAction: () => ref.invalidate(favoritesProvider),
          ),
        ),
        data: (items) => items.isEmpty
            ? _Centered(
                child: EmberEmpty(
                  key: const Key('favorites.empty'),
                  illustration: const SquareIllustration(
                    SquareIllustrationKind.emptyFeed,
                  ),
                  title: '还没有收藏',
                  description: '在动态的「···」里点收藏,想回看的都在这里',
                  actionLabel: '去回声看看',
                  actionKey: const Key('favorites.empty.toSquare'),
                  onAction: _goSquare,
                ),
              )
            : ListView.separated(
                key: const Key('favorites.list'),
                controller: _scroll,
                padding: EdgeInsets.fromLTRB(
                  tokens.space20,
                  tokens.space4,
                  tokens.space20,
                  tokens.space24,
                ),
                itemCount: items.length,
                separatorBuilder: (_, _) => SizedBox(height: tokens.space12),
                itemBuilder: (context, index) {
                  final post = items[index];
                  return PostCard(
                    post: post,
                    isMine: post.author.userId == myId,
                    online: presenceById[post.author.userId]?.online == true,
                    // 二级页无飞行源:不参与任何 Hero(附录 C.7)
                    onTapAuthor: post.author.userId == myId
                        ? null
                        : () => context.push('/users/${post.author.userId}'),
                    // 详情页里可能取消了收藏:回来后重拉一页,
                    // 已取消的条目不该继续留在「我的收藏」里
                    onTap: () async {
                      await context.push('/posts/${post.id}');
                      if (mounted) {
                        await ref.read(favoritesProvider.notifier).reload();
                      }
                    },
                    onTapLikes: () => context.push('/posts/${post.id}/likes'),
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
    );
  }
}

/// 空 / 错两态居中且可滚动(小屏 + 大字号下不溢出)。
class _Centered extends StatelessWidget {
  const _Centered({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) => SingleChildScrollView(
        child: ConstrainedBox(
          constraints: BoxConstraints(minHeight: constraints.maxHeight),
          child: Center(
            child: Padding(
              padding: EdgeInsets.symmetric(vertical: tokens.space24),
              child: child,
            ),
          ),
        ),
      ),
    );
  }
}
