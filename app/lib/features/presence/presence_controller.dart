import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'models.dart';
import 'presence_repository.dart';

/// 刷新间隔;override 成 null 关闭周期刷新(测试默认关,同步长心跳)。
final presenceRefreshIntervalProvider =
    Provider<Duration?>((ref) => const Duration(seconds: 45));

/// 共享在线状态缓存:各页面在自己的 build 里 `track(owner, ids)` 登记关心的人,
/// 合并去重后统一拉取。autoDispose:没有页面 watch 时定时器随之取消。
class PresenceController extends Notifier<Map<int, Presence>> {
  final Map<String, List<int>> _owners = {};
  Timer? _timer;
  bool _fetchScheduled = false;

  @override
  Map<int, Presence> build() {
    ref.onDispose(() => _timer?.cancel());
    return const {};
  }

  /// 登记某个页面(owner)关心的 userIds。只更新内部集合、**不在这里同步改 state**
  /// —— 它会被页面在 build 里调用,同步改 provider 会触发 Riverpod 断言;
  /// state 只在异步拉取返回后写。
  void track(String owner, List<int> userIds) {
    final current = _owners[owner];
    if (current != null &&
        current.length == userIds.length &&
        userIds.every(current.contains)) {
      return;
    }
    _owners[owner] = List.of(userIds);
    _startTimer();
    _scheduleFetch();
  }

  void _startTimer() {
    if (_timer != null) return;
    final interval = ref.read(presenceRefreshIntervalProvider);
    if (interval == null || interval <= Duration.zero) return;
    _timer = Timer.periodic(interval, (_) => refresh());
  }

  /// 同帧多次 track 合并成一次请求。
  void _scheduleFetch() {
    if (_fetchScheduled) return;
    _fetchScheduled = true;
    Future.microtask(() async {
      _fetchScheduled = false;
      await refresh();
    });
  }

  /// 拉一轮;失败保留旧值、下个周期再试(点缀信息,不弹提示)。
  Future<void> refresh() async {
    final ids = <int>{for (final list in _owners.values) ...list}.toList();
    if (ids.isEmpty) return;
    try {
      final fresh = await ref.read(presenceRepositoryProvider).fetchPresence(ids);
      final next = Map<int, Presence>.from(state)
        ..removeWhere((id, _) => ids.contains(id));
      next.addAll(fresh);
      state = next;
    } catch (_) {
      // 网络抖动:保持旧数据,别打扰用户
    }
  }
}

final presenceProvider =
    NotifierProvider.autoDispose<PresenceController, Map<int, Presence>>(
        PresenceController.new);
