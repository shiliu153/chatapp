import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:phosphor_glyphs/phosphor_glyphs.dart';

import '../../core/api_exception.dart';
import '../../core/theme/app_typography.dart';
import '../../core/theme/ember_theme_context.dart';
import '../../core/theme/tokens.g.dart' as tokens;
import '../../core/ui/ember_ui.dart';
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
import 'widgets/post_confirm_dialog.dart';
import 'widgets/post_detail_skeleton.dart';
import 'widgets/square_illustration.dart';

/// 动态详情(E-5.5 page spec §1 / §2 / §3 / §5)。
///
/// 层级形态(§9.3 / §9.4):二级页、全屏 push、图片 Hero 进入;顶栏走 §9.4 shell
/// **52**(返回 22 + 标题 17/w600 居中)。三点用户可见变化:
/// 1. 顶栏从心跳期自绘的 62 / 56 统一到 **52**;
/// 2. 图片 Hero 本单落地(卡图片 → 详情图片),`disableAnimations` 时退化为淡入
///    (Hero 不包 + 路由转场走 `router.dart` 的 reduced 分支);
/// 3. 评论楼中楼换 `surface.sunken` + `radius.md`(缩进 16),输入条换 `EmberField` +
///    文字按钮「发送」;发送失败**保留草稿**并在输入条下方给 `status.danger` 说明。
class PostDetailPage extends ConsumerStatefulWidget {
  /// 构造详情页。
  const PostDetailPage({super.key, required this.postId, this.args});

  /// 动态 id。
  final int postId;

  /// 跨页载荷(Hero tag + 列表快照);null(我的动态 / 深链)时无 Hero、骨架起步。
  final PostDetailArgs? args;

  @override
  ConsumerState<PostDetailPage> createState() => _PostDetailPageState();
}

class _PostDetailPageState extends ConsumerState<PostDetailPage> {
  final _input = TextEditingController();
  final _focus = FocusNode();
  bool _sending = false;
  PostCommentItem? _replyTo;

  /// 发送失败提示(§5「评论发送失败 → 输入条下方 status.danger 提示 + 保留草稿」)。
  String? _sendError;

  @override
  void initState() {
    super.initState();
    // 从「评论钮」进详情:焦点直接落进输入框(§4 评论钮的语义)。
    if (widget.args?.focusComment == true) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) _focus.requestFocus();
      });
    }
  }

  @override
  void dispose() {
    _input.dispose();
    _focus.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    final text = _input.text.trim();
    if (text.isEmpty || _sending) return;
    setState(() {
      _sending = true;
      _sendError = null;
    });
    try {
      await ref
          .read(commentsProvider(widget.postId).notifier)
          .send(text, parentId: _replyTo?.id);
      _input.clear();
      setState(() => _replyTo = null);
      ref.invalidate(commentsProvider(widget.postId)); // 评论列表刷新
      ref.invalidate(postDetailProvider(widget.postId)); // 评论数 +1
    } on ApiException catch (error) {
      // 不静默丢弃草稿:只把错误写在输入条下方,输入内容原样留着。
      if (mounted) setState(() => _sendError = error.message);
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
    final confirmed = await showPostConfirmDialog(
      context,
      icon: PhosphorIconsRegular.trash,
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
      if (mounted) EmberToast.show(context, error.message);
    }
  }

  Future<void> _toggleLike() async {
    try {
      await ref.read(postDetailProvider(widget.postId).notifier).toggleLike();
    } on ApiException catch (error) {
      if (mounted) EmberToast.show(context, error.message);
    }
  }

  /// 收藏 / 取消收藏:乐观翻转在控制器里,失败回滚后由这里提示。
  ///
  /// 这里**故意不 invalidate 列表 provider**(与点赞同口径):广场 / 我的动态的
  /// provider 还活着,失效会把它打回 loading,返回时列表被重置到顶部、Hero 也没了
  /// 目标。列表页自己在「从详情返回」时刷新(见 `favorites_page.dart`)。
  Future<void> _toggleFavorite() async {
    final wasFavorited =
        ref.read(postDetailProvider(widget.postId)).value?.isFavorited ?? false;
    try {
      await ref.read(postDetailProvider(widget.postId).notifier).toggleFavorite();
      if (!mounted) return;
      EmberToast.show(context, wasFavorited ? '已取消收藏' : '已收藏');
    } on ApiException catch (error) {
      if (mounted) EmberToast.show(context, error.message);
    }
  }

  /// 卡片右上 `···` 的动作分发(收藏对谁都给;删除/举报按动态归属二选一)。
  Future<void> _onMenu(Post post, String action) async {
    switch (action) {
      case 'favorite' || 'unfavorite':
        await _toggleFavorite();
      case 'delete':
        await _deletePost();
      default:
        await reportPostFromSheet(context, ref, post.id);
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
      if (mounted) EmberToast.show(context, error.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    final post = ref.watch(postDetailProvider(widget.postId));
    final comments = ref.watch(commentsProvider(widget.postId));
    final presenceById = ref.watch(presenceProvider);
    final myId = ref.watch(profileProvider).value?.userId;
    final args = widget.args;
    return Scaffold(
      backgroundColor: colors.surfacePage,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            const _DetailHeader(),
            Expanded(
              child: post.when(
                loading: () {
                  final seedArgs = args;
                  if (seedArgs != null) {
                    final seed = seedArgs.seed;
                    // Hero 只在 push 后下一帧末扫描一次:loading 也要用 seed
                    // 直出真卡(顶卡带 tag),否则目标侧没 Hero、不飞
                    ref.read(presenceProvider.notifier).track(
                        'post:${widget.postId}', [seed.author.userId]);
                    return _Body(
                      post: seed,
                      heroCardTag: seedArgs.heroTag,
                      imageHeroTag: seedArgs.imageHeroTag,
                      presenceById: presenceById,
                      myId: myId,
                      comments: comments,
                      onToggleLike: _toggleLike,
                      onOpenImage: (post, i) => openPhotoViewer(context,
                          urls: post.images, initialIndex: i),
                      onMenu: _onMenu,
                      onRetryComments: () =>
                          ref.invalidate(commentsProvider(widget.postId)),
                      onReply: _startReply,
                      onDelete: _deleteComment,
                    );
                  }
                  return const Padding(
                    padding: EdgeInsets.symmetric(horizontal: tokens.space20),
                    child: PostDetailSkeleton(),
                  );
                },
                error: (error, _) => _error(error),
                data: (data) {
                  ref.read(presenceProvider.notifier).track(
                      'post:${widget.postId}', [data.author.userId]);
                  return _Body(
                    post: data,
                    heroCardTag: args?.heroTag,
                    imageHeroTag: args?.imageHeroTag,
                    presenceById: presenceById,
                    myId: myId,
                    comments: comments,
                    onToggleLike: _toggleLike,
                    onOpenImage: (post, i) => openPhotoViewer(context,
                        urls: post.images, initialIndex: i),
                    onMenu: _onMenu,
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
              errorText: _sendError,
              onCancelReply: () => setState(() => _replyTo = null),
              onSend: _send,
            ),
          ],
        ),
      ),
    );
  }

  /// 详情拿不到时的两态(§5):404 =「这条动态已被删除」+ 返回;其余 = 加载失败 + 重试。
  Widget _error(Object error) {
    final notFound = error is ApiException && error.statusCode == 404;
    return Center(
      child: Padding(
        padding: EdgeInsets.symmetric(
          horizontal: tokens.space20,
          vertical: tokens.space24,
        ),
        child: EmberEmpty(
          illustration: const SquareIllustration(SquareIllustrationKind.loadFailed),
          title: notFound ? '这条动态已被删除' : '加载失败',
          description: apiMessageOf(error),
          actionLabel: notFound ? '返回' : '重试',
          // 「返回」用独立 key:与顶栏返回键的 post.back 区分开,测试才不会撞
          actionKey: Key(notFound ? 'post.deleted.back' : 'post.retry'),
          onAction: notFound
              ? () => context.pop()
              : () => ref.invalidate(postDetailProvider(widget.postId)),
        ),
      ),
    );
  }
}

/// 二级页顶栏(§9.4):高 **52**;返回 22 + 标题 17/w600 居中。
///
/// 右侧留一个与返回键等宽的占位,保证标题在屏幕上真正居中(不是「减掉左键后居中」)。
class _DetailHeader extends StatelessWidget {
  const _DetailHeader();

  /// 返回图标尺寸(§9.4「返回 22」;token 只有 16/20/24 三档,22 是规范直接给的数)。
  static const _backIconSize = 22.0;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    return SizedBox(
      height: tokens.sizeControlHeight,
      child: Row(
        children: [
          EmberPressable(
            key: const Key('post.back'),
            onTap: () => Navigator.of(context).maybePop(),
            pressedScale: 0.97,
            borderRadius: BorderRadius.circular(tokens.radiusPill),
            semanticLabel: '返回',
            builder: (context, state) => SizedBox(
              width: tokens.sizeTouchApp,
              height: tokens.sizeTouchApp,
              child: Icon(
                PhosphorIconsRegular.caretLeft,
                size: _backIconSize,
                color: colors.textPrimary,
              ),
            ),
          ),
          Expanded(
            child: Text(
              '动态详情',
              textAlign: TextAlign.center,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: AppText.subtitle.copyWith(color: colors.textPrimary),
            ),
          ),
          // 与返回键等宽的占位:标题真正居中
          SizedBox(width: tokens.sizeTouchApp, height: tokens.sizeTouchApp),
        ],
      ),
    );
  }
}

/// 详情页正文(seed / data 共用):顶卡 + 评论流。
class _Body extends StatelessWidget {
  const _Body({
    required this.post,
    required this.heroCardTag,
    required this.imageHeroTag,
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
  final String? imageHeroTag;
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
    // Hero 互斥:两种 Hero 都没在飞(我的动态 / 深链)时,作者头像保留「头像 → 资料页」
    // 转场;任一在飞时头像让位(SDK 禁 Hero 嵌套)。
    final heroFlying = heroCardTag != null || imageHeroTag != null;
    return ListView(
      padding: EdgeInsets.fromLTRB(
        tokens.space20,
        tokens.space4,
        tokens.space20,
        tokens.space24,
      ),
      children: [
        CardHero(
          tag: heroCardTag,
          child: PostCard(
            post: post,
            heroTag: heroFlying ? null : 'avatar-post-${post.id}',
            isMine: post.author.userId == myId,
            online: presenceById[post.author.userId]?.online == true,
            onTapAuthor: post.author.userId == myId
                ? null
                : () => context.push('/users/${post.author.userId}',
                    extra: 'avatar-post-${post.id}'),
            onToggleLike: onToggleLike,
            // 点赞数字区 → 点赞列表(图标区仍是点赞/取消,语义不变)
            onTapLikes: () => context.push('/posts/${post.id}/likes'),
            onOpenImage: (i) => onOpenImage(post, i),
            menuAction: (action) => onMenu(post, action),
            // 详情页里点卡不该再进详情
            onTap: null,
            imageHeroTag: imageHeroTag,
          ),
        ),
        SizedBox(height: tokens.space16),
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

/// 底部评论输入条(§2「评论输入:键盘上方内联输入条」+ §3「EmberField + 文字按钮」)。
///
/// 为什么不用 sheet:评论是**持续动作**(一行接一行发),不是单次选择(§9.3)。
class _CommentBar extends StatelessWidget {
  const _CommentBar({
    required this.input,
    required this.focus,
    required this.sending,
    required this.replyTo,
    required this.errorText,
    required this.onCancelReply,
    required this.onSend,
  });

  final TextEditingController input;
  final FocusNode focus;
  final bool sending;
  final PostCommentItem? replyTo;

  /// 发送失败说明(`status.danger`,§5);null = 无错误。
  final String? errorText;

  final VoidCallback onCancelReply;
  final VoidCallback onSend;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    return Container(
      decoration: BoxDecoration(
        color: colors.surfacePage,
        border: Border(top: BorderSide(color: colors.borderDivider)),
      ),
      child: SafeArea(
        top: false,
        child: Padding(
          padding: EdgeInsets.all(tokens.space12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (replyTo != null)
                Padding(
                  padding: EdgeInsets.only(bottom: tokens.space8),
                  child: Row(
                    children: [
                      Expanded(
                        child: Text(
                          '回复 @${replyTo!.author.nickname}',
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: AppText.caption.copyWith(color: colors.textSecondary),
                        ),
                      ),
                      EmberPressable(
                        key: const Key('post.comment.reply.cancel'),
                        onTap: onCancelReply,
                        pressedScale: 0.97,
                        borderRadius: BorderRadius.circular(tokens.radiusPill),
                        semanticLabel: '取消回复',
                        builder: (context, state) => SizedBox(
                          width: tokens.sizeIcon24 + tokens.space24,
                          height: tokens.sizeIcon24 + tokens.space24,
                          child: Icon(
                            PhosphorIconsRegular.x,
                            size: tokens.sizeIcon16,
                            color: colors.textTertiary,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(
                    child: EmberField(
                      fieldKey: const Key('post.comment.input'),
                      controller: input,
                      focusNode: focus,
                      maxLength: 200,
                      placeholder: replyTo == null
                          ? '说点什么…'
                          : '回复 @${replyTo!.author.nickname}…',
                      errorText: errorText,
                      onSubmitted: (_) => onSend(),
                    ),
                  ),
                  SizedBox(width: tokens.space8),
                  // 发送:文字按钮(§3),发送中保持字号、转圈替换文字(§8.3 loading)。
                  //
                  // 注意**不要**用「输入为空就 disabled」控制这里:空内容本来就由
                  // `_send()` 自己早退,而按键状态跟着输入框重建会让「输入 → 立刻点」
                  // 落到上一帧的禁用态上(点了没反应),真机快速输入也会撞。
                  EmberButton(
                    key: const Key('post.comment.send'),
                    label: '发送',
                    variant: EmberButtonVariant.text,
                    loading: sending,
                    onPressed: sending ? null : onSend,
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}
