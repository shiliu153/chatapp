import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_exception.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_radius.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/theme/app_typography.dart';
import '../../core/widgets/app_dialog.dart';
import '../../core/widgets/app_error_view.dart';
import '../../core/widgets/app_sub_page_bar.dart';
import '../../core/widgets/app_toast.dart';
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
import 'widgets/comment_thread.dart';
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
  PostCommentItem? _replyTo;

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
      await ref
          .read(commentsProvider(widget.postId).notifier)
          .send(text, parentId: _replyTo?.id);
      _input.clear();
      setState(() => _replyTo = null);
      ref.invalidate(commentsProvider(widget.postId));      // 评论列表刷新
      ref.invalidate(postDetailProvider(widget.postId));    // 评论数 +1
    } on ApiException catch (error) {
      if (mounted) AppToast.show(context, error.message);
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  void _startReply(PostCommentItem comment) {
    setState(() => _replyTo = comment);
    _focus.requestFocus();
  }

  Future<void> _deleteComment(PostCommentItem comment) async {
    final extra = comment.replyCount > 0 ? '连同 ${comment.replyCount} 条回复一起删除,' : '';
    final confirmed = await showConfirmDialog(
      context,
      title: '删除这条评论?',
      message: '$extra删除后不可恢复',
      confirmLabel: '删除',
      confirmKey: const Key('post.comment.delete.confirm'),
      danger: true,
    );
    if (!confirmed || !mounted) return;
    try {
      await ref.read(commentsProvider(widget.postId).notifier).delete(comment.id);
      ref.invalidate(commentsProvider(widget.postId));
      ref.invalidate(repliesProvider);
      ref.invalidate(postDetailProvider(widget.postId));
    } on ApiException catch (error) {
      if (mounted) AppToast.show(context, error.message);
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
                      onReply: _startReply,
                      onDelete: _deleteComment,
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
                    onReply: _startReply,
                    onDelete: _deleteComment,
                  );
                },
              ),
            ),
            _CommentBar(
              input: _input,
              focus: _focus,
              sending: _sending,
              replyTo: _replyTo,
              onCancelReply: () => setState(() => _replyTo = null),
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
    required this.onReply,
    required this.onDelete,
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
  final void Function(PostCommentItem comment) onReply;
  final void Function(PostCommentItem comment) onDelete;

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
        CommentThread(
          postId: post.id,
          comments: comments,
          myId: myId,
          onReply: onReply,
          onDelete: onDelete,
          onRetry: onRetryComments,
        ),
      ],
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
    required this.replyTo,
    required this.onCancelReply,
    required this.onSend,
  });

  final TextEditingController input;
  final FocusNode focus;
  final bool sending;
  final PostCommentItem? replyTo;
  final VoidCallback onCancelReply;
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
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (replyTo != null)
                  Padding(
                    padding: const EdgeInsets.only(bottom: AppSpacing.xs),
                    child: Row(
                      children: [
                        Flexible(
                          child: Text('回复 @${replyTo!.author.nickname}',
                              style: AppText.micro.copyWith(color: AppColors.text2)),
                        ),
                        GestureDetector(
                          key: const Key('post.comment.reply.cancel'),
                          behavior: HitTestBehavior.opaque,
                          onTap: onCancelReply,
                          child: Icon(Icons.close_rounded,
                              size: 16, color: AppColors.text3),
                        ),
                      ],
                    ),
                  ),
                Row(
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
                        hintText: replyTo == null
                            ? '说点什么…'
                            : '回复 @${replyTo!.author.nickname}…',
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
              ],
            ),
          ),
        ),
      );
}
