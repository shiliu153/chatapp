import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/theme/heart_colors.dart';
import 'package:chatapp_app/core/theme/theme_mode_store.dart';

import '../../support/harness.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

const _loggedIn = {'auth.access': 'a', 'auth.refresh': 'r', 'auth.user_id': 7};

/// 当前生效的 MaterialApp.themeMode(整个 App 只有一个 MaterialApp.router)。
ThemeMode currentThemeMode(WidgetTester tester) =>
    tester.widget<MaterialApp>(find.byType(MaterialApp)).themeMode!;

/// 走到「我的 → 设置」,并滚到「外观」卡片可见(它在设置页最后一张卡)。
Future<void> openSettings(WidgetTester tester) async {
  await tester.tap(navTab('我的'));
  await tester.pumpAndSettle();
  await tester.ensureVisible(find.byKey(const Key('my.row.settings')));
  await tester.pumpAndSettle();
  await tester.tap(find.byKey(const Key('my.row.settings')));
  await tester.pumpAndSettle();
  await tester.scrollUntilVisible(
    find.byKey(const Key('settings.row.theme')),
    200,
    scrollable: find.byType(Scrollable).first,
  );
  await tester.pumpAndSettle();
}

ScriptedAdapter _adapter() => ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
    });

void main() {
  group('ThemeModeStore', () {
    test('encode / decode:枚举名往返,非法值回落 system', () {
      expect(ThemeModeStore.encode(ThemeMode.dark), 'dark');
      expect(ThemeModeStore.decode('dark'), ThemeMode.dark);
      expect(ThemeModeStore.decode('light'), ThemeMode.light);
      expect(ThemeModeStore.decode('system'), ThemeMode.system);
      expect(ThemeModeStore.decode(null), ThemeMode.system);
      expect(ThemeModeStore.decode('purple'), ThemeMode.system);
    });

    test('write 后 read 能读回', () async {
      SharedPreferences.setMockInitialValues({});
      const store = ThemeModeStore();
      expect(await store.read(), ThemeMode.system);
      await store.write(ThemeMode.dark);
      expect(await store.read(), ThemeMode.dark);
      expect((await SharedPreferences.getInstance()).getString('theme_mode'), 'dark');
    });
  });

  testWidgets('启动读到 dark → MaterialApp.themeMode == ThemeMode.dark', (tester) async {
    await pumpApp(tester, _adapter(), prefs: {..._loggedIn, 'theme_mode': 'dark'});
    await tester.pumpAndSettle();

    expect(currentThemeMode(tester), ThemeMode.dark);
    // 主题本身也确实是暗色板(darkTheme 的页面底色 = 深色 bgPage)
    final app = tester.widget<MaterialApp>(find.byType(MaterialApp));
    expect(app.darkTheme?.scaffoldBackgroundColor, HeartColors.dark.bgPage);
  });

  testWidgets('没存过时默认跟随系统', (tester) async {
    await pumpApp(tester, _adapter(), prefs: _loggedIn);
    await tester.pumpAndSettle();
    expect(currentThemeMode(tester), ThemeMode.system);
  });

  testWidgets('设置页三态切换:即时生效 + 写进 prefs', (tester) async {
    await pumpApp(tester, _adapter(), prefs: _loggedIn);
    await tester.pumpAndSettle();
    await openSettings(tester);

    expect(find.byKey(const Key('settings.row.theme')), findsOneWidget);
    // 默认选中「跟随系统」
    expect(currentThemeMode(tester), ThemeMode.system);

    await tester.tap(find.text('深色'));
    await tester.pumpAndSettle();
    expect(currentThemeMode(tester), ThemeMode.dark);
    expect((await SharedPreferences.getInstance()).getString('theme_mode'), 'dark');

    await tester.tap(find.text('浅色'));
    await tester.pumpAndSettle();
    expect(currentThemeMode(tester), ThemeMode.light);
    expect((await SharedPreferences.getInstance()).getString('theme_mode'), 'light');

    await tester.tap(find.text('跟随系统'));
    await tester.pumpAndSettle();
    expect(currentThemeMode(tester), ThemeMode.system);
  });

  testWidgets('杀进程重启后保留:按上次写下的 prefs 重建 App 仍是深色', (tester) async {
    await pumpApp(tester, _adapter(), prefs: _loggedIn);
    await tester.pumpAndSettle();
    await openSettings(tester);
    await tester.tap(find.text('深色'));
    await tester.pumpAndSettle();

    final saved = (await SharedPreferences.getInstance()).getString('theme_mode');
    expect(saved, 'dark');

    // 「重启」:新的 widget 树 + 新的 ProviderScope,prefs 只带上次写下的值
    await pumpApp(tester, _adapter(), prefs: {..._loggedIn, 'theme_mode': saved!});
    await tester.pumpAndSettle();
    expect(currentThemeMode(tester), ThemeMode.dark);
  });
}
