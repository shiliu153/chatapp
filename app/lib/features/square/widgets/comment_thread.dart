import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/api_exception.dart';
import '../../../core/format.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_radius.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/theme/app_typography.dart';
import '../../../core/widgets/app_avatar.dart';
import '../../../core/widgets/app_empty_state.dart';
import '../../../core/widgets/app_error_view.dart';
import '../../../core/widgets/avatar_hero.dart';
import '../models.dart';
import '../post_detail_controller.dart';

/// 评论流(附录 D):顶级评论 + 内嵌回复 + 「查看全部 N 条回复」。
///
/// 楼层恒为两级:回复对象不再递归展开,与后端一致。
class CommentThread extends StatelessWidget {
  const CommentThread({
    super.key,
    required this.postId,
    required this.comments,
    required this.myId,
    required this.onReply,
    required this.onDelete,
    required this.onRetry,
  });

  final int postId;
  final AsyncValue<List<PostCommentItem>> comments;
  final int? myId;
  final void Function(PostCommentItem comment) onReply;
  final void Function(PostCommentItem comment) onDelete;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return comments.when(
      loading: () => const Padding(
        padding: EdgeInsets.all(AppSpacing.xxl),
        child: Center(child: CircularProgressIndicator()),
      ),
      error: (error, _) => Padding(
        padding: const EdgeInsets.all(AppSpacing.xxl),
        child: AppErrorView(message: apiMessageOf(error), onRetry: onRetry),
      ),
      data: (items) => items.isEmpty
          ? const Center(
              child: AppEmptyState(emoji: '💬', title: '还没有评论', description: '来抢沙发'),
            )
          : Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                for (var i = 0; i < items.length; i++) ...[
                  if (i > 0) const Divider(height: 1, color: AppColors.divider),
                  CommentTile(
                    comment: items[i],
                    depth: 0,
                    isMine: items[i].author.userId == myId,
                    onReply: () => onReply(items[i]),
                    onDelete: () => onDelete(items[i]),
                  ),
                  for (final reply in items[i].replies)
                    CommentTile(
                      comment: reply,
                      depth: 1,
                      isMine: reply.author.userId == myId,
                      onReply: () => onReply(reply),
                      onDelete: () => onDelete(reply),
                    ),
                  if (items[i].replyCount > items[i].replies.length)
                    _MoreReplies(
                      postId: postId,
                      root: items[i],
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

/// 一条评论或回复;`depth` 为 1 时缩进、头像缩到 24。
class CommentTile extends StatelessWidget {
  const CommentTile({
    super.key,
    required this.comment,
    required this.depth,
    required this.isMine,
    required this.onReply,
    required this.onDelete,
  });

  final PostCommentItem comment;
  final int depth;
  final bool isMine;
  final VoidCallback onReply;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) {
    final indent = depth == 0 ? 0.0 : AppSpacing.xxl;
    final size = depth == 0 ? 28.0 : 24.0;
    final heroTag = 'avatar-comment-${comment.id}';
    final replyTo = comment.replyTo;
    return Padding(
      key: Key('post.comment.${comment.id}'),
      padding: EdgeInsets.fromLTRB(indent, 12, 0, 12),
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
              onTap: isMine
                  ? null
                  : () => context.push('/users/${comment.author.userId}',
                      extra: heroTag),
              child: AppAvatar(
                imageUrl: comment.author.avatarUrl,
                size: size,
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
                  onTap: isMine
                      ? null
                      : () => context.push('/users/${comment.author.userId}',
                          extra: heroTag),
                  child: Text(comment.author.nickname,
                      style: AppText.caption.copyWith(
                          fontWeight: FontWeight.w600, color: AppColors.text2)),
                ),
                const SizedBox(height: 2),
                Text.rich(TextSpan(children: [
                  if (replyTo != null)
                    TextSpan(
                      text: '回复 @${replyTo.nickname} ',
                      style: AppText.body.copyWith(color: AppColors.text3),
                    ),
                  TextSpan(
                    text: comment.text,
                    style: AppText.body.copyWith(color: AppColors.text1),
                  ),
                ])),
                const SizedBox(height: 2),
                Row(
                  children: [
                    Text(formatPostTime(comment.createdAt),
                        style: AppText.micro.copyWith(color: AppColors.text3)),
                    const SizedBox(width: AppSpacing.md),
                    _TextButton(
                      key: Key('post.comment.reply.${comment.id}'),
                      label: '回复',
                      onTap: onReply,
                    ),
                    if (isMine) ...[
                      const SizedBox(width: AppSpacing.sm),
                      _TextButton(
                        key: Key('post.comment.delete.${comment.id}'),
                        label: '删除',
                        onTap: onDelete,
                      ),
                    ],
                  ],
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _TextButton extends StatelessWidget {
  const _TextButton({super.key, required this.label, required this.onTap});

  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 2, horizontal: 2),
          child: Text(label,
              style: AppText.micro.copyWith(color: AppColors.text2)),
        ),
      );
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
    final root = widget.root;
    if (!_expanded) {
      return Padding(
        padding: const EdgeInsets.only(left: AppSpacing.xxl, bottom: AppSpacing.sm),
        child: GestureDetector(
          key: Key('post.comment.replies.more.${root.id}'),
          behavior: HitTestBehavior.opaque,
          onTap: () => setState(() => _expanded = true),
          child: Text('查看全部 ${root.replyCount} 条回复',
              style: AppText.micro.copyWith(color: AppColors.text2)),
        ),
      );
    }
    final replies = ref.watch(
        repliesProvider((postId: widget.postId, commentId: root.id)));
    return AnimatedSize(
      duration: const Duration(milliseconds: 180),
      alignment: Alignment.topCenter,
      child: replies.when(
        loading: () => const Padding(
          padding: EdgeInsets.symmetric(vertical: AppSpacing.md),
          child: Center(child: CircularProgressIndicator()),
        ),
        error: (error, _) => Padding(
          padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
          child: Text(apiMessageOf(error),
              style: AppText.micro.copyWith(color: AppColors.text3)),
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
