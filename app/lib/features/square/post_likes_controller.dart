import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'feed_repository.dart';
import 'models.dart';

/// 某条动态的「谁点了赞」列表(游标分页,按点赞时间倒序)。
///
/// 与动态流不同,这里没有乐观写操作:点赞状态在卡片上改,本页只读。
/// `count` 不入状态 —— 它是**过滤后的可见人数**(双向拉黑/重封禁作者不计),
/// 与卡片上的 `like_count` 不是同一个数,展示它只会让人对不上。
class PostLikesController extends AsyncNotifier<List<PostLikeUser>> {
  PostLikesController(this.postId);

  final int postId;

  bool _hasMore = true;
  String? _nextCursor;

  @override
  Future<List<PostLikeUser>> build() => _fetchFirst();

  Future<List<PostLikeUser>> _fetchFirst() async {
    final page = await ref.read(feedRepositoryProvider).fetchLikes(postId);
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
    final page =
        await ref.read(feedRepositoryProvider).fetchLikes(postId, cursor: _nextCursor);
    _nextCursor = page.nextCursor;
    _hasMore = page.nextCursor != null;
    // 有人取消赞再点回来会让同一人出现在两页:按 userId 去重
    final existing = current.map((user) => user.userId).toSet();
    state = AsyncValue.data(
        [...current, ...page.items.where((user) => !existing.contains(user.userId))]);
  }
}

final postLikesProvider = AsyncNotifierProvider.autoDispose
    .family<PostLikesController, List<PostLikeUser>, int>(PostLikesController.new,
        retry: (retryCount, error) => null);
