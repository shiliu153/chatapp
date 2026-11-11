// L3 golden(批次 W-L3):把「App 长什么样」也变成 CI 的判据。
//
// 为什么**单独一个文件**、而不是并进 smoke_test.dart:
//   smoke 断言的是**行为**(后端不可达也能落到登录页),红了结论很明确;
//   这里断言的是**像素**,红了有两种完全不同的原因 —— 外观真的变了,或者跑图的机器变了。
//   混在一个用例里,视觉回归会把行为信号淹掉;而且临时跳过 golden(换镜像/换字体)时
//   不该连行为断言一起跳。两者仍在同一条轨(同一次 `flutter test` 调用)。
//
// 三条硬约束(踩过的坑,别动):
//
// 1. **基准图只能在 CI 里生成、在 CI 里比对。**
//    本机模拟器是 API 37 / `sdk_gphone16k_x86_64`,CI 是 API 34 / AOSP default 镜像,
//    系统字体与渲染都不同 —— 本机 `--update-goldens` 的产物**不能**提交。
//    正确做法:`.github/workflows/app-ui.yml` 用 `workflow_dispatch` 打开 `update_goldens`,
//    由 CI 生成 → 下载 artifact → 提交那两张 PNG。日常推送只做**比对**。
//
// 2. **固定视口**:捕获的是 390×844 逻辑像素 + 零 padding + textScaler=1 的那一块。
//    `captureImage` 走 `layer.toImage(bounds)`(pixelRatio=1.0),所以 PNG 尺寸 = **逻辑**
//    尺寸,与设备 DPR / 分辨率无关;但**逻辑屏幕尺寸**会随 AVD 变,所以必须自己钉住,
//    否则换个 AVD 就整张图对不上。用 `OverflowBox` 而不是 `Align`:`home` 拿到的是紧约束
//    (整屏),`Align` 只把「0..屏幕宽」的松约束传下去 —— 屏幕比 390 窄时(CI 的 AVD 就是
//    320x640 逻辑像素)`SizedBox` 会被压小,基准图尺寸跟着设备变;`OverflowBox` 给子级
//    无界约束,390x844 才是真的 390x844。
//
// 3. **不碰网络**:假网络(ScriptedAdapter)只喂 JSON;候选照片一律不铺(`photos: []`),
//    卡片走 `profile_card.dart` 的纯色占位。真图是 `Image.network`,截帧时「图下没下来」
//    会让结果随机 —— golden 里不允许出现这种竞态。
//
// 生成/更新基准图(只在 CI):
//   gh workflow run app-ui.yml --ref <branch> -f update_goldens=true
// 本机自查(产物**不要提交**,只用来肉眼确认截到的是真页面):
//   flutter test integration_test/golden_test.dart -d emulator-5554 --update-goldens

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/app_config.dart';
import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/core/theme/app_theme.dart';
import 'package:chatapp_app/core/token_storage.dart';
import 'package:chatapp_app/core/token_store.dart';
import 'package:chatapp_app/features/auth/login_page.dart';
import 'package:chatapp_app/features/auth/session.dart';
import 'package:chatapp_app/features/legal/legal_texts.dart';
import 'package:chatapp_app/features/notifications/notifications_controller.dart';
import 'package:chatapp_app/features/presence/presence_controller.dart';
import 'package:chatapp_app/features/shell/home_shell.dart';
import 'package:chatapp_app/im/im_manager.dart';

import '../test/support/fake_im_client.dart';
import '../test/support/sample_data.dart';
import '../test/support/scripted_adapter.dart';

/// 登录页与首页的 golden 边界 key;`matchesGoldenFile` 截的就是这两块。
const _loginBoundary = Key('golden.login');
const _discoveryBoundary = Key('golden.discovery');

/// 与 `test/support/harness.dart` 的 `pumpApp` 同口径:prefs 里塞令牌 = 已登录。
const _loggedIn = {'auth.access': 'a', 'auth.refresh': 'r', 'auth.user_id': 7};

/// 固定视口(逻辑像素)。改这个值 = 换基准图,必须重新在 CI 生成。
const _viewport = Size(390, 844);

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('登录页 golden', (tester) async {
    // 登录页在冷启动链之外单独 pump:品牌区是静态的,不依赖 /app/config 与会话 bootstrap,
    // 这样这张图只受「登录页自己长什么样」影响。冷启动仍由 smoke_test.dart 覆盖。
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
    });
    await _pumpGolden(tester,
        boundary: _loginBoundary, adapter: adapter, child: const LoginPage());
    // 登录页无动画(login_page.dart 顶部注释),可以 settle。
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('login.submit')), findsOneWidget);
    expect(find.text('手机号登录 / 注册'), findsOneWidget);

    await expectLater(
        find.byKey(_loginBoundary), matchesGoldenFile('goldens/login.png'));
  });

  testWidgets('首页(发现)golden', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson(nickname: '小明')),
      // 两张卡:上面一张是主体,第二张让卡组有层次(与真机一致)
      'GET /discovery/candidates': (options) => ok([
            candidateJson(
              userId: 9,
              nickname: '小红',
              city: '上海',
              bio: '周末爬山,平时看书',
              tags: [tagJson(1, '旅行'), tagJson(2, '读书'), tagJson(3, '电影')],
              // 空照片 = 纯色占位,**零网络**(见文件头约束 3)
              photos: const [],
            ),
            candidateJson(userId: 10, nickname: '小刚', photos: const []),
          ]),
      'GET /discovery/daily': (options) => ok(dailyJson(candidates: const [])),
      // 隐藏 Tab 也会 build(IndexedStack),铺一条空流避免 404 噪声
      'GET /posts': (options) => ok(cursorPageJson(const [])),
    });

    await _pumpGolden(tester,
        boundary: _discoveryBoundary,
        adapter: adapter,
        prefs: _loggedIn,
        child: const HomeShell());
    // 隐藏 Tab 的空态涟漪是无限动画 → 不能 pumpAndSettle(见 home_shell_test.dart 注释)。
    await _pumpFrames(tester);

    // 截之前先确认数据已到:否则截到的是骨架屏,而骨架屏不该被当成「设计基线」。
    expect(find.text('小红,25'), findsOneWidget);

    await expectLater(find.byKey(_discoveryBoundary),
        matchesGoldenFile('goldens/discovery.png'));
  });
}

/// 把页面装进固定视口再 pump。
///
/// 与 `test/support/harness.dart::pumpPage` 的区别只有两点:① 固定视口(见文件头约束 2);
/// ② 关掉 debug 角标 —— golden 要的是设计基线,不是 debug 包上的 DEBUG 飘带。
/// provider 覆盖列表与 `pumpPage` 保持一致(那才是「真实 provider + 假网络」的唯一口径)。
Future<void> _pumpGolden(
  WidgetTester tester, {
  required Key boundary,
  required ScriptedAdapter adapter,
  required Widget child,
  Map<String, Object> prefs = const {},
}) async {
  SharedPreferences.setMockInitialValues(
      {'legal.agreed_version': legalVersion, ...prefs});
  final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))
    ..httpClientAdapter = adapter;
  final refreshDio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))
    ..httpClientAdapter = adapter;

  await tester.pumpWidget(ProviderScope(
    overrides: [
      baseDioProvider.overrideWithValue(dio),
      refreshDioProvider.overrideWithValue(refreshDio),
      tokenStoreProvider.overrideWithValue(
          TokenStore(storage: SharedPreferencesTokenStorage())),
      imClientProvider.overrideWithValue(FakeImClient()),
      appConfigCheckEnabledProvider.overrideWithValue(false),
      // 三个周期性任务默认关掉:它们的 Timer 会让画面随时间变,是 golden 的天敌
      heartbeatIntervalProvider.overrideWithValue(null),
      presenceRefreshIntervalProvider.overrideWithValue(null),
      notificationsBadgeRefreshIntervalProvider.overrideWithValue(null),
    ],
    child: OverflowBox(
      // 不能只用 Align:`home` 拿到的是**紧**约束(整屏),Align 传给子级的是
      // 「0..屏幕宽」的松约束 —— 屏幕比 390 窄时(CI 的 AVD 就是 320x640 逻辑像素)
      // SizedBox 会被压到屏幕尺寸,基准图尺寸就跟着设备变。OverflowBox 让子级拿到
      // 无界约束,SizedBox 才能稳定是 390x844。
      alignment: Alignment.topLeft,
      minWidth: 0,
      maxWidth: double.infinity,
      minHeight: 0,
      maxHeight: double.infinity,
      child: RepaintBoundary(
        key: boundary,
        child: SizedBox(
          width: _viewport.width,
          height: _viewport.height,
          // 系统字体缩放 / 状态栏高度都是设备相关的,这里全部钉死
          child: MediaQuery(
            data: const MediaQueryData(
              size: _viewport,
              devicePixelRatio: 2,
              textScaler: TextScaler.noScaling,
            ),
            child: MaterialApp(
              // 与 app.dart 的 MaterialApp.router 同一套主题与本地化,只少了路由与 debug 角标
              debugShowCheckedModeBanner: false,
              theme: buildAppTheme(brightness: Brightness.light),
              locale: const Locale('zh', 'CN'),
              supportedLocales: const [Locale('zh', 'CN')],
              localizationsDelegates: const [
                GlobalMaterialLocalizations.delegate,
                GlobalWidgetsLocalizations.delegate,
                GlobalCupertinoLocalizations.delegate,
              ],
              home: child,
            ),
          ),
        ),
      ),
    ),
  ));
  await tester.pump();
}

/// 定步长推进若干帧(不能用 `pumpAndSettle`:隐藏 Tab 里有无限动画)。
Future<void> _pumpFrames(WidgetTester tester,
    {int frames = 12, Duration step = const Duration(milliseconds: 100)}) async {
  for (var i = 0; i < frames; i++) {
    await tester.pump(step);
  }
}
