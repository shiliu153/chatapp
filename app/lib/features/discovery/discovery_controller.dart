import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../profile/models.dart';
import 'discovery_repository.dart';
import 'models.dart';

const _batchSize = 10;

/// 卡组剩这么少就开始悄悄续拉。
const _preloadThreshold = 3;

/// 发现页的临时筛选态(批次 S)。
///
/// **纯内存**:不写 shared_preferences、不调 `PATCH /users/me/preference` ——
/// 筛选是「这一次想换个范围看看」,偏好仍只在设置页改。`Notifier` 挂在
/// ProviderScope 上,所以首页 Tab 来回切(同一次 App 生命周期)筛选态不丢。
class DiscoveryFilterController extends Notifier<DiscoveryFilter> {
  @override
  DiscoveryFilter build() => DiscoveryFilter.none;

  /// 应用面板里选好的筛选;`DiscoveryFilter.none` 等价于「重置」。
  ///
  /// 值没变也照常写:候选池视图希望「应用」一定重新拉一次,所以由调用方决定
  /// 要不要额外 [DiscoveryController.reload];这里只负责存。
  void apply(DiscoveryFilter filter) => state = filter;

  /// 清空筛选,回到「沿用偏好」。
  void reset() => state = DiscoveryFilter.none;
}

final discoveryFilterProvider =
    NotifierProvider<DiscoveryFilterController, DiscoveryFilter>(
        DiscoveryFilterController.new);

/// 今日精选(批次 S,discovery.md §3.11);首页每天只拉一次,空数组 = 整块不渲染。
final dailyProvider = FutureProvider<DailyCandidates>(
  (ref) => ref.watch(discoveryRepositoryProvider).fetchDaily(),
  // 与 discoveryProvider 同口径:失败不自动重试,区块自己隐藏,不打扰滑卡
  retry: (retryCount, error) => null,
);

class DiscoveryController extends AsyncNotifier<List<Candidate>> {
  bool _loadingMore = false;

  /// 候选取数跟着筛选态走:筛选一变,build 重跑 → 自动重新拉候选池。
  @override
  Future<List<Candidate>> build() {
    final filter = ref.watch(discoveryFilterProvider);
    return _fetch(filter);
  }

  Future<List<Candidate>> _fetch([DiscoveryFilter? filter]) =>
      ref.read(discoveryRepositoryProvider).fetchCandidates(
          limit: _batchSize,
          filter: filter ?? ref.read(discoveryFilterProvider));

  Future<void> reload() async {
    state = const AsyncValue.loading();
    state = await AsyncValue.guard(_fetch);
  }

  /// 处理一次滑卡:先把卡从卡组移除(界面立刻响应),再提交后端。
  /// 失败把卡放回队首并原样抛出(页面弹提示);返回配对结果与共同标签
  /// (共同标签只在配对成功时非空,用于「配对那一刻」的破冰文案)。
  Future<({bool matched, List<Tag> sharedTags})> decide(Candidate candidate,
      {required bool like}) async {
    final current = state.value ?? const <Candidate>[];
    state = AsyncValue.data(
        current.where((item) => item.userId != candidate.userId).toList());
    try {
      final result = await ref
          .read(discoveryRepositoryProvider)
          .swipe(targetUserId: candidate.userId, like: like);
      unawaited(_preloadIfLow());
      return result;
    } catch (_) {
      final now = state.value ?? const <Candidate>[];
      state = AsyncValue.data([candidate, ...now]);
      rethrow;
    }
  }

  /// 撤销成功后把那张卡放回**卡堆顶部**(批次 O,discovery.md §3.9)。
  ///
  /// 用滑卡时缓存下来的那份卡面数据直出,不再请求后端(也避免续拉把他又发回来
  /// 时的重复卡);如果卡组里他已经被续拉回来了,只把他挪到队首。
  void restore(Candidate candidate) {
    final current = state.value ?? const <Candidate>[];
    final rest = current.where((item) => item.userId != candidate.userId).toList();
    state = AsyncValue.data([candidate, ...rest]);
  }

  /// 卡组快见底时续拉下一批;失败不打扰用户(空态里有「刷新」可以重来)。
  Future<void> _preloadIfLow() async {
    final current = state.value;
    if (_loadingMore || current == null || current.length > _preloadThreshold) return;
    _loadingMore = true;
    try {
      final batch = await _fetch();
      final now = state.value;
      if (now == null || batch.isEmpty) return;
      // 后端只排除「已划过」的人,卡组里还没划的人会被再发一次 —— 按 userId 去重,别出重复卡
      final existing = now.map((item) => item.userId).toSet();
      final fresh = batch.where((item) => !existing.contains(item.userId)).toList();
      if (fresh.isNotEmpty) {
        state = AsyncValue.data([...now, ...fresh]);
      }
    } catch (_) {
      // 忽略:下次滑卡会自动再试
    } finally {
      _loadingMore = false;
    }
  }
}

final discoveryProvider = AsyncNotifierProvider<DiscoveryController, List<Candidate>>(
  DiscoveryController.new,
  // Riverpod 3 默认失败重试(200ms 起指数退避);页面已有手动「重试」按钮,关掉更可预期
  retry: (retryCount, error) => null,
);
