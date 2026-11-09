import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'models.dart';
import 'stats_repository.dart';

/// 当前选中的统计周期(默认「周」)。
///
/// 为什么和报告分成两个 provider:切周期时报告进入 loading、页面要出骨架,
/// 而**分段控件的选中态必须在这个 loading 期间保持不动** —— 用
/// `AsyncValue.loading()` 一把梭会把选中态也丢掉,控件会先弹回「周」再跳到「月」。
///
/// autoDispose:离开页面再进来回到默认的「周」(用户说的「默认周」是每次进入的口径)。
class StatsPeriodController extends Notifier<StatsPeriod> {
  @override
  StatsPeriod build() => StatsPeriod.week;

  /// 切到某个周期;报告 provider 跟着重建,即重新请求。
  void select(StatsPeriod period) => state = period;
}

final statsPeriodProvider =
    NotifierProvider.autoDispose<StatsPeriodController, StatsPeriod>(
  StatsPeriodController.new,
);

/// 选中周期的报告:`ref.watch(statsPeriodProvider)` 让切周期就等于重新请求。
///
/// 关掉自动重试(与 `blockedUsersProvider` 同口径):页面自带「重试」按钮,
/// 否则错误态会被自动重试闪一下再出现。
final statsReportProvider = FutureProvider.autoDispose<StatsReport>(
  (ref) => ref
      .watch(statsRepositoryProvider)
      .fetchReport(ref.watch(statsPeriodProvider)),
  retry: (retryCount, error) => null,
);
