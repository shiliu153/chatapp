import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/core/theme/app_theme.dart';
import 'package:chatapp_app/features/settings/notification_settings_page.dart';
import 'package:chatapp_app/features/settings/settings_page.dart';

import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

/// 设置线 golden(E-5.6b page spec §6 第 2 条 + §7 拍板:b 组 **4 张**)。
///
/// | 页 | 张数 | 覆盖 |
/// |---|---|---|
/// | 设置主页 | 2 | 明 / 暗:§9.4 顶栏 + 四张分组卡(开关行 / 入口行 / 危险按钮 / 外观) |
/// | 通知设置 | 2 | 明 / 暗:两行只读开关行 + 说明 |
///
/// 为什么是**整页 golden**(而不是模拟器截图):这里比的是取值 —— 顶栏 52 / 标题
/// 17-w600 居中、行高 68–76、标题 17/w600 + 副标题 13 `text.secondary`、开关选中
/// `brand.default`、危险按钮的 `status.danger` 描边(实底只在二次确认后)、
/// 卡片 `radius.lg` 与明暗两套层级(深色换 `border.divider` 描边、无阴影)。
/// 设备字体、真机手势与键盘属于**模拟器手测**(PR 正文「等待模拟器验收」那一段)。
///
/// 设置主页用 **390×1000** 视口:整页四张卡加间距约 940 高,844 会把「外观」卡切掉
/// —— golden 要看的是整页层级,不是折叠线。
///
/// 重新生成:`cd app && flutter test --update-goldens test/features/settings/settings_golden_test.dart`
/// (只在**确认视觉改动就是想要的**之后跑,并人工看一眼 diff 图。)
void main() {
  /// 固定视口 + 关掉动效 + 真 provider + 假网络(页面自己会读 `profileProvider`)。
  Future<void> pumpPage(
    WidgetTester tester,
    Widget page, {
    required Brightness brightness,
    Size size = const Size(390, 1000),
  }) async {
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    // apiClientProvider 会挂 AuthInterceptor,它读凭证要走 SharedPreferences
    SharedPreferences.setMockInitialValues({});
    final adapter = ScriptedAdapter({
      'GET /users/me': (options) => ok(profileJson()),
    });
    final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))
      ..httpClientAdapter = adapter;
    final container = ProviderContainer(overrides: [
      baseDioProvider.overrideWithValue(dio),
      refreshDioProvider.overrideWithValue(dio),
    ]);
    addTearDown(container.dispose);
    await tester.pumpWidget(UncontrolledProviderScope(
      container: container,
      child: MaterialApp(
        theme: buildAppTheme(brightness: brightness),
        themeAnimationDuration: Duration.zero,
        home: page,
      ),
    ));
    // 资料请求落定(开关行的取值来自 `profileProvider`)
    await tester.pumpAndSettle();
  }

  for (final brightness in Brightness.values) {
    final mode = brightness == Brightness.light ? 'light' : 'dark';

    testWidgets('设置主页 golden · $mode', (tester) async {
      await pumpPage(
        tester,
        const SettingsPage(key: Key('golden.settings')),
        brightness: brightness,
      );
      await expectLater(
        find.byKey(const Key('golden.settings')),
        matchesGoldenFile('goldens/settings_page_$mode.png'),
      );
    });

    testWidgets('通知设置 golden · $mode', (tester) async {
      await pumpPage(
        tester,
        const NotificationSettingsPage(key: Key('golden.notifications')),
        brightness: brightness,
        size: const Size(390, 420),
      );
      await expectLater(
        find.byKey(const Key('golden.notifications')),
        matchesGoldenFile('goldens/notification_settings_$mode.png'),
      );
    });
  }
}
