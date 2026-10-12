import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_exception.dart';
import '../../core/format.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_radius.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/theme/app_typography.dart';
import '../../core/widgets/app_avatar.dart';
import '../../core/widgets/app_empty_state.dart';
import '../../core/widgets/app_error_view.dart';
import '../../core/widgets/app_sub_page_bar.dart';
import '../../core/widgets/app_toast.dart';
import '../../core/widgets/avatar_hero.dart';
import '../../core/widgets/card_hero.dart';
import '../chat/widgets/photo_viewer.dart';
import '../presence/models.dart';
import '../presence/presence_controller.dart';
import '../profile/profile_controller.dart';
import 'feed_repository.dart';
import 'models.dart';
import 'post_actions.dart';
import 'post_detail_args.dart';
import 'post_detail_controller.dart';
import 'square_controller.dart';
import 'widgets/post_card.dart';
import 'widgets/post_detail_skeleton.dart';

/// 动态详情(附录 D):自绘顶栏 + 动态卡 + 评论流 + 底部紧凑输入栏(44)。
class PostDetailPage extends ConsumerStatefulWidget {
  const PostDetailPage({super.key, required this.postId, this.args});

  final int postId;

  /// 整卡 Hero 载荷(附录 D);null(我的动态/深链)时无 Hero、骨架起步。
  final PostDetailArgs? args;

  @override
  ConsumerState<PostDetailPage> createState() => _PostDetailPageState();
}

class _PostDetailPageState extends ConsumerState<PostDetailPage> {
  final _input = TextEditingController();
  final _focus = FocusNode();
  bool _sending = false;

  @override
  void dispose() {
    _input.dispose();
    _focus.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    final text = _input.text.trim();
    if (text.isEmpty) return;
    setState(() => _sending = true);
    try {
      await ref.read(commentsProvider(widget.postId).notifier).send(text);
      _input.clear();
      ref.invalidate(commentsProvider(widget.postId));      // 评论列表刷新
      ref.invalidate(postDetailProvider(widget.postId));    // 评论数 +1
    } on ApiException catch (error) {
      if (mounted) AppToast.show(context, error.message);
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  Future<void> _toggleLike() async {
    try {
      await ref.read(postDetailProvider(widget.postId).notifier).toggleLike();
    } on ApiException catch (error) {
      if (mounted) AppToast.show(context, error.message);
    }
  }

  Future<void> _deletePost() async {
    final confirmed = await confirmDeletePost(context);
    if (!confirmed || !mounted) return;
    try {
      await ref.read(feedRepositoryProvider).deletePost(widget.postId);
      ref.invalidate(squareProvider);
      ref.invalidate(myPostsProvider);
      if (mounted) context.pop();
    } on ApiException catch (error) {
      if (mounted) AppToast.show(context, error.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    final post = ref.watch(postDetailProvider(widget.postId));
    final comments = ref.watch(commentsProvider(widget.postId));
    final presenceById = ref.watch(presenceProvider);
    final myId = ref.watch(profileProvider).value?.userId;
    final args = widget.args;
    return Scaffold(
      backgroundColor: AppColors.bgPage,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            const AppSubPageBar(
              title: '动态详情',
              backKey: Key('post.back'),
            ),
            Expanded(
              child: post.when(
                loading: () {
                  final seed = args?.seed;
                  if (seed != null) {
                    // Hero 只在 push 后下一帧末扫描一次:loading 也要用 seed
                    // 直出真卡(顶卡带 tag),否则目标侧没 Hero、不飞(附录 D.4)
                    ref.read(presenceProvider.notifier).track(
                        'post:${widget.postId}', [seed.author.userId]);
                    return _Body(
                      post: seed,
                      heroCardTag: args!.heroTag,
                      presenceById: presenceById,
                      myId: myId,
                      comments: comments,
                      onToggleLike: _toggleLike,
                      onOpenImage: (post, i) => openPhotoViewer(context,
                          urls: post.images, initialIndex: i),
                      onMenu: (post, action) => action == 'delete'
                          ? _deletePost()
                          : reportPostFromSheet(context, ref, post.id),
                      onRetryComments: () =>
                          ref.invalidate(commentsProvider(widget.postId)),
                    );
                  }
                  return const Padding(
                    padding: EdgeInsets.symmetric(horizontal: AppSpacing.pageH),
                    child: PostDetailSkeleton(),
                  );
                },
                error: (error, _) => AppErrorView(
                  message: apiMessageOf(error),
                  retryKey: const Key('post.retry'),
                  onRetry: () => ref.invalidate(postDetailProvider(widget.postId)),
                ),
                data: (data) {
                  ref.read(presenceProvider.notifier).track(
                      'post:${widget.postId}', [data.author.userId]);
                  return _Body(
                    post: data,
                    heroCardTag: args?.heroTag,
                    presenceById: presenceById,
                    myId: myId,
                    comments: comments,
                    onToggleLike: _toggleLike,
                    onOpenImage: (post, i) => openPhotoViewer(context,
                        urls: post.images, initialIndex: i),
                    onMenu: (post, action) => action == 'delete'
                        ? _deletePost()
                        : reportPostFromSheet(context, ref, post.id),
                    onRetryComments: () =>
                        ref.invalidate(commentsProvider(widget.postId)),
                  );
                },
              ),
            ),
            _CommentBar(
              input: _input,
              focus: _focus,
              sending: _sending,
              onSend: _send,
            ),
          ],
        ),
      ),
    );
  }
}

/// 详情页正文(seed/data 共用):顶卡 + 评论流。
class _Body extends StatelessWidget {
  const _Body({
    required this.post,
    required this.heroCardTag,
    required this.presenceById,
    required this.myId,
    required this.comments,
    required this.onToggleLike,
    required this.onOpenImage,
    required this.onMenu,
    required this.onRetryComments,
  });

  final Post post;
  final String? heroCardTag;
  final Map<int, Presence> presenceById;
  final int? myId;
  final AsyncValue<List<PostCommentItem>> comments;
  final VoidCallback onToggleLike;
  final void Function(Post post, int index) onOpenImage;
  final void Function(Post post, String action) onMenu;
  final VoidCallback onRetryComments;

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.fromLTRB(
          AppSpacing.pageH, AppSpacing.xs, AppSpacing.pageH, AppSpacing.xxl),
      children: [
        CardHero(
          tag: heroCardTag,
          child: PostCard(
            post: post,
            // Hero 互斥(spec §5):整卡态下头像 Hero 必须让位(SDK 禁嵌套);
            // 无整卡 Hero(我的动态/深链进入)时保留批次④的「头像→资料页」转场
            heroTag:
                heroCardTag == null ? 'avatar-post-${post.id}' : null,
            isMine: post.author.userId == myId,
            online: presenceById[post.author.userId]?.online == true,
            onTapAuthor: post.author.userId == myId
                ? null
                : () => context.push('/users/${post.author.userId}',
                    extra: 'avatar-post-${post.id}'),
            onToggleLike: onToggleLike,
            onOpenImage: (i) => onOpenImage(post, i),
            menuAction: (action) => onMenu(post, action),
            // 详情页里点卡不该再进详情
            onTap: null,
          ),
        ),
        const SizedBox(height: AppSpacing.md),
        comments.when(
          loading: () => const Padding(
            padding: EdgeInsets.all(AppSpacing.xxl),
            child: Center(child: CircularProgressIndicator()),
          ),
          error: (error, _) => Padding(
            padding: const EdgeInsets.all(AppSpacing.xxl),
            child: AppErrorView(
              message: apiMessageOf(error),
              onRetry: onRetryComments,
            ),
          ),
          data: (items) => Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (items.isEmpty)
                const Center(
                  child: AppEmptyState(
                    emoji: '💬',
                    title: '还没有评论',
                    description: '来抢沙发',
                  ),
                ),
              for (var i = 0; i < items.length; i++) ...[
                if (i > 0) const Divider(height: 1, color: AppColors.divider),
                _CommentTile(
                  comment: items[i],
                  heroTag: 'avatar-comment-${items[i].id}',
                  onTapAuthor: items[i].author.userId == myId
                      ? null
                      : () => context.push('/users/${items[i].author.userId}',
                          extra: 'avatar-comment-${items[i].id}'),
                ),
              ],
            ],
          ),
        ),
      ],
    );
  }
}

/// 评论行(附录 D):28 圆头像 + 昵称 13/w600 text2 + 正文 + 时间;行间 1px divider。
class _CommentTile extends StatelessWidget {
  const _CommentTile({required this.comment, this.onTapAuthor, this.heroTag});

  final PostCommentItem comment;
  final VoidCallback? onTapAuthor;

  /// Hero tag(附录 C.7);按评论 id 派生,同页多条评论不会撞。
  final String? heroTag;

  @override
  Widget build(BuildContext context) {
    return Container(
      key: Key('post.comment.${comment.id}'),
      padding: const EdgeInsets.symmetric(vertical: 12),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          AvatarHero(
            tag: heroTag,
            imageUrl: comment.author.avatarUrl,
            fromRadius: AppRadius.full,
            child: GestureDetector(
              key: Key('post.comment.avatar.${comment.id}'),
              behavior: HitTestBehavior.opaque,
              onTap: onTapAuthor ?? () {},
              child: AppAvatar(
                imageUrl: comment.author.avatarUrl,
                size: 28,
                fallbackText: comment.author.nickname,
              ),
            ),
          ),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                GestureDetector(
                  key: Key('post.comment.nickname.${comment.id}'),
                  behavior: HitTestBehavior.opaque,
                  onTap: onTapAuthor ?? () {},
                  child: Text(comment.author.nickname,
                      style: AppText.caption.copyWith(
                          fontWeight: FontWeight.w600, color: AppColors.text2)),
                ),
                const SizedBox(height: 2),
                Text(comment.text,
                    style: AppText.body.copyWith(color: AppColors.text1)),
                const SizedBox(height: 2),
                Text(formatPostTime(comment.createdAt),
                    style: AppText.micro.copyWith(color: AppColors.text3)),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// 底部评论输入栏(附录 D;紧凑输入场景高 44,B.4 例外延伸):
/// R16 白底、1px divider、聚焦 1.5px brand + 光晕;发送纯图标随文字变色。
class _CommentBar extends StatelessWidget {
  const _CommentBar({
    required this.input,
    required this.focus,
    required this.sending,
    required this.onSend,
  });

  final TextEditingController input;
  final FocusNode focus;
  final bool sending;
  final VoidCallback onSend;

  static const _barHeight = 44.0; // 紧凑输入场景(附录 D 修订 B.4)

  @override
  Widget build(BuildContext context) => Container(
        color: AppColors.bgCard,
        child: SafeArea(
          top: false,
          child: Container(
            padding: const EdgeInsets.all(AppSpacing.sm),
            decoration: const BoxDecoration(
              border: Border(top: BorderSide(color: AppColors.divider)),
            ),
            child: Row(
              children: [
                Expanded(
                  child: ListenableBuilder(
                    listenable: Listenable.merge([focus, input]),
                    builder: (context, child) => Container(
                      height: _barHeight,
                      decoration: BoxDecoration(
                        color: AppColors.bgCard,
                        borderRadius: BorderRadius.circular(AppRadius.input),
                        border: Border.all(
                          color:
                              focus.hasFocus ? AppColors.brand : AppColors.divider,
                          width: focus.hasFocus ? 1.5 : 1,
                        ),
                        boxShadow: focus.hasFocus
                            ? [
                                BoxShadow(
                                  color: AppColors.brand.withValues(alpha: .12),
                                  blurRadius: 12,
                                ),
                              ]
                            : null,
                      ),
                      child: child,
                    ),
                    child: TextField(
                      key: const Key('post.comment.input'),
                      controller: input,
                      focusNode: focus,
                      maxLength: 200,
                      style: AppText.body.copyWith(color: AppColors.text1),
                      decoration: InputDecoration(
                        hintText: '说点什么…',
                        hintStyle: AppText.body.copyWith(color: AppColors.text3),
                        counterText: '',
                        border: InputBorder.none,
                        isCollapsed: true,
                        contentPadding:
                            const EdgeInsets.symmetric(horizontal: 14),
                      ),
                      onSubmitted: (_) => onSend(),
                    ),
                  ),
                ),
                ListenableBuilder(
                  listenable: input,
                  builder: (context, _) => IconButton(
                    key: const Key('post.comment.send'),
                    onPressed: sending ? null : onSend,
                    icon: Icon(Icons.send_rounded,
                        size: 24,
                        color: input.text.trim().isEmpty
                            ? AppColors.text3
                            : AppColors.brand),
                  ),
                ),
              ],
            ),
          ),
        ),
      );
}
