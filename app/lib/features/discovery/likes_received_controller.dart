import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../chat/match_cache.dart';
import 'discovery_repository.dart';
import 'models.dart';

const _pageSize = 20;

/// 「喜欢我的人」页面状态。
class LikesReceivedState {
  const LikesReceivedState({
    required this.items,
    required this.count,
    this.hasMore = false,
    this.busyUserId,
  });

  final List<LikeReceived> items;
  final int count;
  final bool hasMore;
  final int? busyUserId;

  LikesReceivedState copyWith({
    List<LikeReceived>? items,
    int? count,
    bool? hasMore,
    int? busyUserId,
    bool clearBusy = false,
  }) =>
      LikesReceivedState(
        items: items ?? this.items,
        count: count ?? this.count,
        hasMore: hasMore ?? this.hasMore,
        busyUserId: clearBusy ? null : (busyUserId ?? this.busyUserId),
      );
}

/// 分页拉取 + 回喜欢编排(移除行、计数、配对缓存、角标)。
class LikesReceivedController extends AsyncNotifier<LikesReceivedState> {
  bool _loadingMore = false;

  @override
  Future<LikesReceivedState> build() => _fetch(reset: true);

  Future<LikesReceivedState> _fetch({required bool reset, int offset = 0}) async {
    final page = await ref
        .read(discoveryRepositoryProvider)
        .fetchLikesReceived(limit: _pageSize, offset: offset);
    final items = reset
        ? page.items
        : [...(state.value?.items ?? const <LikeReceived>[]), ...page.items];
    return LikesReceivedState(
      items: items,
      count: page.count,
      hasMore: items.length < page.count,
    );
  }

  Future<void> reload() async {
    state = const AsyncValue.loading();
    state = await AsyncValue.guard(() => _fetch(reset: true));
  }

  Future<void> loadMore() async {
    final current = state.value;
    if (current == null || !current.hasMore || _loadingMore) return;
    _loadingMore = true;
    try {
      final page = await ref
          .read(discoveryRepositoryProvider)
          .fetchLikesReceived(limit: _pageSize, offset: current.items.length);
      state = AsyncValue.data(current.copyWith(
        items: [...current.items, ...page.items],
        count: page.count,
        hasMore: current.items.length + page.items.length < page.count,
      ));
    } finally {
      _loadingMore = false;
    }
  }

  /// 回喜欢;需要弹配对动效时返回被喜欢的人,未配对返回 null。
  Future<Candidate?> accept(LikeReceived item) async {
    final current = state.value;
    if (current == null || current.busyUserId != null) return null;
    state = AsyncValue.data(current.copyWith(busyUserId: item.candidate.userId));
    try {
      final matched = await ref
          .read(discoveryRepositoryProvider)
          .swipe(targetUserId: item.candidate.userId, like: true);
      final now = state.value ?? current;
      final items = now.items
          .where((entry) => entry.candidate.userId != item.candidate.userId)
          .toList();
      final newCount = now.count > 0 ? now.count - 1 : 0;
      state = AsyncValue.data(now.copyWith(
        items: items,
        count: newCount,
        hasMore: items.length < newCount,
        clearBusy: true,
      ));
      ref.invalidate(matchCacheProvider);
      ref.invalidate(likesReceivedCountProvider);
      return matched ? item.candidate : null;
    } catch (_) {
      final now = state.value ?? current;
      state = AsyncValue.data(now.copyWith(clearBusy: true));
      await reload();
      rethrow;
    }
  }
}

final likesReceivedProvider =
    AsyncNotifierProvider<LikesReceivedController, LikesReceivedState>(
  LikesReceivedController.new,
  retry: (retryCount, error) => null,
);

/// 入口角标:只查数量,不拉整页。
final likesReceivedCountProvider = FutureProvider<int>((ref) async =>
    ref.watch(discoveryRepositoryProvider).fetchLikesReceivedCount());
