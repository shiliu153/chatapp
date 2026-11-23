import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/theme/app_theme.dart';
import 'package:chatapp_app/features/shell/ember_nav_bar.dart';

/// 底栏 golden:明 / 暗 × 四种内容 = 8 张(E-5.1 page spec §6 第 2 条)。
///
/// 四种内容的口径(page spec §4 的状态清单压成能出现在**同一张图**里的四组):
/// 1. `default` —— 第 1 项选中,其余三项未选中:一张图同时给出「选中 / 未选中」取值;
/// 2. `selected` —— 选中项挪到第 3 格:验证胶囊位移后的位置(不是只有第一格好看);
/// 3. `badge` —— 「对话」tab 3 条未读;
/// 4. `badge99` —— 未读 120,角标显示「99+」。
///
/// 为什么是**组件级 golden**(而不是模拟器 golden):这里比的是底栏自己的取值
/// (§8.3 状态取值表),不需要设备字体与真实渲染;`flutter test` 在本机与 CI 上
/// 跑的是同一个 `flutter_tester` 引擎,基准图可随代码一起提交。
///
/// 重新生成:`cd app && flutter test --update-goldens test/features/shell/ember_nav_bar_golden_test.dart`
/// (只在**确认视觉改动就是想要的**之后跑,并人工看一眼 diff 图。)
void main() {
  /// 固定视口(390 宽 = 常见手机逻辑宽度),渲染底栏并截它自己。
  ///
  /// 减弱动态效果固定开着:胶囊与图标都直接取终态,截图不会撞上弹簧动画的中间帧。
  Future<void> pumpBar(
    WidgetTester tester, {
    required Brightness brightness,
    required int currentIndex,
    int unreadCount = 0,
  }) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);

    await tester.pumpWidget(
      MaterialApp(
        theme: buildAppTheme(brightness: brightness),
        themeAnimationDuration: Duration.zero,
        home: MediaQuery(
          data: const MediaQueryData(disableAnimations: true, size: Size(390, 844)),
          child: Scaffold(
            bottomNavigationBar: EmberNavBar(
              currentIndex: currentIndex,
              onTap: (_) {},
              unreadCount: unreadCount,
            ),
          ),
        ),
      ),
    );
    await tester.pump();
  }

  for (final brightness in Brightness.values) {
    final mode = brightness == Brightness.light ? 'light' : 'dark';

    testWidgets('底栏 golden · $mode · 未选中/选中', (tester) async {
      await pumpBar(tester, brightness: brightness, currentIndex: 0);
      await expectLater(
        find.byType(EmberNavBar),
        matchesGoldenFile('goldens/ember_nav_bar_${mode}_default.png'),
      );
    });

    testWidgets('底栏 golden · $mode · 选中挪到第 3 格', (tester) async {
      await pumpBar(tester, brightness: brightness, currentIndex: 2);
      await expectLater(
        find.byType(EmberNavBar),
        matchesGoldenFile('goldens/ember_nav_bar_${mode}_selected.png'),
      );
    });

    testWidgets('底栏 golden · $mode · 有角标(3)', (tester) async {
      await pumpBar(tester, brightness: brightness, currentIndex: 0, unreadCount: 3);
      await expectLater(
        find.byType(EmberNavBar),
        matchesGoldenFile('goldens/ember_nav_bar_${mode}_badge.png'),
      );
    });

    testWidgets('底栏 golden · $mode · 角标 99+', (tester) async {
      await pumpBar(tester, brightness: brightness, currentIndex: 2, unreadCount: 120);
      await expectLater(
        find.byType(EmberNavBar),
        matchesGoldenFile('goldens/ember_nav_bar_${mode}_badge99.png'),
      );
    });
  }
}
