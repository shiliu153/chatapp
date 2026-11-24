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

/// 设置线的读屏口径(E-5.6b page spec §6 第 3 条):
///
/// 1. 二级页返回键读「返回」;
/// 2. **开关行读「标题,已开启 / 已关闭」**(不是「开关,关」这种没有主语的念法);
/// 3. 危险 Dialog 的按钮读**明确动词**(「继续注销」「确认注销」),不是「确定」。
///
/// 这三条由 `EmberPageScaffold` / `EmberSettingsTile` / `EmberDialog` 三个公共组件
/// 保证;本文件从**页面**这一层断言,防的是「组件对、页面却把标签覆盖掉了」。
///
/// 断言走 `find.semantics.byLabel`(Flutter 3.47 的语义树查找器):它直接查语义节点,
/// 不受 `ExcludeSemantics` 之外的可视结构影响 —— 正是「读屏会念什么」这件事。
void main() {
  /// 真 provider + 假网络(设置页的开关行要读 `profileProvider`)。
  Future<void> pumpPage(
    WidgetTester tester,
    Widget page, {
    required ScriptedAdapter adapter,
  }) async {
    SharedPreferences.setMockInitialValues({});
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
        theme: buildAppTheme(brightness: Brightness.light),
        home: page,
      ),
    ));
    await tester.pumpAndSettle();
  }

  /// 把设置页滚到某一行可见(ListView 懒加载,没滚到的行根本没被 build)。
  Future<void> scrollSettingsTo(WidgetTester tester, Key key) async {
    await tester.scrollUntilVisible(
      find.byKey(key),
      120,
      scrollable: find.descendant(
        of: find.byKey(const Key('settings.list')),
        matching: find.byType(Scrollable),
      ),
    );
    await tester.pumpAndSettle();
  }

  /// 断言某个「按钮动词」确实出现在语义树里。
  ///
  /// 为什么不是精确字符串:`EmberButton` 的读屏标签目前是「动词 + 换行 + 同一动词」——
  /// `EmberPressable` 包了 `Semantics(label:)` 却没有 `excludeSemantics: true`,
  /// 于是按钮里的 `Text` 又把同一句话合并进来,读屏会念两遍。这是公共组件
  /// (E-5.6a)的既有缺陷,不属于本单范围,已写进 PR「遗留」;这里的正则按「整段就是
  /// 该动词(重复一次也算)」匹配,既证明念到的是动作本身,又不被这条缺陷挡住。
  SemanticsFinder verbNode(String verb) {
    final escaped = RegExp.escape(verb);
    return find.semantics.byLabel(RegExp('^$escaped(\\n$escaped)?\$'));
  }

  testWidgets('通知设置:两行开关都读「标题,已关闭」', (tester) async {
    final handle = tester.ensureSemantics();
    await pumpPage(
      tester,
      const NotificationSettingsPage(),
      adapter: ScriptedAdapter({}),
    );

    expect(find.semantics.byLabel('新配对提醒,已关闭'), findsOne);
    expect(find.semantics.byLabel('新消息提醒,已关闭'), findsOne);
    // 返回键的标签是规范硬要求(§8.4「图标按钮必须有 Semantics(label:)」)
    expect(verbNode('返回'), findsOne);
    handle.dispose();
  });

  testWidgets('设置页:隐身浏览开关行读「隐身浏览,已关闭」,切换后变「已开启」', (tester) async {
    final handle = tester.ensureSemantics();
    final adapter = ScriptedAdapter({
      'GET /users/me': (options) => ok(profileJson()),
      'PATCH /users/me': (options) => ok(profileJson(visitsHidden: true)),
    });
    await pumpPage(tester, const SettingsPage(), adapter: adapter);

    expect(find.semantics.byLabel('隐身浏览,已关闭'), findsOne);
    expect(verbNode('返回'), findsOne);

    await tester.tap(find.byKey(const Key('settings.row.visitsHidden')));
    await tester.pumpAndSettle();

    expect(find.semantics.byLabel('隐身浏览,已开启'), findsOne);
    expect(find.semantics.byLabel('隐身浏览,已关闭'), findsNothing);
    handle.dispose();
  });

  testWidgets('注销账号:两个 Dialog 的确认键都读明确动词', (tester) async {
    final handle = tester.ensureSemantics();
    final adapter = ScriptedAdapter({
      'GET /users/me': (options) => ok(profileJson()),
    });
    await pumpPage(tester, const SettingsPage(), adapter: adapter);

    await scrollSettingsTo(tester, const Key('settings.row.deleteAccount'));
    await tester.tap(find.byKey(const Key('settings.row.deleteAccount')));
    await tester.pumpAndSettle();

    // 第一步:后果说明,动词是「继续注销」而不是「继续 / 确定」
    expect(verbNode('继续注销'), findsOne);
    expect(verbNode('确定'), findsNothing);

    await tester.tap(find.text('继续注销'));
    await tester.pumpAndSettle();

    // 第二步:输入手机号,动词是「确认注销」
    expect(verbNode('确认注销'), findsOne);
    expect(verbNode('取消'), findsOne);
    handle.dispose();
  });

  testWidgets('退出登录 Dialog 的确认键读「退出」', (tester) async {
    final handle = tester.ensureSemantics();
    final adapter = ScriptedAdapter({
      'GET /users/me': (options) => ok(profileJson()),
    });
    await pumpPage(tester, const SettingsPage(), adapter: adapter);

    await scrollSettingsTo(tester, const Key('settings.logout'));
    await tester.tap(find.byKey(const Key('settings.logout')));
    await tester.pumpAndSettle();

    expect(verbNode('退出'), findsOne);
    handle.dispose();
  });
}
