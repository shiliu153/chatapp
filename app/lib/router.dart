import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'features/auth/login_page.dart';
import 'features/auth/session.dart';
import 'features/auth/splash_page.dart';
import 'features/chat/chat_page.dart';
import 'features/legal/legal_page.dart';
import 'features/onboarding/onboarding_page.dart';
import 'features/profile/preference_page.dart';
import 'features/profile/profile_edit_page.dart';
import 'features/profile/user_profile_page.dart';
import 'features/settings/blocked_users_page.dart';
import 'features/settings/settings_page.dart';
import 'features/shell/home_shell.dart';
import 'features/square/post_compose_page.dart';

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
      GoRoute(path: '/onboarding', builder: (context, state) => const OnboardingPage()),
      GoRoute(path: '/home', builder: (context, state) => const HomeShell()),
      GoRoute(path: '/profile/edit', builder: (context, state) => const ProfileEditPage()),
      GoRoute(path: '/preference', builder: (context, state) => const PreferencePage()),
      GoRoute(path: '/settings', builder: (context, state) => const SettingsPage()),
      GoRoute(path: '/settings/blocks', builder: (context, state) => const BlockedUsersPage()),
      GoRoute(
        path: '/chat/:peerId',
        builder: (context, state) => ChatPage(peerId: state.pathParameters['peerId']!),
      ),
      GoRoute(
        path: '/users/:id',
        builder: (context, state) =>
            UserProfilePage(userId: int.parse(state.pathParameters['id']!)),
      ),
      GoRoute(path: '/posts/compose', builder: (context, state) => const PostComposePage()),
      GoRoute(path: '/legal/agreement', builder: (context, state) => const LegalPage.agreement()),
      GoRoute(path: '/legal/privacy', builder: (context, state) => const LegalPage.privacy()),
    ],
    redirect: (context, state) {
      final session = ref.read(sessionProvider);
      final location = state.matchedLocation;
      switch (session) {
        case SessionLoading() || SessionBootFailed():
          // 协议全文是公开文本,首启弹窗里要能打开
          return (location == '/splash' || location.startsWith('/legal')) ? null : '/splash';
        case SessionLoggedOut():
          return (location == '/login' || location.startsWith('/legal')) ? null : '/login';
        case SessionLoggedIn():
          return (location == '/splash' || location == '/login') ? '/home' : null;
      }
    },
  );
});
