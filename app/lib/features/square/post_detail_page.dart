import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_exception.dart';
import '../../core/format.dart';
import '../chat/widgets/photo_viewer.dart';
import '../profile/profile_controller.dart';
import 'models.dart';
import 'post_detail_controller.dart';
import 'widgets/post_card.dart';

/// 动态详情:顶部完整卡片 + 评论列表(正序)+ 底部输入框。
class PostDetailPage extends ConsumerStatefulWidget {
  const PostDetailPage({super.key, required this.postId});

  final int postId;

  @override
  ConsumerState<PostDetailPage> createState() => _PostDetailPageState();
}

class _PostDetailPageState extends ConsumerState<PostDetailPage> {
  final _input = TextEditingController();
  bool _sending = false;

  @override
  void dispose() {
    _input.dispose();
    super.dispose();
  }

  void _show(String message) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
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
      if (mounted) _show(error.message);
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  Future<void> _toggleLike() async {
    try {
      await ref.read(postDetailProvider(widget.postId).notifier).toggleLike();
    } on ApiException catch (error) {
      if (mounted) _show(error.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    final post = ref.watch(postDetailProvider(widget.postId));
    final comments = ref.watch(commentsProvider(widget.postId));
    final myId = ref.watch(profileProvider).value?.userId;
    return Scaffold(
      appBar: AppBar(title: const Text('动态详情')),
      backgroundColor: const Color(0xFFF7F3F5),
      body: Column(
        children: [
          Expanded(
            child: post.when(
              loading: () => const Center(child: CircularProgressIndicator()),
              error: (error, _) => Center(
                child: Text(error is ApiException ? error.message : '加载失败,请重试'),
              ),
              data: (data) => ListView(
                children: [
                  PostCard(
                    post: data,
                    isMine: data.author.userId == myId,
                    onToggleLike: _toggleLike,
                    onOpenImage: (i) =>
                        openPhotoViewer(context, urls: data.images, initialIndex: i),
                    // 删除/举报菜单在 Task 12 接入
                  ),
                  const Divider(height: 1),
                  comments.when(
                    loading: () => const Padding(
                      padding: EdgeInsets.all(24),
                      child: Center(child: CircularProgressIndicator()),
                    ),
                    error: (error, _) => Padding(
                      padding: const EdgeInsets.all(24),
                      child: Center(
                        child: Text(error is ApiException ? error.message : '评论加载失败'),
                      ),
                    ),
                    data: (items) => Column(
                      children: [
                        for (final comment in items) _CommentTile(comment: comment),
                        if (items.isEmpty)
                          const Padding(
                            padding: EdgeInsets.all(24),
                            child: Text('还没有评论',
                                style: TextStyle(color: Color(0xFF999999))),
                          ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
          SafeArea(
            child: Container(
              color: Colors.white,
              padding: const EdgeInsets.fromLTRB(12, 6, 12, 6),
              child: Row(
                children: [
                  Expanded(
                    child: TextField(
                      key: const Key('post.comment.input'),
                      controller: _input,
                      maxLength: 200,
                      decoration: const InputDecoration(
                        hintText: '说点什么…',
                        counterText: '',
                        border: InputBorder.none,
                      ),
                      onSubmitted: (_) => _send(),
                    ),
                  ),
                  IconButton(
                    key: const Key('post.comment.send'),
                    onPressed: _sending ? null : _send,
                    icon: const Icon(Icons.send),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _CommentTile extends StatelessWidget {
  const _CommentTile({required this.comment});

  final PostCommentItem comment;

  @override
  Widget build(BuildContext context) {
    return Container(
      key: Key('post.comment.${comment.id}'),
      color: Colors.white,
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 28,
            height: 28,
            decoration: BoxDecoration(
              color: const Color(0xFFC9CDD4),
              borderRadius: BorderRadius.circular(4),
            ),
            clipBehavior: Clip.antiAlias,
            child: comment.author.avatarUrl == null
                ? Center(
                    child: Text(
                        comment.author.nickname.isEmpty
                            ? '?'
                            : comment.author.nickname.substring(0, 1),
                        style: const TextStyle(color: Colors.white, fontSize: 12)))
                : Image.network(comment.author.avatarUrl!, fit: BoxFit.cover,
                    errorBuilder: (c, e, s) =>
                        const Icon(Icons.person, color: Colors.white, size: 16)),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(comment.author.nickname,
                    style: const TextStyle(fontSize: 12, color: Color(0xFF999999))),
                const SizedBox(height: 2),
                Text(comment.text, style: const TextStyle(fontSize: 14, height: 1.3)),
                const SizedBox(height: 2),
                Text(formatPostTime(comment.createdAt),
                    style: const TextStyle(fontSize: 11, color: Color(0xFFBBBBBB))),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
