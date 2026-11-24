import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../chat/chats_page.dart';
import '../chat/conversations_controller.dart';
import '../discovery/discovery_page.dart';
import '../profile/my_profile_page.dart';
import '../profile/profile_controller.dart';
import '../square/square_page.dart';
import 'banned_page.dart';
import 'ember_nav_bar.dart';
import 'shell_tab.dart';

/// 四个 tab 的容器(「余烬 Ember」§9.1)。
///
/// 选中哪个 tab 存在 `shellTabIndexProvider` 里(不再是本组件的私有字段):
/// 页内引导(如会话列表空态的「去遇见」)要能主动切 tab,而 tab 不是路由 —— 见
/// `shell_tab.dart` 的注释。
class HomeShell extends ConsumerWidget {
  /// 构造外壳。
  const HomeShell({super.key});

  static const _pages = [DiscoveryPage(), SquarePage(), ChatsPage(), MyProfilePage()];

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final profile = ref.watch(profileProvider).value;
    if (profile != null && profile.status == 'banned_heavy') {
      return BannedPage(profile: profile);
    }
    final index = ref.watch(shellTabIndexProvider);
    final unread = ref.watch(unreadTotalProvider);
    return Scaffold(
      body: IndexedStack(index: index, children: _pages),
      bottomNavigationBar: EmberNavBar(
        currentIndex: index,
        onTap: (next) => ref.read(shellTabIndexProvider.notifier).select(next),
        unreadCount: unread,
      ),
    );
  }
}
