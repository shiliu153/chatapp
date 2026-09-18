import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../chat/chats_page.dart';
import '../chat/conversations_controller.dart';
import '../discovery/discovery_page.dart';
import '../profile/my_profile_page.dart';
import '../profile/profile_controller.dart';
import '../square/square_page.dart';
import 'app_bottom_bar.dart';
import 'banned_page.dart';

class HomeShell extends ConsumerStatefulWidget {
  const HomeShell({super.key});

  @override
  ConsumerState<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends ConsumerState<HomeShell> {
  int _index = 0;

  static const _pages = [DiscoveryPage(), SquarePage(), ChatsPage(), MyProfilePage()];

  @override
  Widget build(BuildContext context) {
    final profile = ref.watch(profileProvider).value;
    if (profile != null && profile.status == 'banned_heavy') {
      return BannedPage(profile: profile);
    }
    final unread = ref.watch(unreadTotalProvider);
    return Scaffold(
      body: IndexedStack(index: _index, children: _pages),
      bottomNavigationBar: AppBottomBar(
        currentIndex: _index,
        onTap: (index) => setState(() => _index = index),
        unreadCount: unread,
      ),
    );
  }
}
