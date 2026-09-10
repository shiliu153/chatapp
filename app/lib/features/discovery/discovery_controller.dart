import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'discovery_repository.dart';
import 'models.dart';

const _batchSize = 10;

/// 卡组剩这么少就开始悄悄续拉。
const _preloadThreshold = 3;

class DiscoveryController extends AsyncNotifier<List<Candidate>> {
  bool _loadingMore = false;

  @override
  Future<List<Candidate>> build() => _fetch();

  Future<List<Candidate>> _fetch() =>
      ref.read(discoveryRepositoryProvider).fetchCandidates(limit: _batchSize);

  Future<void> reload() async {
    state = const AsyncValue.loading();
    state = await AsyncValue.guard(_fetch);
  }

  /// 处理一次滑卡:先把卡从卡组移除(界面立刻响应),再提交后端。
  /// 失败把卡放回队首并原样抛出(页面弹提示);返回是否配对成功。
  Future<bool> decide(Candidate candidate, {required bool like}) async {
    final current = state.value ?? const <Candidate>[];
    state = AsyncValue.data(
        current.where((item) => item.userId != candidate.userId).toList());
    try {
      final matched = await ref
          .read(discoveryRepositoryProvider)
          .swipe(targetUserId: candidate.userId, like: like);
      unawaited(_preloadIfLow());
      return matched;
    } catch (_) {
      final now = state.value ?? const <Candidate>[];
      state = AsyncValue.data([candidate, ...now]);
      rethrow;
    }
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
