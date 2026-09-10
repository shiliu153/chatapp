import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'features/auth/login_page.dart';
import 'features/auth/session.dart';
import 'features/auth/splash_page.dart';
import 'features/common/placeholder_page.dart';
import 'features/profile/profile_edit_page.dart';
import 'features/shell/home_shell.dart';

final routerProvider = Provider<GoRouter>((ref) {
  // 会话状态变化 → 让 GoRouter 重新跑一遍 redirect
  final refreshSignal = ValueNotifier<int>(0);
  ref.listen(sessionProvider, (_, _) => refreshSignal.value++);
  ref.onDispose(refreshSignal.dispose);

  return GoRouter(
    initialLocation: '/splash',
    refreshListenable: refreshSignal,
    routes: [
      GoRoute(path: '/splash', builder: (context, state) => const SplashPage()),
      GoRoute(path: '/login', builder: (context, state) => const LoginPage()),
      GoRoute(
          path: '/onboarding',
          builder: (context, state) => const PlaceholderPage(title: '资料引导')),
      GoRoute(path: '/home', builder: (context, state) => const HomeShell()),
      GoRoute(path: '/profile/edit', builder: (context, state) => const ProfileEditPage()),
      GoRoute(
          path: '/preference',
          builder: (context, state) => const PlaceholderPage(title: '想找的人')),
      GoRoute(
          path: '/settings', builder: (context, state) => const PlaceholderPage(title: '设置')),
    ],
    redirect: (context, state) {
      final session = ref.read(sessionProvider);
      final location = state.matchedLocation;
      switch (session) {
        case SessionLoading() || SessionBootFailed():
          return location == '/splash' ? null : '/splash';
        case SessionLoggedOut():
          return location == '/login' ? null : '/login';
        case SessionLoggedIn():
          return (location == '/splash' || location == '/login') ? '/home' : null;
      }
    },
  );
});
