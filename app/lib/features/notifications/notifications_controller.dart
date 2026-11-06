import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'models.dart';
import 'notifications_repository.dart';

const _pageSize = 20;

/// 通知页状态:已加载的条目 + 分页游标。
class NotificationsState {
  const NotificationsState({
    required this.items,
    required this.count,
    this.hasMore = false,
    this.nextCursor,
  });

  final List<AppNotification> items;
  final int count;
  final bool hasMore;

  /// 下一页游标(后端 `next_cursor`);没有下一页时为 `null`。
  final String? nextCursor;

  /// 当前页里还有没有未读(「全部已读」按钮的可用态)。
  bool get hasUnread => items.any((item) => !item.isRead);

  NotificationsState copyWith({
    List<AppNotification>? items,
    int? count,
    bool? hasMore,
    String? nextCursor,
  }) =>
      NotificationsState(
        items: items ?? this.items,
        count: count ?? this.count,
        hasMore: hasMore ?? this.hasMore,
        nextCursor: nextCursor ?? this.nextCursor,
      );
}

/// 通知列表控制器:游标分页 + 标记已读(单条 / 全部)。
///
/// 标记已读后**本地先改状态**再刷新角标,避免用户回到消息页还看到旧角标。
class NotificationsController extends AsyncNotifier<NotificationsState> {
  bool _loadingMore = false;

  @override
  Future<NotificationsState> build() => _fetch();

  Future<NotificationsState> _fetch({String? cursor}) async {
    final page = await ref
        .read(notificationsRepositoryProvider)
        .fetch(limit: _pageSize, cursor: cursor);
    return NotificationsState(
      items: page.items,
      count: page.count,
      hasMore: page.nextCursor != null,
      nextCursor: page.nextCursor,
    );
  }

  Future<void> reload() async {
    state = const AsyncValue.loading();
    state = await AsyncValue.guard(_fetch);
  }

  Future<void> loadMore() async {
    final current = state.value;
    if (current == null || !current.hasMore || _loadingMore) return;
    _loadingMore = true;
    try {
      final page = await ref
          .read(notificationsRepositoryProvider)
          .fetch(limit: _pageSize, cursor: current.nextCursor);
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

  /// 标记单条已读;已经读过的直接返回(不重复请求)。
  Future<void> markRead(AppNotification item) async {
    if (item.isRead) return;
    await ref.read(notificationsRepositoryProvider).markRead(ids: [item.id]);
    _applyRead({item.id});
  }

  /// 全部标记已读;本地把已加载的条目一起改掉。
  Future<void> markAllRead() async {
    final current = state.value;
    if (current == null || !current.hasUnread) return;
    await ref.read(notificationsRepositoryProvider).markRead(all: true);
    _applyRead(current.items.map((item) => item.id).toSet());
  }

  void _applyRead(Set<int> ids) {
    final current = state.value;
    if (current == null) return;
    state = AsyncValue.data(current.copyWith(
      items: [
        for (final item in current.items)
          ids.contains(item.id) ? item.copyWith(isRead: true) : item,
      ],
    ));
    ref.invalidate(notificationsUnreadCountProvider);
  }
}

final notificationsProvider =
    AsyncNotifierProvider<NotificationsController, NotificationsState>(
  NotificationsController.new,
  retry: (retryCount, error) => null,
);

/// 入口角标:只查数量,不拉整页。
final notificationsUnreadCountProvider = FutureProvider<int>((ref) async =>
    ref.watch(notificationsRepositoryProvider).fetchUnreadCount());

/// 角标自动刷新间隔(默认 60 秒;`null` = 关闭轮询)。
///
/// 为什么需要它:本项目**不做离线推送**(backlog §4),角标只能靠拉。H 批交付时
/// 角标是纯 `FutureProvider`,App 常驻打开时不会自己更新(要重启或手动 invalidate),
/// 这是已知限制;轮询是「没有推送也能看到新通知」的最小代价。
/// 做成 provider 是为了让测试能关掉它(否则每个用例结束都有 pending Timer)或调快它。
final notificationsBadgeRefreshIntervalProvider =
    Provider<Duration?>((ref) => const Duration(seconds: 60));
