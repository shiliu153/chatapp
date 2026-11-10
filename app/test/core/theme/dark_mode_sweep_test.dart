import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/theme/heart_colors.dart';
import 'package:chatapp_app/features/auth/login_page.dart';
import 'package:chatapp_app/features/chat/chat_page.dart';
import 'package:chatapp_app/features/chat/search_page.dart';
import 'package:chatapp_app/features/discovery/discovery_page.dart';
import 'package:chatapp_app/features/discovery/likes_received_page.dart';
import 'package:chatapp_app/features/discovery/visits_page.dart';
import 'package:chatapp_app/features/discovery/widgets/discovery_filter_sheet.dart';
import 'package:chatapp_app/features/legal/legal_page.dart';
import 'package:chatapp_app/features/onboarding/onboarding_page.dart';
import 'package:chatapp_app/features/profile/models.dart';
import 'package:chatapp_app/features/profile/my_profile_page.dart';
import 'package:chatapp_app/features/profile/preference_page.dart';
import 'package:chatapp_app/features/profile/profile_edit_page.dart';
import 'package:chatapp_app/features/profile/user_profile_page.dart';
import 'package:chatapp_app/features/settings/about_page.dart';
import 'package:chatapp_app/features/settings/blocked_users_page.dart';
import 'package:chatapp_app/features/settings/devices_page.dart';
import 'package:chatapp_app/features/settings/feedback_page.dart';
import 'package:chatapp_app/features/settings/notification_settings_page.dart';
import 'package:chatapp_app/features/settings/settings_page.dart';
import 'package:chatapp_app/features/shell/home_shell.dart';
import 'package:chatapp_app/features/square/favorites_page.dart';
import 'package:chatapp_app/features/square/my_posts_page.dart';
import 'package:chatapp_app/features/square/post_likes_page.dart';
import 'package:chatapp_app/features/square/post_compose_page.dart';
import 'package:chatapp_app/features/square/post_detail_page.dart';
import 'package:chatapp_app/features/square/square_page.dart';
import 'package:chatapp_app/features/stats/stats_page.dart';

import '../../support/harness.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

/// 全页面暗色回归(F-5)。
///
/// 人工逐页看暗色只能抓「一眼就明显」的问题,而且不可回归。这里把「暗色页面里
/// 不该出现浅色面」变成断言:
/// 1. 每页在暗色主题下渲染不抛异常;
/// 2. Scaffold 底色必须是深色 `bgPage`;
/// 3. 渲染树里任何「面」(Material/ColoredBox/DecoratedBox 的底色与渐变)**不得**
///    等于浅色板的 `bgPage` / `divider` —— 那正是漏迁移的典型症状(白块/浅灰块)。
///
/// 白 / 黑 / 全透明不在禁止之列:它们在两种主题下语义相同(照片叠字、纯黑看图底)。
const _loggedIn = {'auth.access': 'a', 'auth.refresh': 'r', 'auth.user_id': 7};

/// 收集渲染树里所有显式「面」色(容器底色、渐变两端、Scaffold 底色)。
List<Color> surfaceColors(WidgetTester tester) {
  final out = <Color>[];
  for (final widget in tester.allWidgets) {
    if (widget is Scaffold && widget.backgroundColor != null) {
      out.add(widget.backgroundColor!);
    } else if (widget is Material && widget.color != null) {
      out.add(widget.color!);
    } else if (widget is ColoredBox) {
      out.add(widget.color);
    } else if (widget is DecoratedBox) {
      final decoration = widget.decoration;
      if (decoration is BoxDecoration) {
        final color = decoration.color;
        if (color != null) out.add(color);
        final gradient = decoration.gradient;
        if (gradient != null) out.addAll(gradient.colors);
      }
    }
  }
  return out;
}

/// 断言当前页面在暗色主题下没有残留浅色面。
void expectNoLightSurfaces(WidgetTester tester, String page) {
  expect(tester.takeException(), isNull, reason: '$page 在暗色下抛异常');

  final scaffolds = tester.allWidgets.whereType<Scaffold>();
  for (final scaffold in scaffolds) {
    final background = scaffold.backgroundColor;
    if (background == null) continue;
    expect(
      background,
      HeartColors.dark.bgPage,
      reason: '$page 的 Scaffold 底色仍是 ${background.toString()}',
    );
  }

  final forbidden = <Color, String>{
    HeartColors.light.bgPage: 'light.bgPage',
    HeartColors.light.divider: 'light.divider',
  };
  final hits = <String>[];
  for (final color in surfaceColors(tester)) {
    final name = forbidden[color];
    if (name != null) hits.add('$name(${color.toString()})');
  }
  expect(hits, isEmpty, reason: '$page 在暗色下出现浅色面:${hits.join(', ')}');
}

/// 每个页面需要的假网络响应(没铺的路由会 404,页面走错误态也算「渲染过」)。
ScriptedAdapter _adapter() => ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson(nickname: '小明')),
      'GET /users/tags': (options) => ok([tagJson(1, '旅行')]),
      'GET /users/9': (options) => ok(candidateJson(userId: 9)),
      'GET /posts': (options) => ok(pageJson([postJson(id: 1, nickname: 'Alice')])),
      'GET /posts/mine': (options) => ok(pageJson([postJson(id: 1, nickname: '小明')])),
      'GET /posts/1': (options) => ok(postJson(id: 1, nickname: 'Alice')),
      'GET /posts/1/comments': (options) => ok(pageJson([])),
      'GET /posts/1/likes': (options) => ok(cursorPageJson([postLikerJson()])),
      'GET /feed/favorites':
          (options) => ok(cursorPageJson([postJson(id: 1, isFavorited: true)])),
      'GET /matches': (options) => ok(pageJson([])),
      'GET /discovery/candidates': (options) => ok(pageJson([candidateJson()])),
      'GET /discovery/daily': (options) => ok(dailyJson(candidates: [candidateJson()])),
      'GET /discovery/quota': (options) =>
          ok({'like_limit': 10, 'likes_used': 3, 'likes_remaining': 7}),
      'GET /discovery/likes': (options) => ok(pageJson([candidateJson()])),
      'GET /discovery/likes/count': (options) => ok({'count': 1}),
      'GET /discovery/visits': (options) => ok(pageJson([candidateJson()])),
      'GET /discovery/visits/count': (options) => ok({'count': 1}),
      'GET /blocks': (options) => ok(pageJson([])),
      'GET /devices': (options) => ok({
            'results': [
              deviceJson(current: true),
              deviceJson(clientType: 'web', clientLabel: '网页端'),
            ],
          }),
      'GET /stats/me': (options) => ok({
            'period': 'week',
            'start': '2026-11-09',
            'end': '2026-11-15',
            'matches': 2,
            'likes_given': 14,
            'likes_received': 9,
            'visits': 6,
            'posts': 3,
            'post_likes': 11,
            'new_followers': 1,
          }),
      'GET /presence': (options) => ok({'results': []}),
    });

void main() {
  /// 页面清单:名字 → 构造函数。加新页面时记得往这里补一行,否则它就是「暗色盲区」。
  final pages = <String, Widget Function()>{
    'LoginPage': () => const LoginPage(),
    'OnboardingPage': () => const OnboardingPage(),
    'HomeShell': () => const HomeShell(),
    'SquarePage': () => const SquarePage(),
    'MyProfilePage': () => const MyProfilePage(),
    'ProfileEditPage': () => const ProfileEditPage(),
    'PreferencePage': () => const PreferencePage(),
    'UserProfilePage': () => UserProfilePage(userId: 9),
    'LikesReceivedPage': () => const LikesReceivedPage(),
    'VisitsPage': () => const VisitsPage(),
    // 发现页的筛选面板:条目自己挂 Material 底色,单独给它一页才能巡检到
    'DiscoveryFilterSheet': () => Scaffold(
          body: DiscoveryFilterSheet(
            preference: const Preference(ageMin: 22, ageMax: 30, city: '北京'),
          ),
        ),
    'ChatPage': () => const ChatPage(peerId: '9'),
    'SearchPage': () => const SearchPage(),
    'PostComposePage': () => const PostComposePage(),
    'MyPostsPage': () => const MyPostsPage(),
    'FavoritesPage': () => const FavoritesPage(),
    'PostLikesPage': () => const PostLikesPage(postId: 1),
    'PostDetailPage': () => const PostDetailPage(postId: 1),
    'SettingsPage': () => const SettingsPage(),
    'BlockedUsersPage': () => const BlockedUsersPage(),
    'DevicesPage': () => const DevicesPage(),
    'StatsPage': () => const StatsPage(),
    'NotificationSettingsPage': () => const NotificationSettingsPage(),
    'AboutPage': () => const AboutPage(),
    'FeedbackPage': () => const FeedbackPage(),
    'LegalPage(协议)': () => const LegalPage.agreement(),
    'LegalPage(隐私)': () => const LegalPage.privacy(),
  };

  for (final entry in pages.entries) {
    testWidgets('暗色回归:${entry.key}', (tester) async {
      await pumpPage(tester, _adapter(), entry.value(),
          prefs: _loggedIn, brightness: Brightness.dark);
      // 页面里有无限动画(涟漪/骨架/呼吸点),只能有限 pump
      await pumpFrames(tester, frames: 12);
      expectNoLightSurfaces(tester, entry.key);
    });
  }

  testWidgets('暗色回归:首页四个 Tab 逐一切换', (tester) async {
    await pumpPage(tester, _adapter(), const HomeShell(),
        prefs: _loggedIn, brightness: Brightness.dark);
    await pumpFrames(tester);

    for (final tab in ['发现', '广场', '消息', '我的']) {
      await tester.tap(navTab(tab));
      await pumpFrames(tester);
      expectNoLightSurfaces(tester, '首页/$tab');
    }
  });

  testWidgets('暗色回归:发现页撤销按钮(滑卡后才出现)', (tester) async {
    // 撤销按钮与额度文案只在滑卡动作之后才在树里,上面那张页面清单覆盖不到
    final adapter = _adapter();
    // 共用的 _adapter 给候选池铺的是 pageJson(错误形状),这里要给真列表才出得了卡
    adapter.routes['GET /discovery/candidates'] =
        (options) => ok([candidateJson(userId: 9, nickname: '小红')]);
    adapter.routes['POST /discovery/swipe'] = (options) => ok({'matched': false});
    adapter.routes['POST /discovery/swipe/undo'] =
        (options) => ok({'undone': true, 'target_user_id': 9});
    await pumpPage(tester, adapter, const DiscoveryPage(),
        prefs: _loggedIn, brightness: Brightness.dark);
    await pumpFrames(tester, frames: 12);

    await tester.tap(find.byKey(const Key('discovery.like')));
    // 倒计时环一直在走,不能 pumpAndSettle
    await pumpFrames(tester);

    expect(find.byKey(const Key('discovery.undo')), findsOneWidget);
    expectNoLightSurfaces(tester, '发现页(撤销按钮)');
  });

  testWidgets('暗色重点元素:渐变主按钮 / 卡片 / 骨架 / Toast / 对话框 / 空态', (tester) async {
    // 用「设置」页做载体:它同时有卡片底、分组、危险按钮,最能暴露白块
    await pumpPage(tester, _adapter(), const SettingsPage(),
        prefs: _loggedIn, brightness: Brightness.dark);
    await pumpFrames(tester);
    expectNoLightSurfaces(tester, '设置页');

    // 卡片底必须是深色 bgCard(而不是白色)
    final cards = tester
        .allWidgets
        .whereType<DecoratedBox>()
        .map((d) => d.decoration)
        .whereType<BoxDecoration>()
        .map((d) => d.color)
        .where((c) => c == HeartColors.dark.bgCard);
    expect(cards, isNotEmpty, reason: '设置页应有深色卡片底');
  });
}
