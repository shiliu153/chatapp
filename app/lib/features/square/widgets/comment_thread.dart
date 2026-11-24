import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/api_exception.dart';
import '../../../core/format.dart';
import '../../../core/theme/app_typography.dart';
import '../../../core/theme/ember_colors.dart';
import '../../../core/theme/ember_motion.dart';
import '../../../core/theme/ember_theme_context.dart';
import '../../../core/theme/tokens.g.dart' as tokens;
import '../../../core/ui/ember_ui.dart';
import '../../../core/widgets/avatar_hero.dart';
import '../models.dart';
import '../post_detail_controller.dart';

/// 评论流(E-5.5 page spec §1 第 8 条 / §3 / §4):顶级评论 + 内嵌回复 +
/// 「查看全部 N 条回复」。
///
/// 迁到 Ember 的三件事:
/// 1. 每条评论是一块 `surface.sunken` + `radius.md` 的次级容器(不再是分割线列表);
/// 2. 楼中楼**保留**(§7 拍板 #4),缩进 16;作者名 `caption` 13/w600 `text.primary`,
///    内容 `body` 15 `text.primary`;
/// 3. 自己的评论在行尾给「删除」文字按钮(`text.tertiary`),二次确认走带图标 + 动词的
///    Dialog(§9.3)。
///
/// 楼层恒为两级:回复对象不再递归展开,与后端一致。
///
/// 评论区行内文字按钮的可点高度取 [_commentActionHeight](32):§8.4 要求 48,但一行里
/// 排三个 48 高热区会把每条评论撑到 110+、信息密度崩掉。这条差异记在 PR「遗留」,
/// 等规范为「行内文字按钮」补一档再改(规范目前只给了按钮与图标的 48)。
const double _commentActionHeight = 32.0;

/// 评论流。
class CommentThread extends StatelessWidget {
  /// 构造评论流。
  const CommentThread({
    super.key,
    required this.postId,
    required this.comments,
    required this.myId,
    required this.onReply,
    required this.onDelete,
    required this.onRetry,
  });

  /// 所属动态 id(拉「查看全部回复」用)。
  final int postId;

  /// 评论列表状态。
  final AsyncValue<List<PostCommentItem>> comments;

  /// 当前账号 id(判断「自己的评论」)。
  final int? myId;

  /// 点「回复」。
  final void Function(PostCommentItem comment) onReply;

  /// 点「删除」(自己发的评论)。
  final void Function(PostCommentItem comment) onDelete;

  /// 评论加载失败时的重试。
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return comments.when(
      loading: () => const _CommentSkeleton(),
      // 错误态:一句话 + 文字按钮「重试」,不静默吞掉(spec §5 的失败口径)。
      error: (error, _) => _CommentError(
        message: apiMessageOf(error),
        onRetry: onRetry,
      ),
      data: (items) => items.isEmpty
          // 空评论:居中一句 `caption` `text.tertiary`(spec §5「评论为空」)。
          ? const _EmptyComments()
          : Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                for (final root in items) ...[
                  CommentTile(
                    comment: root,
                    depth: 0,
                    isMine: root.author.userId == myId,
                    onReply: () => onReply(root),
                    onDelete: () => onDelete(root),
                  ),
                  for (final reply in root.replies)
                    CommentTile(
                      comment: reply,
                      depth: 1,
                      isMine: reply.author.userId == myId,
                      onReply: () => onReply(reply),
                      onDelete: () => onDelete(reply),
                    ),
                  if (root.replyCount > root.replies.length)
                    _MoreReplies(
                      postId: postId,
                      root: root,
                      myId: myId,
                      onReply: onReply,
                      onDelete: onDelete,
                    ),
                ],
              ],
            ),
    );
  }
}

/// 一条评论或回复;`depth` 为 1 时缩进 16、头像缩到 24。
class CommentTile extends StatelessWidget {
  /// 构造一条评论。
  const CommentTile({
    super.key,
    required this.comment,
    required this.depth,
    required this.isMine,
    required this.onReply,
    required this.onDelete,
  });

  /// 评论本身。
  final PostCommentItem comment;

  /// 0 = 顶级评论,1 = 回复(缩进 16)。
  final int depth;

  /// 是否是我发的(决定有没有「删除」)。
  final bool isMine;

  /// 点「回复」。
  final VoidCallback onReply;

  /// 点「删除」。
  final VoidCallback onDelete;

  /// 读屏一句话:作者 + 内容 + 时间(spec §6 第 3 条)。
  String get _semanticsLabel => [
        comment.author.nickname,
        comment.text,
        formatPostTime(comment.createdAt),
      ].join('，');

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    final heroTag = 'avatar-comment-${comment.id}';
    final replyTo = comment.replyTo;
    final avatarSize = depth == 0
        ? EmberComponentSizes.avatarXs
        : EmberComponentSizes.avatarSm;
    return Padding(
      padding: EdgeInsets.only(
        // 楼中楼缩进 16(spec §3「评论项 楼中楼缩进 16」)。
        left: depth == 0 ? 0 : tokens.space16,
        bottom: tokens.space8,
      ),
      child: Semantics(
        container: true,
        label: _semanticsLabel,
        child: Container(
          key: Key('post.comment.${comment.id}'),
          padding: EdgeInsets.all(tokens.space12),
          decoration: BoxDecoration(
            color: colors.surfaceSunken,
            borderRadius: BorderRadius.circular(tokens.radiusMd),
          ),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              AvatarHero(
                tag: heroTag,
                imageUrl: comment.author.avatarUrl,
                fromRadius: tokens.radiusPill,
                child: GestureDetector(
                  key: Key('post.comment.avatar.${comment.id}'),
                  behavior: HitTestBehavior.opaque,
                  onTap: isMine
                      ? null
                      : () => context.push('/users/${comment.author.userId}',
                          extra: heroTag),
                  child: EmberAvatar(
                    image: (comment.author.avatarUrl == null ||
                            comment.author.avatarUrl!.isEmpty)
                        ? null
                        : NetworkImage(comment.author.avatarUrl!),
                    name: comment.author.nickname,
                    size: avatarSize,
                  ),
                ),
              ),
              SizedBox(width: tokens.space8),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    GestureDetector(
                      key: Key('post.comment.nickname.${comment.id}'),
                      behavior: HitTestBehavior.opaque,
                      onTap: isMine
                          ? null
                          : () => context.push('/users/${comment.author.userId}',
                              extra: heroTag),
                      child: Text(
                        comment.author.nickname,
                        style: AppText.caption.copyWith(
                          fontWeight: FontWeight.w600,
                          color: colors.textPrimary,
                        ),
                      ),
                    ),
                    SizedBox(height: tokens.space4),
                    Text.rich(
                      TextSpan(
                        children: [
                          if (replyTo != null)
                            TextSpan(
                              text: '回复 @${replyTo.nickname} ',
                              style: AppText.body.copyWith(
                                color: colors.textTertiary,
                              ),
                            ),
                          TextSpan(
                            text: comment.text,
                            style: AppText.body.copyWith(
                              color: colors.textPrimary,
                            ),
                          ),
                        ],
                      ),
                    ),
                    SizedBox(height: tokens.space4),
                    _footer(colors),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  /// 时间 + 回复 + 删除(自己的评论才有;删除贴在行尾,§4「自己的评论右侧删除」)。
  Widget _footer(EmberColors colors) => Row(
        children: [
          Text(
            formatPostTime(comment.createdAt),
            style: AppText.caption.copyWith(color: colors.textTertiary),
          ),
          SizedBox(width: tokens.space12),
          _CommentTextAction(
            key: Key('post.comment.reply.${comment.id}'),
            label: '回复',
            color: colors.textSecondary,
            onTap: onReply,
          ),
          const Spacer(),
          if (isMine)
            _CommentTextAction(
              key: Key('post.comment.delete.${comment.id}'),
              label: '删除',
              color: colors.textTertiary,
              onTap: onDelete,
            ),
        ],
      );
}

/// 评论行内的文字按钮(回复 / 删除):无底、`caption` 13,按压缩到 .97。
class _CommentTextAction extends StatelessWidget {
  const _CommentTextAction({
    super.key,
    required this.label,
    required this.color,
    required this.onTap,
  });

  final String label;
  final Color color;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return EmberPressable(
      onTap: onTap,
      pressedScale: 0.97,
      borderRadius: BorderRadius.circular(tokens.radiusXs),
      semanticLabel: label,
      builder: (context, state) => ConstrainedBox(
        constraints: const BoxConstraints(
          minWidth: tokens.sizeTouchApp,
          minHeight: _commentActionHeight,
        ),
        child: Center(
          child: Text(
            label,
            style: AppText.caption.copyWith(
              fontWeight: FontWeight.w600,
              color: color,
            ),
          ),
        ),
      ),
    );
  }
}

/// 「查看全部 N 条回复」:点击后走独立接口拉全量,原地展开。
class _MoreReplies extends ConsumerStatefulWidget {
  const _MoreReplies({
    required this.postId,
    required this.root,
    required this.myId,
    required this.onReply,
    required this.onDelete,
  });

  final int postId;
  final PostCommentItem root;
  final int? myId;
  final void Function(PostCommentItem comment) onReply;
  final void Function(PostCommentItem comment) onDelete;

  @override
  ConsumerState<_MoreReplies> createState() => _MoreRepliesState();
}

class _MoreRepliesState extends ConsumerState<_MoreReplies> {
  bool _expanded = false;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    final root = widget.root;
    if (!_expanded) {
      return Padding(
        padding: EdgeInsets.only(left: tokens.space16, bottom: tokens.space8),
        child: Align(
          alignment: Alignment.centerLeft,
          child: _CommentTextAction(
            key: Key('post.comment.replies.more.${root.id}'),
            label: '查看全部 ${root.replyCount} 条回复',
            color: colors.textSecondary,
            onTap: () => setState(() => _expanded = true),
          ),
        ),
      );
    }
    final replies = ref.watch(
        repliesProvider((postId: widget.postId, commentId: root.id)));
    return AnimatedSize(
      duration: EmberMotion.reducedOf(context)
          ? EmberMotion.reduced
          : const Duration(milliseconds: 240),
      alignment: Alignment.topCenter,
      child: replies.when(
        loading: () => const _CommentSkeleton(rows: 1),
        error: (error, _) => Padding(
          padding: EdgeInsets.symmetric(vertical: tokens.space8),
          child: Text(
            apiMessageOf(error),
            style: AppText.caption.copyWith(color: colors.textTertiary),
          ),
        ),
        data: (items) => Column(
          children: [
            for (final reply in items)
              CommentTile(
                comment: reply,
                depth: 1,
                isMine: reply.author.userId == widget.myId,
                onReply: () => widget.onReply(reply),
                onDelete: () => widget.onDelete(reply),
              ),
          ],
        ),
      ),
    );
  }
}

/// 评论骨架:圆头像块 + 两行文字条。
class _CommentSkeleton extends StatelessWidget {
  const _CommentSkeleton({this.rows = 2});

  final int rows;

  @override
  Widget build(BuildContext context) => Column(
        children: [
          for (var i = 0; i < rows; i++)
            Padding(
              padding: EdgeInsets.only(bottom: tokens.space8),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const EmberSkeleton(
                    width: EmberComponentSizes.avatarXs,
                    height: EmberComponentSizes.avatarXs,
                    shape: BoxShape.circle,
                  ),
                  SizedBox(width: tokens.space8),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        EmberSkeleton(width: 96, height: tokens.fontSizeCaption),
                        SizedBox(height: tokens.space4),
                        EmberSkeleton(height: tokens.fontSizeBody),
                      ],
                    ),
                  ),
                ],
              ),
            ),
        ],
      );
}

/// 评论加载失败:一句话 + 文字按钮「重试」(不静默吞掉)。
class _CommentError extends StatelessWidget {
  const _CommentError({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    return Padding(
      padding: EdgeInsets.symmetric(vertical: tokens.space20),
      child: Column(
        children: [
          Text(
            message,
            textAlign: TextAlign.center,
            style: AppText.caption.copyWith(color: colors.textSecondary),
          ),
          SizedBox(height: tokens.space8),
          EmberButton(
            key: const Key('post.comments.retry'),
            label: '重试',
            variant: EmberButtonVariant.text,
            onPressed: onRetry,
          ),
        ],
      ),
    );
  }
}

/// 评论为空:居中一句提示(spec §5「还没有评论,来说点什么」)。
class _EmptyComments extends StatelessWidget {
  const _EmptyComments();

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    return Padding(
      padding: EdgeInsets.symmetric(vertical: tokens.space32),
      child: Center(
        child: Text(
          '还没有评论，来说点什么',
          style: AppText.caption.copyWith(color: colors.textTertiary),
        ),
      ),
    );
  }
}
