import 'package:flutter_riverpod/flutter_riverpod.dart';

/// 底栏四个 tab 的下标(「余烬 Ember」§9.1:遇见 / 回声 / 对话 / 我)。
///
/// 为什么要有这个 provider:tab 不是路由,`HomeShell` 用 `IndexedStack` + 本地下标
/// 切换;而空态里的「去遇见」这类**页内引导**需要主动切 tab。把下标提到 provider 里,
/// 页面按语义常量切换,不必知道 `HomeShell` 的实现,也不用为了跳 tab 新开一条路由
/// (那会让「对话 → 遇见」变成一层可回退的历史,与底栏语义冲突)。
abstract final class ShellTab {
  /// 遇见(发现)tab。
  static const discovery = 0;

  /// 回声(广场)tab。
  static const square = 1;

  /// 对话(会话列表)tab。
  static const chats = 2;

  /// 我(资料与设置)tab。
  static const mine = 3;
}

/// 当前选中的底栏 tab 下标(默认落在「遇见」,§9.1「永远默认落地页」)。
///
/// 用 [Notifier] 而不是已从 Riverpod 3 主入口移除的 `StateProvider`(legacy 才有):
/// 只需要「读当前值 + 切到某一 tab」两个动作,一个方法足够。
class ShellTabIndex extends Notifier<int> {
  @override
  int build() => ShellTab.discovery;

  /// 切到某个 tab(越界直接忽略,不给外壳抛异常的机会)。
  ///
  /// 参数说明:
  /// - [index] 目标 tab 下标,取 [ShellTab] 里的常量。
  void select(int index) {
    if (index < ShellTab.discovery || index > ShellTab.mine) return;
    state = index;
  }
}

/// 当前底栏 tab。
final shellTabIndexProvider = NotifierProvider<ShellTabIndex, int>(ShellTabIndex.new);
