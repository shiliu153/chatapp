import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'feed_repository.dart';
import 'models.dart';

/// 游标分页动态流的公共实现。
///
/// 广场「推荐」、「关注」、我的动态与「我的收藏」四个列表的数据链路完全一致,
/// 只差取哪一页:首屏、翻页去重、点赞/收藏的乐观更新与失败回滚都在这里。
/// 不抽基类的话几份逻辑必然漂移(改一处忘一处是列表页最常见的 bug)。
abstract class PostFeedController extends AsyncNotifier<List<Post>> {
  /// 列表接口路径:`/posts`(推荐)、`/feed/following`(关注)或
  /// `/posts/mine`(我的动态)。收藏页走自己的 [fetchPage]。
  String get path;

  bool _hasMore = true;
  String? _nextCursor;

  /// 取一页;默认按 [path] 打动态流接口,需要别的口径的列表重写此方法。
  Future<({List<Post> items, String? nextCursor})> fetchPage({String? cursor}) =>
      ref.read(feedRepositoryProvider).fetchPosts(path: path, cursor: cursor);

  @override
  Future<List<Post>> build() => _fetchFirst();

  Future<List<Post>> _fetchFirst() async {
    final page = await fetchPage();
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
    final page = await fetchPage(cursor: _nextCursor);
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

  /// 收藏乐观更新:先翻本地标记再发请求,失败回滚并抛出(页面弹提示)。
  ///
  /// 收藏态只认服务端(`is_favorited`),本地不持久化 —— 所以这里不做落盘。
  Future<void> toggleFavorite(Post post) async {
    final target = !post.isFavorited;
    _patch(post.id, isFavorited: target);
    try {
      await ref.read(feedRepositoryProvider).setFavorite(post.id, favorite: target);
    } catch (_) {
      _patch(post.id, isFavorited: post.isFavorited);
      rethrow;
    }
  }

  void _patch(int postId, {bool? likedByMe, int? likeCount, bool? isFavorited}) {
    final current = state.value;
    if (current == null) return;
    state = AsyncValue.data([
      for (final post in current)
        post.id == postId
            ? post.copyWith(
                likedByMe: likedByMe,
                likeCount: likeCount,
                isFavorited: isFavorited,
              )
            : post,
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

class MyPostsController extends PostFeedController {
  @override
  String get path => '/posts/mine';

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

/// 我的收藏:按**收藏时间**倒序(游标落在收藏行上,由后端保证),
/// 分页与乐观更新复用 [PostFeedController]。
class FavoritesController extends PostFeedController {
  @override
  String get path => '/feed/favorites';

  @override
  Future<({List<Post> items, String? nextCursor})> fetchPage({String? cursor}) =>
      ref.read(feedRepositoryProvider).fetchFavorites(cursor: cursor);

  /// 取消收藏成功后把这条移出列表:收藏列表里不该继续存在「已取消收藏」的条目。
  ///
  /// 失败时父类已经回滚标记并抛出,所以只需处理成功分支。
  @override
  Future<void> toggleFavorite(Post post) async {
    await super.toggleFavorite(post);
    if (!post.isFavorited) return; // 原本未收藏 → 现在是「收藏」,留在列表里
    final current = state.value ?? const <Post>[];
    state = AsyncValue.data(current.where((item) => item.id != post.id).toList());
  }
}

final favoritesProvider =
    AsyncNotifierProvider.autoDispose<FavoritesController, List<Post>>(
  FavoritesController.new,
  retry: (retryCount, error) => null,
);
