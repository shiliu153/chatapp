import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_exception.dart';
import '../../core/theme/tokens.g.dart' as tokens;
import '../../core/ui/ember_ui.dart';
import '../chat/widgets/photo_viewer.dart';
import 'models.dart';
import 'post_actions.dart';
import 'square_controller.dart';
import 'widgets/post_card.dart';
import 'widgets/square_illustration.dart';
import 'widgets/square_skeleton.dart';

/// 我的动态(附录 D):二级页顶栏 + 复用动态卡(不参与 Hero)。
///
/// E-5.6d 只换皮(page spec §1 D 组):顶栏换 [`EmberPageScaffold`](§9.4)、
/// 空 / 错态换 [`EmberEmpty`] + unDraw(空态的主按钮从 `AppButton` 换
/// [`EmberButton`],Key 不变)、骨架换 [`EmberSkeleton`]、反馈换 [`EmberToast`];
/// `myPostsProvider` 与卡片的业务逻辑一行没动。
class MyPostsPage extends ConsumerStatefulWidget {
  /// 构造我的动态页。
  const MyPostsPage({super.key});

  @override
  ConsumerState<MyPostsPage> createState() => _MyPostsPageState();
}

class _MyPostsPageState extends ConsumerState<MyPostsPage> {
  final _scroll = ScrollController();

  @override
  void initState() {
    super.initState();
    _scroll.addListener(() {
      if (_scroll.position.extentAfter < 300) {
        ref.read(myPostsProvider.notifier).loadMore();
      }
    });
  }

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _deletePost(Post post) async {
    final confirmed = await confirmDeletePost(context);
    if (!confirmed || !mounted) return;
    try {
      await ref.read(myPostsProvider.notifier).remove(post.id);
      ref.invalidate(squareProvider);
      if (mounted) EmberToast.show(context, '已删除');
    } on ApiException catch (error) {
      if (mounted) EmberToast.show(context, error.message);
    }
  }

  /// 自己的动态也能收藏(书签语义,后端允许);乐观翻转在控制器里。
  Future<void> _toggleFavorite(Post post) async {
    final wasFavorited = post.isFavorited;
    try {
      await ref.read(myPostsProvider.notifier).toggleFavorite(post);
      ref.invalidate(favoritesProvider);
      if (!mounted) return;
      EmberToast.show(context, wasFavorited ? '已取消收藏' : '已收藏');
    } on ApiException catch (error) {
      if (mounted) EmberToast.show(context, error.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    final posts = ref.watch(myPostsProvider);
    return EmberPageScaffold(
      title: '我的动态',
      backKey: const Key('myPosts.back'),
      body: posts.when(
        loading: () => const SquareSkeleton(key: Key('myPosts.skeleton')),
        error: (error, _) => _Centered(
          child: EmberEmpty(
            illustration:
                const SquareIllustration(SquareIllustrationKind.loadFailed),
            title: '加载失败',
            description: apiMessageOf(error),
            actionLabel: '重试',
            actionKey: const Key('myPosts.retry'),
            onAction: () => ref.invalidate(myPostsProvider),
          ),
        ),
        data: (items) => items.isEmpty
            ? _Centered(
                child: EmberEmpty(
                  key: const Key('myPosts.empty'),
                  illustration: const SquareIllustration(
                    SquareIllustrationKind.emptyFeed,
                  ),
                  title: '还没发过动态',
                  description: '第一句想说的话,发在广场',
                  actionLabel: '去发布',
                  actionKey: const Key('myPosts.compose'),
                  onAction: () => context.push('/posts/compose'),
                ),
              )
            : ListView.separated(
                key: const Key('myPosts.list'),
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
                    isMine: true,
                    // 从我的页进入无飞行源:不参与任何 Hero(附录 C.7)
                    onTap: () => context.push('/posts/${post.id}'),
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
