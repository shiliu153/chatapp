import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'feed_repository.dart';
import 'models.dart';

/// 游标分页动态流的公共实现。
///
/// 广场「推荐」与「关注」两个 tab 的数据链路完全一致,只差一个接口路径:
/// 首屏、翻页去重、点赞乐观更新与失败回滚都在这里,子类只声明 [path]。
/// 不抽基类的话两份逻辑必然漂移(改一处忘一处是列表页最常见的 bug)。
abstract class PostFeedController extends AsyncNotifier<List<Post>> {
  /// 列表接口路径:`/posts`(推荐)或 `/feed/following`(关注)。
  String get path;

  bool _hasMore = true;
  String? _nextCursor;

  @override
  Future<List<Post>> build() => _fetchFirst();

  Future<List<Post>> _fetchFirst() async {
    final page = await ref.read(feedRepositoryProvider).fetchPosts(path: path);
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
        .fetchPosts(path: path, cursor: _nextCursor);
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

/// 广场「推荐」tab:全站可见动态(`GET /posts`)。
class SquareController extends PostFeedController {
  @override
  String get path => '/posts';
}

/// 广场「关注」tab:只含我关注的人的动态(`GET /feed/following`,不含自己)。
class FollowingController extends PostFeedController {
  @override
  String get path => '/feed/following';
}

final squareProvider =
    AsyncNotifierProvider.autoDispose<SquareController, List<Post>>(
  SquareController.new,
  // 页面自己有错误态,关掉 Riverpod 3 的自动重试
  retry: (retryCount, error) => null,
);

final followingProvider =
    AsyncNotifierProvider.autoDispose<FollowingController, List<Post>>(
  FollowingController.new,
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
