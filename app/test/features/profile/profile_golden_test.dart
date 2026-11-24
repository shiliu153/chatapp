import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/core/theme/app_theme.dart';
import 'package:chatapp_app/core/ui/ember_ui.dart';
import 'package:chatapp_app/features/auth/session.dart';
import 'package:chatapp_app/features/presence/presence_controller.dart';
import 'package:chatapp_app/features/profile/my_profile_page.dart';
import 'package:chatapp_app/features/profile/user_profile_page.dart';
import 'package:chatapp_app/features/profile/widgets/profile_info_row.dart';
import 'package:chatapp_app/features/profile/widgets/profile_photo_header.dart';
import 'package:chatapp_app/im/im_manager.dart';

import '../../support/fake_im_client.dart';
import '../../support/harness.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

/// E-5.4 page spec §6 第 2 条:**8 张 golden**。
///
/// | 组 | 张数 | 覆盖 |
/// |---|---|---|
/// | 我的 | 2 | 明 / 暗 |
/// | 他人资料 | 2 | 明 / 暗 |
/// | 头图占位 | 2 | 明 / 暗 |
/// | 信息行 | 2 | 明 / 暗 |
///
/// 为什么是**组件/整页 golden**(而不是模拟器截图):这里比的是取值 —— 头图
/// `overlay.scrim` 叠字 `title` 24 Fraunces 白字、信息行「标签 17/w600 + 值
/// 15/`text.secondary`」、`EmberCard` 的 `radius.lg` + 明暗两套层级、头图占位的
/// `surface.sunken` + Phosphor `user` 64。设备字体、真实照片、滚动轨迹属于
/// **模拟器手测**的范围(PR 正文「等待模拟器验收」那一段)。
///
/// 照片层在 widget 测试里拿不到真图(所有 HTTP 都返回 400),所以整页 golden 里
/// 头图走的是「无照片」的内容占位 —— 这本身也是 §4 头图表里的一格,真照片由手测覆盖。
///
/// 重新生成:`cd app && flutter test --update-goldens test/features/profile/profile_golden_test.dart`
/// (只在**确认视觉改动就是想要的**之后跑,并人工看一眼 diff 图。)
const _loggedIn = {
  'auth.access': 'a',
  'auth.refresh': 'r',
  'auth.user_id': 7,
};

void main() {
  /// 固定视口 390×844(常见手机逻辑尺寸)+ dpr 1,截图不随机器变。
  void fixViewport(WidgetTester tester, {Size size = const Size(390, 844)}) {
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
  }

  Future<void> pumpMyProfile(
    WidgetTester tester, {
    required Brightness brightness,
  }) async {
    fixViewport(tester);
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson(
            id: 6,
            userId: 7,
            nickname: '小雨',
            gender: 'female',
            city: '杭州',
            bio: '周末爬山,平时看展',
            tags: [tagJson(1, '运动'), tagJson(2, '音乐'), tagJson(3, '旅行')],
          )),
    });
    await pumpApp(tester, adapter, prefs: {
      ..._loggedIn,
      // 与 main.dart 同一条路径:主题模式从 prefs 读,深色用例不用另造主题
      'theme_mode': brightness == Brightness.dark ? 'dark' : 'light',
    });
    await tester.pumpAndSettle();
    await tester.tap(navTab('我'));
    await tester.pumpAndSettle();
  }

  Future<void> pumpUserProfile(
    WidgetTester tester, {
    required Brightness brightness,
  }) async {
    fixViewport(tester);
    final adapter = ScriptedAdapter({
      'GET /users/9': (options) => ok(publicProfileJson(
            nickname: '小红',
            age: 25,
            city: '上海',
            bio: '喜欢爬山和看展',
            tags: [tagJson(1, '运动'), tagJson(2, '音乐')],
            photos: const [],
            followerCount: 12,
            followingCount: 8,
          )),
      'GET /matches': (options) => ok(pageJson([])),
      'GET /presence': (options) => ok({'results': []}),
    });
    final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))
      ..httpClientAdapter = adapter;
    final fake = FakeImClient();
    addTearDown(fake.dispose);
    final container = ProviderContainer(overrides: [
      baseDioProvider.overrideWithValue(dio),
      refreshDioProvider.overrideWithValue(dio),
      imClientProvider.overrideWithValue(fake),
      imStatusProvider.overrideWith(_LoggedInImManager.new),
      sessionProvider.overrideWith(_LoggedInSession.new),
      presenceRefreshIntervalProvider.overrideWithValue(null),
    ]);
    addTearDown(container.dispose);
    final router = GoRouter(
      initialLocation: '/users/9',
      routes: [
        GoRoute(
          path: '/',
          builder: (context, state) => const Scaffold(body: Text('首页')),
        ),
        GoRoute(
          path: '/users/:id',
          builder: (context, state) =>
              UserProfilePage(userId: int.parse(state.pathParameters['id']!)),
        ),
      ],
    );
    await tester.pumpWidget(UncontrolledProviderScope(
      container: container,
      child: MaterialApp.router(
        theme: buildAppTheme(brightness: brightness),
        themeAnimationDuration: Duration.zero,
        routerConfig: router,
      ),
    ));
    await tester.pumpAndSettle();
  }

  /// 组件级场景:与发现页 golden 同款布置(居中 + 20 内边距 + 关动效)。
  Future<void> pumpScene(
    WidgetTester tester,
    Widget child, {
    required Brightness brightness,
    Size size = const Size(390, 320),
  }) async {
    fixViewport(tester, size: size);
    await tester.pumpWidget(
      MaterialApp(
        theme: buildAppTheme(brightness: brightness),
        themeAnimationDuration: Duration.zero,
        home: MediaQuery(
          data: MediaQueryData(size: size, disableAnimations: true),
          child: Scaffold(
            body: Center(
              child: Padding(padding: const EdgeInsets.all(20), child: child),
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
  }

  for (final brightness in Brightness.values) {
    final mode = brightness == Brightness.light ? 'light' : 'dark';

    testWidgets('我的 golden · $mode', (tester) async {
      await pumpMyProfile(tester, brightness: brightness);
      await expectLater(
        find.byType(MyProfilePage),
        matchesGoldenFile('goldens/my_profile_$mode.png'),
      );
    });

    testWidgets('他人资料 golden · $mode', (tester) async {
      await pumpUserProfile(tester, brightness: brightness);
      await expectLater(
        find.byType(UserProfilePage),
        matchesGoldenFile('goldens/user_profile_$mode.png'),
      );
    });

    testWidgets('头图占位 golden · $mode', (tester) async {
      await pumpScene(
        tester,
        const SizedBox(
          width: 350,
          child: ProfilePhotoHeader(
            photoUrl: null,
            nickname: '小红',
            age: 25,
            city: '上海',
          ),
        ),
        brightness: brightness,
        size: const Size(390, 520),
      );
      await expectLater(
        find.byType(ProfilePhotoHeader),
        matchesGoldenFile('goldens/photo_header_placeholder_$mode.png'),
      );
    });

    testWidgets('信息行 golden · $mode', (tester) async {
      await pumpScene(
        tester,
        EmberCard(
          padding: EdgeInsets.zero,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              ProfileInfoRow(label: '城市', value: '上海'),
              ProfileInfoRow(label: '简介', value: '喜欢爬山和看展'),
              ProfileInfoRow(
                label: '标签',
                value: '运动、音乐',
                showDivider: false,
                child: Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: const [
                    EmberChip(label: '运动', readOnly: true),
                    EmberChip(label: '音乐', readOnly: true),
                  ],
                ),
              ),
            ],
          ),
        ),
        brightness: brightness,
        size: const Size(390, 360),
      );
      await expectLater(
        find.byType(EmberCard),
        matchesGoldenFile('goldens/info_row_$mode.png'),
      );
    });
  }
}

/// 资料页用例都直接当已登录:跳会话 / 拉配对缓存都依赖它。
class _LoggedInSession extends SessionController {
  @override
  SessionState build() => const SessionLoggedIn();
}

/// IM 直接已登录(测试里裸 await 登录会撞假时钟死锁,见 chat_page_test 同款注释)。
class _LoggedInImManager extends ImManager {
  @override
  ImStatus build() => const ImLoggedIn('u3');
}
