import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'core/theme/ember_motion.dart';
import 'features/auth/login_page.dart';
import 'features/auth/session.dart';
import 'features/auth/splash_page.dart';
import 'features/chat/chat_page.dart';
import 'features/chat/search_page.dart';
import 'features/discovery/likes_received_page.dart';
import 'features/discovery/visits_page.dart';
import 'features/legal/legal_page.dart';
import 'features/notifications/notifications_page.dart';
import 'features/onboarding/onboarding_page.dart';
import 'features/profile/preference_page.dart';
import 'features/profile/profile_edit_page.dart';
import 'features/profile/user_profile_page.dart';
import 'features/settings/about_page.dart';
import 'features/settings/blocked_users_page.dart';
import 'features/settings/devices_page.dart';
import 'features/settings/feedback_page.dart';
import 'features/settings/notification_settings_page.dart';
import 'features/settings/settings_page.dart';
import 'features/shell/home_shell.dart';
import 'features/square/favorites_page.dart';
import 'features/square/my_posts_page.dart';
import 'features/square/post_compose_page.dart';
import 'features/square/post_likes_page.dart';
import 'features/square/post_detail_args.dart';
import 'features/square/post_detail_page.dart';
import 'features/stats/stats_page.dart';

/// 二级页统一转场(§9.3 / §9.4 + §7.1):从右滑入,位移用 `spring.standard`;
/// 系统开了「减弱动态效果」时退化成 **120ms 线性淡入**(§8.4),不做位移。
///
/// 为什么逐条写 `pageBuilder` 而不是全局换掉页面转场:§9.4 的「二级页右滑入」只在
/// 已迁移的页面上生效,其余二级页还没迁(E-5.6),全局改会把它们的转场一起改掉。
///
/// Hero 与这条转场的关系(E-5.5 page spec §1 第 9 条):`disableAnimations` 为真时
/// Hero 自己就不包了(`PostImageHero` / `CardHero` 都静默降级),转场同时退成淡入 ——
/// 于是「图片 Hero 转场退化为淡入」是这两处一起成立的结果。
///
/// 参数说明:
/// - [context] Navigator 侧上下文:从 MediaQuery 读「是否减弱动态效果」,据此选
///   转场时长(120ms 淡入 / 320ms 滑入)。
/// - [state] go_router 的路由状态(取 key)。
/// - [child] 目标页面。
///
/// Returns:
///   带弹簧位移(或减弱动态效果下的淡入)转场的页面。
CustomTransitionPage<void> subPageRoute(
  BuildContext context,
  GoRouterState state,
  Widget child,
) {
  final reduced = MediaQuery.maybeDisableAnimationsOf(context) ?? false;
  return CustomTransitionPage<void>(
    key: state.pageKey,
    transitionDuration: reduced ? EmberMotion.reduced : const Duration(milliseconds: 320),
    reverseTransitionDuration:
        reduced ? EmberMotion.reduced : const Duration(milliseconds: 240),
    child: child,
    transitionsBuilder: (context, animation, secondaryAnimation, child) {
      // 减弱动态效果:只淡入,不位移、不缩放(§8.4)。
      if (reduced) return FadeTransition(opacity: animation, child: child);
      // 只关心「进入 / 退出」这一条 spring,`secondaryAnimation` 留给下层页面
      // 自己画(这里不改下层,避免与被推走的列表叠出双层位移)。
      return SlideTransition(
        position: Tween<Offset>(
          begin: const Offset(1, 0),
          end: Offset.zero,
        ).animate(
          CurvedAnimation(
            parent: animation,
            curve: EmberMotion.springCurve(EmberMotion.standard),
          ),
        ),
        child: child,
      );
    },
  );
}

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
      GoRoute(path: '/settings/devices', builder: (context, state) => const DevicesPage()),
      GoRoute(path: '/settings/notifications',
          builder: (context, state) => const NotificationSettingsPage()),
      GoRoute(path: '/settings/about', builder: (context, state) => const AboutPage()),
      GoRoute(path: '/settings/stats', builder: (context, state) => const StatsPage()),
      GoRoute(path: '/settings/feedback',
          builder: (context, state) => const FeedbackPage()),
      GoRoute(path: '/likes', builder: (context, state) => const LikesReceivedPage()),
      GoRoute(path: '/visits', builder: (context, state) => const VisitsPage()),
      GoRoute(path: '/notifications',
          builder: (context, state) => const NotificationsPage()),
      GoRoute(
        path: '/chat/:peerId',
        // 二级页右滑入(E-5.3 page spec §1 第 7 条):位移用 `spring.standard`,
        // 不用 Material 默认的曲线;减弱动态效果时直接落终态(§7.3)。
        pageBuilder: (context, state) => subPageRoute(
          context,
          state,
          ChatPage(
            peerId: state.pathParameters['peerId']!,
            focusMsgId: state.uri.queryParameters['focus'],
          ),
        ),
      ),
      GoRoute(path: '/search', builder: (context, state) => const SearchPage()),
      GoRoute(
        path: '/users/:id',
        builder: (context, state) => UserProfilePage(
          userId: int.parse(state.pathParameters['id']!),
          // Hero tag(附录 C.7);深链/无来源时为 null,两端都不包 Hero
          heroTag: state.extra as String?,
        ),
      ),
      GoRoute(path: '/posts/compose', builder: (context, state) => const PostComposePage()),
      GoRoute(path: '/my-posts', builder: (context, state) => const MyPostsPage()),
      GoRoute(path: '/favorites', builder: (context, state) => const FavoritesPage()),
      // 点赞列表必须比 /posts/:id 更具体:它多一段,go_router 按整条路径匹配不会串
      GoRoute(
        path: '/posts/:id/likes',
        builder: (context, state) => PostLikesPage(
          postId: int.parse(state.pathParameters['id']!),
        ),
      ),
      GoRoute(
        path: '/posts/:id',
        // 动态详情是二级页(§9.3 沉浸内容):右滑入 + 图片 Hero;
        // 减弱动态效果时转场退成淡入(Hero 由 PostImageHero 自己让位)。
        pageBuilder: (context, state) {
          final args = state.extra is PostDetailArgs
              ? state.extra as PostDetailArgs
              : null; // 深链/无来源:extra 不是 PostDetailArgs(或为 null)
          return subPageRoute(
            context,
            state,
            PostDetailPage(
              postId: int.parse(state.pathParameters['id']!),
              args: args,
            ),
          );
        },
      ),
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
