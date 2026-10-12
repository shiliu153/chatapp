import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_exception.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/theme/app_typography.dart';
import '../../core/widgets/app_button.dart';
import '../../core/widgets/app_empty_state.dart';
import '../../core/widgets/app_error_view.dart';
import '../../core/widgets/app_toast.dart';
import '../chat/widgets/photo_viewer.dart';
import 'models.dart';
import 'post_actions.dart';
import 'square_controller.dart';
import 'widgets/post_card.dart';
import 'widgets/square_skeleton.dart';

/// 我的动态(附录 D):二级页顶栏 + 复用动态卡(不参与 Hero)。
class MyPostsPage extends ConsumerStatefulWidget {
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
      if (mounted) AppToast.show(context, '已删除');
    } on ApiException catch (error) {
      if (mounted) AppToast.show(context, error.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    final posts = ref.watch(myPostsProvider);
    return Scaffold(
      backgroundColor: AppColors.bgPage,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            _SubPageBar(
              title: '我的动态',
              backKey: const Key('myPosts.back'),
            ),
            Expanded(
              child: posts.when(
                loading: () => const Padding(
                  padding: EdgeInsets.symmetric(horizontal: AppSpacing.pageH),
                  child: SquareSkeleton(key: Key('myPosts.skeleton')),
                ),
                error: (error, _) => AppErrorView(
                  message: apiMessageOf(error),
                  retryKey: const Key('myPosts.retry'),
                  onRetry: () => ref.invalidate(myPostsProvider),
                ),
                data: (items) => items.isEmpty
                    ? Center(
                        child: AppEmptyState(
                          emoji: '📝',
                          title: '还没发过动态',
                          description: '第一句想说的话,发在广场',
                          action: AppButton(
                            key: const Key('myPosts.compose'),
                            label: '去发布',
                            variant: AppButtonVariant.secondary,
                            onPressed: () => context.push('/posts/compose'),
                          ),
                        ),
                      )
                    : ListView.separated(
                        key: const Key('myPosts.list'),
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
                            isMine: true,
                            // 从我的页进入无飞行源:不参与任何 Hero(附录 C.7)
                            onTap: () => context.push('/posts/${post.id}'),
                            onOpenImage: (i) => openPhotoViewer(context,
                                urls: post.images, initialIndex: i),
                            menuAction: (action) => action == 'delete'
                                ? _deletePost(post)
                                : reportPostFromSheet(context, ref, post.id),
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

/// 二级页顶栏(§5.2):高 52,返回 + 居中标题。
/// Task 6 的详情页会复制同款(两页各自私有,不抽共享组件——两处共 20 行)。
class _SubPageBar extends StatelessWidget {
  const _SubPageBar({
    required this.title,
    required this.backKey,
  });

  final String title;
  final Key backKey;

  static const _height = 52.0;

  @override
  Widget build(BuildContext context) => SizedBox(
        height: _height,
        child: Stack(
          alignment: Alignment.center,
          children: [
            Text(title,
                style: AppText.subtitle.copyWith(
                    fontSize: 17, color: AppColors.text1)), // 17/w600(§5.2)
            Positioned(
              left: 0,
              top: 0,
              bottom: 0,
              child: IconButton(
                key: backKey,
                onPressed: () => Navigator.of(context).maybePop(),
                icon: const Icon(Icons.arrow_back_ios_new_rounded,
                    size: 22, color: AppColors.text1),
              ),
            ),
          ],
        ),
      );
}
