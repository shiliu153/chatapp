import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'discovery_clock.dart';
import 'discovery_repository.dart';
import 'models.dart';

/// 「今日喜欢次数已用完」的业务码(`429` + `Retry-After`,discovery.md §3.10)。
const likeQuotaExceededCode = 42904;

/// 每日喜欢额度状态:后端快照 + 「额度用完」时对喜欢按钮的冷却闸门。
///
/// 两个字段各自独立:快照拿不到(接口 404 / 网络抖动)时只是**不显示**额度文案,
/// 不影响滑卡;冷却闸门只在真的收到过 `42904` 之后才非空。
class LikeQuotaState {
  const LikeQuotaState({this.quota, this.blockedUntil});

  /// 后端快照;还没拉到或拉失败时为 `null`。
  final LikeQuota? quota;

  /// `42904` 之后喜欢按钮禁用到这个时刻;`null` = 没禁用。
  final DateTime? blockedUntil;

  /// 要显示成「今日还可喜欢 N 次」的数字;`like_limit = 0`(不限)或没数据时为 `null`
  /// —— 调用方拿到 `null` 就整块不渲染。
  int? get likesRemaining {
    final snapshot = quota;
    if (snapshot == null || !snapshot.limited) return null;
    return snapshot.likesRemaining;
  }

  /// 现在能不能点喜欢。
  bool isBlockedAt(DateTime now) {
    final until = blockedUntil;
    return until != null && now.isBefore(until);
  }

  LikeQuotaState copyWith({LikeQuota? quota, DateTime? blockedUntil}) => LikeQuotaState(
        quota: quota ?? this.quota,
        blockedUntil: blockedUntil ?? this.blockedUntil,
      );
}

/// 每日喜欢额度:进页拉一次,喜欢成功本地减一,`42904` 时按 `Retry-After` 关按钮。
///
/// 额度默认关闭(`like_limit = 0`),那时后端不计数、界面整块不渲染 —— 不做任何特判。
class LikeQuotaController extends Notifier<LikeQuotaState> {
  @override
  LikeQuotaState build() {
    unawaited(refresh());
    return const LikeQuotaState();
  }

  /// 重新拉一次额度。失败静默:额度提示是锦上添花,不该拖垮发现页。
  Future<void> refresh() async {
    try {
      final quota = await ref.read(discoveryRepositoryProvider).fetchQuota();
      state = state.copyWith(quota: quota);
    } catch (_) {
      // 忽略:下次喜欢 / 撤销 / 重进页面还会再试
    }
  }

  /// 喜欢成功一次:本地先减一让文案立刻跟上,和后端差的一由下次 [refresh] 校正。
  void consumeOne() {
    final snapshot = state.quota;
    if (snapshot == null) return;
    state = state.copyWith(quota: snapshot.useOne());
  }

  /// 收到 `42904`:按 `Retry-After` 把喜欢按钮禁到那个时刻(通常是次日 0 点)。
  ///
  /// 拿不到 `Retry-After` 时不禁用 —— 后端下一次仍会给 42904,不猜一个假时长。
  void blockFor(Duration? wait) {
    if (wait == null || wait <= Duration.zero) return;
    state = state.copyWith(
      blockedUntil: ref.read(discoveryClockProvider)().add(wait),
    );
  }
}

final likeQuotaProvider =
    NotifierProvider<LikeQuotaController, LikeQuotaState>(LikeQuotaController.new);
