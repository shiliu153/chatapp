import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../chat/match_cache.dart';
import 'discovery_repository.dart';
import 'models.dart';

const _pageSize = 20;

/// 「谁看过我」页面状态。
class VisitsState {
  const VisitsState({
    required this.items,
    required this.count,
    this.hasMore = false,
    this.nextCursor,
    this.busyUserId,
  });

  final List<Visit> items;
  final int count;
  final bool hasMore;

  /// 下一页游标(后端 `next_cursor`);没有下一页时为 `null`。
  final String? nextCursor;
  final int? busyUserId;

  VisitsState copyWith({
    List<Visit>? items,
    int? count,
    bool? hasMore,
    String? nextCursor,
    int? busyUserId,
    bool clearBusy = false,
  }) =>
      VisitsState(
        items: items ?? this.items,
        count: count ?? this.count,
        hasMore: hasMore ?? this.hasMore,
        nextCursor: nextCursor ?? this.nextCursor,
        busyUserId: clearBusy ? null : (busyUserId ?? this.busyUserId),
      );
}

/// 分页拉取 + 回喜欢编排(移除行、计数、配对缓存、角标)。
class VisitsController extends AsyncNotifier<VisitsState> {
  bool _loadingMore = false;

  @override
  Future<VisitsState> build() => _fetch(reset: true);

  Future<VisitsState> _fetch({required bool reset, String? cursor}) async {
    final page = await ref
        .read(discoveryRepositoryProvider)
        .fetchVisits(limit: _pageSize, cursor: cursor);
    final items = reset
        ? page.items
        : [...(state.value?.items ?? const <Visit>[]), ...page.items];
    return VisitsState(items: items, count: page.count,
        hasMore: page.nextCursor != null, nextCursor: page.nextCursor);
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
          .fetchVisits(limit: _pageSize, cursor: current.nextCursor);
      state = AsyncValue.data(current.copyWith(
        items: [...current.items, ...page.items],
        count: page.count,
        hasMore: page.nextCursor != null,
        nextCursor: page.nextCursor,
      ));
    } finally {
      _loadingMore = false;
    }
  }

  /// 回喜欢;需要弹配对动效时返回被喜欢的人,未配对返回 null。
  Future<Candidate?> accept(Visit item) async {
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
      ref.invalidate(visitsCountProvider);
      return matched ? item.candidate : null;
    } catch (_) {
      final now = state.value ?? current;
      state = AsyncValue.data(now.copyWith(clearBusy: true));
      await reload();
      rethrow;
    }
  }
}

final visitsProvider = AsyncNotifierProvider<VisitsController, VisitsState>(
  VisitsController.new,
  retry: (retryCount, error) => null,
);

/// 入口角标:只查数量,不拉整页。
final visitsCountProvider = FutureProvider<int>(
    (ref) async => ref.watch(discoveryRepositoryProvider).fetchVisitsCount());
