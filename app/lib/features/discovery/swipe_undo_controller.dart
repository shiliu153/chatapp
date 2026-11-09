import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_exception.dart';
import 'discovery_clock.dart';
import 'discovery_controller.dart';
import 'discovery_repository.dart';
import 'like_quota_controller.dart';
import 'models.dart';

/// 撤销窗口(discovery.md §3.9):超过这么久按钮置灰,后端同样回 `40003`。
const swipeUndoWindow = Duration(seconds: 30);

/// 「没有可撤销的滑卡」的业务码(`400`):本来没记录 / 超过 30 秒 / 已配对(含已解除)。
const undoSwipeUnavailableCode = 40003;

/// 能撤销的那一次滑卡:目标卡 + 前端拿到滑卡响应的时间(倒计时起点)。
class UndoableSwipe {
  const UndoableSwipe({required this.candidate, required this.at});

  /// 被划掉的那张卡;撤销成功后原样放回卡堆顶部,不必再请求后端。
  final Candidate candidate;

  /// 滑卡响应到达的时间,倒计时环从这里起算。
  final DateTime at;
}

/// 只记得「最近一次」滑卡 —— 更早的即使还在 30 秒内,后端也不让撤(§3.9)。
class SwipeUndoController extends Notifier<UndoableSwipe?> {
  @override
  UndoableSwipe? build() => null;

  /// 滑卡成功后记一笔;每一次成功滑卡都会覆盖上一次(只有最近一次可撤)。
  void remember(Candidate candidate) {
    state = UndoableSwipe(
      candidate: candidate,
      at: ref.read(discoveryClockProvider)(),
    );
  }

  /// 本地抹掉:撤销成功后再撤就是「连撤两次」,或后端回了 `40003`。
  void forget() => state = null;

  /// 撤销最近一次滑卡:成功把那张卡放回卡堆顶部并返回它;失败原样抛 [ApiException]。
  Future<Candidate> undo() async {
    final current = state;
    if (current == null) throw ApiException('没有可撤销的操作');
    await ref.read(discoveryRepositoryProvider).undoSwipe();
    state = null;
    ref.read(discoveryProvider.notifier).restore(current.candidate);
    // 撤销一次喜欢后端会退回一次额度(§3.9),这里顺手把文案校正回来
    unawaited(ref.read(likeQuotaProvider.notifier).refresh());
    return current.candidate;
  }
}

final swipeUndoProvider =
    NotifierProvider<SwipeUndoController, UndoableSwipe?>(SwipeUndoController.new);
