import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_exception.dart';
import '../../core/format.dart';
import '../../core/theme/heart_theme_context.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/widgets/app_avatar.dart';
import '../../core/widgets/app_empty_state.dart';
import '../../core/widgets/app_error_view.dart';
import '../../core/widgets/app_list_row.dart';
import '../../core/widgets/app_list_skeleton.dart';
import '../../core/widgets/app_sub_page_bar.dart';
import '../../core/widgets/heart_ripple.dart';
import 'post_likes_controller.dart';

/// 点赞列表(`/posts/:id/likes`):谁点了赞 —— 头像 + 昵称 + 相对时间,点行进资料页。
///
/// 入口是动态卡上**点赞数字**那一块(图标区仍是点赞/取消),见 `widgets/post_card.dart`。
class PostLikesPage extends ConsumerStatefulWidget {
  const PostLikesPage({super.key, required this.postId});

  final int postId;

  @override
  ConsumerState<PostLikesPage> createState() => _PostLikesPageState();
}

class _PostLikesPageState extends ConsumerState<PostLikesPage> {
  final _scroll = ScrollController();

  @override
  void initState() {
    super.initState();
    _scroll.addListener(() {
      if (_scroll.position.extentAfter < 300) {
        ref.read(postLikesProvider(widget.postId).notifier).loadMore();
      }
    });
  }

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.heart;
    final likes = ref.watch(postLikesProvider(widget.postId));
    return Scaffold(
      backgroundColor: colors.bgPage,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            const AppSubPageBar(
              title: '点赞',
              backKey: Key('postLikes.back'),
            ),
            Expanded(
              child: likes.when(
                loading: () => const AppListSkeleton(key: Key('postLikes.skeleton')),
                error: (error, _) => AppErrorView(
                  message: error is ApiException ? error.message : '加载失败,请重试',
                  retryKey: const Key('postLikes.retry'),
                  onRetry: () =>
                      ref.invalidate(postLikesProvider(widget.postId)),
                ),
                data: (items) => items.isEmpty
                    ? const Center(
                        child: AppEmptyState(
                          key: Key('postLikes.empty'),
                          mark: HeartRipple(),
                          title: '还没有人点赞',
                          description: '第一个喜欢的人,往往就差一个赞',
                        ),
                      )
                    : ListView.separated(
                        key: const Key('postLikes.list'),
                        controller: _scroll,
                        padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
                        itemCount: items.length,
                        separatorBuilder: (_, _) => Divider(
                          height: 1,
                          indent: 72,
                          color: colors.divider,
                        ),
                        itemBuilder: (context, index) {
                          final user = items[index];
                          return AppListRow(
                            key: Key('postLikes.row.${user.userId}'),
                            avatar: AppAvatar(
                              size: 44,
                              imageUrl: user.avatarUrl,
                              fallbackText: user.nickname,
                            ),
                            title: user.nickname,
                            subtitle: formatPostTime(user.likedAt),
                            onTap: () => context.push('/users/${user.userId}'),
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
