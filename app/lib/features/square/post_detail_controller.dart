import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'feed_repository.dart';
import 'models.dart';

class PostDetailController extends AsyncNotifier<Post> {
  PostDetailController(this.postId);

  final int postId;

  @override
  Future<Post> build() => ref.read(feedRepositoryProvider).fetchPost(postId);

  /// 详情页点赞乐观更新:先改本地再发请求,失败回滚并抛出。
  Future<void> toggleLike() async {
    final post = state.value;
    if (post == null) return;
    final target = !post.likedByMe;
    state = AsyncValue.data(post.copyWith(
        likedByMe: target, likeCount: post.likeCount + (target ? 1 : -1)));
    try {
      await ref.read(feedRepositoryProvider).toggleLike(post.id, like: target);
    } catch (_) {
      state = AsyncValue.data(post);
      rethrow;
    }
  }
}

final postDetailProvider = AsyncNotifierProvider.autoDispose
    .family<PostDetailController, Post, int>(PostDetailController.new,
        retry: (retryCount, error) => null);

class CommentsController extends AsyncNotifier<List<PostCommentItem>> {
  CommentsController(this.postId);

  final int postId;

  @override
  Future<List<PostCommentItem>> build() async =>
      (await ref.read(feedRepositoryProvider).fetchComments(postId)).items;

  Future<void> send(String text) async {
    await ref.read(feedRepositoryProvider).addComment(postId, text);
  }
}

final commentsProvider = AsyncNotifierProvider.autoDispose
    .family<CommentsController, List<PostCommentItem>, int>(CommentsController.new,
        retry: (retryCount, error) => null);
