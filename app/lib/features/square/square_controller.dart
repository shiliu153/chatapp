import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'feed_repository.dart';
import 'models.dart';

class SquareController extends AsyncNotifier<List<Post>> {
  bool _hasMore = true;
  String? _nextCursor;

  @override
  Future<List<Post>> build() => _fetchFirst();

  Future<List<Post>> _fetchFirst() async {
    final page = await ref.read(feedRepositoryProvider).fetchPosts();
    _nextCursor = page.nextCursor;
    _hasMore = page.nextCursor != null;
    return page.items;
  }

  Future<void> reload() async {
    state = const AsyncValue.loading();
    state = await AsyncValue.guard(_fetchFirst);
  }

  Future<void> loadMore() async {
    final current = state.value;
    if (current == null || !_hasMore) return;
    final page = await ref
        .read(feedRepositoryProvider)
        .fetchPosts(cursor: _nextCursor);
    _nextCursor = page.nextCursor;
    _hasMore = page.nextCursor != null;
    final existing = current.map((post) => post.id).toSet();
    state = AsyncValue.data(
        [...current, ...page.items.where((post) => !existing.contains(post.id))]);
  }

  /// 点赞乐观更新:先改本地再发请求,失败回滚并抛出(页面弹提示)。
  Future<void> toggleLike(Post post) async {
    final target = !post.likedByMe;
    _patch(post.id, likedByMe: target, likeCount: post.likeCount + (target ? 1 : -1));
    try {
      await ref.read(feedRepositoryProvider).toggleLike(post.id, like: target);
    } catch (_) {
      _patch(post.id, likedByMe: post.likedByMe, likeCount: post.likeCount);
      rethrow;
    }
  }

  void _patch(int postId, {required bool likedByMe, required int likeCount}) {
    final current = state.value;
    if (current == null) return;
    state = AsyncValue.data([
      for (final post in current)
        post.id == postId ? post.copyWith(likedByMe: likedByMe, likeCount: likeCount) : post,
    ]);
  }
}

final squareProvider =
    AsyncNotifierProvider.autoDispose<SquareController, List<Post>>(
  SquareController.new,
  // 页面自己有错误态,关掉 Riverpod 3 的自动重试
  retry: (retryCount, error) => null,
);

class MyPostsController extends AsyncNotifier<List<Post>> {
  bool _hasMore = true;
  String? _nextCursor;

  @override
  Future<List<Post>> build() async {
    final page = await ref.read(feedRepositoryProvider).fetchPosts(path: '/posts/mine');
    _nextCursor = page.nextCursor;
    _hasMore = page.nextCursor != null;
    return page.items;
  }

  Future<void> reload() async {
    state = const AsyncValue.loading();
    state = await AsyncValue.guard(build);
  }

  Future<void> loadMore() async {
    final current = state.value;
    if (current == null || !_hasMore) return;
    final page = await ref
        .read(feedRepositoryProvider)
        .fetchPosts(path: '/posts/mine', cursor: _nextCursor);
    _nextCursor = page.nextCursor;
    _hasMore = page.nextCursor != null;
    final existing = current.map((post) => post.id).toSet();
    state = AsyncValue.data(
        [...current, ...page.items.where((post) => !existing.contains(post.id))]);
  }

  /// 删除后本地移除(行立刻消失)。
  Future<void> remove(int postId) async {
    await ref.read(feedRepositoryProvider).deletePost(postId);
    final current = state.value ?? const <Post>[];
    state = AsyncValue.data(current.where((post) => post.id != postId).toList());
  }
}

final myPostsProvider =
    AsyncNotifierProvider.autoDispose<MyPostsController, List<Post>>(
  MyPostsController.new,
  retry: (retryCount, error) => null,
);
