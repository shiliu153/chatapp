import 'dart:ui' show Tristate;

import 'package:flutter/material.dart';
import 'package:flutter/semantics.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:phosphor_glyphs/phosphor_glyphs.dart';

import 'package:chatapp_app/core/theme/app_theme.dart';
import 'package:chatapp_app/core/theme/ember_colors.dart';
import 'package:chatapp_app/core/theme/tokens.g.dart' as tokens;
import 'package:chatapp_app/core/ui/ember_badge.dart';
import 'package:chatapp_app/core/ui/ember_component_sizes.dart';
import 'package:chatapp_app/features/shell/ember_nav_bar.dart';

/// 底栏单测:取值逐格对照「余烬 Ember」§8.2 / §8.3 底栏行 + E-5.1 page spec §4。
/// 主题必须是真的(`buildAppTheme`):组件取色走 `context.ember`(ThemeExtension)。
Widget wrap(
  Widget bar, {
  Brightness brightness = Brightness.light,
  bool disableAnimations = false,
  double textScale = 1,
}) =>
    MaterialApp(
      theme: buildAppTheme(brightness: brightness),
      // 明暗切换默认走 200ms 插值,断言会读到「中间色」;测试里直接换掉。
      themeAnimationDuration: Duration.zero,
      home: MediaQuery(
        data: MediaQueryData(
          disableAnimations: disableAnimations,
          textScaler: TextScaler.linear(textScale),
        ),
        child: Scaffold(bottomNavigationBar: bar),
      ),
    );

/// 底栏本体(带装饰的那个 Container,不含外边距)。
Container barContainer(WidgetTester tester) => tester.widget<Container>(
      find.descendant(of: find.byType(EmberNavBar), matching: find.byType(Container)).first,
    );

BoxDecoration barDecoration(WidgetTester tester) =>
    barContainer(tester).decoration! as BoxDecoration;

/// 选中胶囊的装饰(胶囊是 `Container`,由 `EmberNavBar.capsuleKey` 定位)。
BoxDecoration capsuleDecoration(WidgetTester tester) => tester
    .widget<Container>(find.byKey(EmberNavBar.capsuleKey))
    .decoration! as BoxDecoration;

/// 第 [index] 个 tab 里的图标。
Icon tabIcon(WidgetTester tester, int index) => tester.widget<Icon>(
      find
          .descendant(
            of: find.byKey(EmberNavBar.navTabKey(index)),
            matching: find.byType(Icon),
          )
          .first,
    );

/// 第 [index] 个 tab 的标签文字。
Text tabLabel(WidgetTester tester, int index) => tester.widget<Text>(
      find
          .descendant(
            of: find.byKey(EmberNavBar.navTabKey(index)),
            matching: find.byType(Text),
          )
          .first,
    );

/// 把弹簧动画推到位(`spring.fast` 在 300ms 内收敛)。
Future<void> settleSpring(WidgetTester tester) async {
  for (var i = 0; i < 20; i++) {
    await tester.pump(const Duration(milliseconds: 32));
  }
}

void main() {
  group('底栏 · 结构(§9.1 主轴 / page spec §3)', () {
    testWidgets('四个 Tab 是「遇见 / 回声 / 对话 / 我」,点击回调索引', (tester) async {
      final taps = <int>[];
      await tester.pumpWidget(wrap(EmberNavBar(currentIndex: 0, onTap: taps.add)));

      for (final label in ['遇见', '回声', '对话', '我']) {
        expect(find.text(label), findsOneWidget);
      }
      // 旧命名在本单里彻底消失(改名不是叠两层)
      for (final old in ['发现', '广场', '消息', '我的']) {
        expect(find.text(old), findsNothing);
      }

      await tester.tap(find.text('回声'));
      expect(taps, [1]);
      await tester.tap(find.byKey(EmberNavBar.navTabKey(3)));
      expect(taps, [1, 3]);
    });

    testWidgets('悬浮胶囊几何:高 64、左右外距 12、底距 10、圆角 radius.xl(§8.2)', (tester) async {
      await tester.pumpWidget(wrap(EmberNavBar(currentIndex: 0, onTap: (_) {})));

      final screen = tester.getRect(find.byType(Scaffold));
      final container = tester.getRect(
        find.descendant(of: find.byType(EmberNavBar), matching: find.byType(Container)).first,
      );
      expect(container.height, tokens.sizeNavHeight);
      expect(container.width, screen.width - tokens.space12 * 2);
      expect(container.left, tokens.space12);
      expect(container.bottom, screen.height - EmberComponentSizes.navBottomInset);
      expect(
        barDecoration(tester).borderRadius,
        BorderRadius.circular(tokens.radiusXl),
      );
    });

    testWidgets('浅色用 elev.2 浮层阴影;深色不用阴影,改 border.strong 1px(§5.3)', (tester) async {
      await tester.pumpWidget(wrap(EmberNavBar(currentIndex: 0, onTap: (_) {})));
      final light = barDecoration(tester);
      expect(light.color, EmberColors.light.surfaceCard);
      expect(light.boxShadow, isNotNull);
      expect(light.boxShadow, isNotEmpty);
      expect(light.border, isNull);

      await tester.pumpWidget(
        wrap(EmberNavBar(currentIndex: 0, onTap: (_) {}), brightness: Brightness.dark),
      );
      final dark = barDecoration(tester);
      expect(dark.color, EmberColors.dark.surfaceCard);
      expect(dark.boxShadow, isNull);
      expect(dark.border, Border.all(color: EmberColors.dark.borderStrong));
    });
  });

  group('底栏 · 选中态(§8.3 底栏 selected)', () {
    testWidgets('选中胶囊是 brand.default 实色、高 40、radius.pill,且不叠光晕', (tester) async {
      await tester.pumpWidget(wrap(EmberNavBar(currentIndex: 0, onTap: (_) {})));

      final decoration = capsuleDecoration(tester);
      expect(decoration.color, EmberColors.light.brandDefault);
      expect(decoration.gradient, isNull); // 旧渐变胶囊不再出现
      expect(decoration.borderRadius, BorderRadius.circular(tokens.radiusPill));
      expect(decoration.boxShadow, isNull); // 一屏最多一处高音,底栏不是

      final size = tester.getSize(find.byKey(EmberNavBar.capsuleKey));
      expect(size.height, EmberComponentSizes.navCapsuleHeight);
      expect(size.width, EmberComponentSizes.navCapsuleWidth);
    });

    testWidgets('胶囊随选中项位移:第 n 项居中于第 n 格', (tester) async {
      for (final index in [0, 2, 3]) {
        await tester.pumpWidget(wrap(EmberNavBar(currentIndex: index, onTap: (_) {})));
        await settleSpring(tester);

        final container = tester.getRect(
          find.descendant(of: find.byType(EmberNavBar), matching: find.byType(Container)).first,
        );
        final slot = container.width / 4;
        final capsule = tester.getRect(find.byKey(EmberNavBar.capsuleKey));
        expect(capsule.center.dx, closeTo(container.left + slot * (index + 0.5), 0.5));
        expect(capsule.center.dy, closeTo(container.center.dy, 0.5));
      }
    });

    testWidgets('选中项 = Fill 白图标 20 + 白字 11/w700;未选中 = Regular 24 + text.tertiary', (tester) async {
      await tester.pumpWidget(wrap(EmberNavBar(currentIndex: 2, onTap: (_) {})));

      final selectedIcon = tabIcon(tester, 2);
      expect(selectedIcon.icon, PhosphorIconsFill.chatCircle);
      expect(selectedIcon.size, tokens.sizeIcon20);
      expect(selectedIcon.color, EmberColors.light.brandOn);

      final selectedLabel = tabLabel(tester, 2);
      expect(selectedLabel.style!.color, EmberColors.light.brandOn);
      expect(selectedLabel.style!.fontSize, tokens.fontSizeMicro);
      expect(selectedLabel.style!.fontWeight, FontWeight.w700);
      // §8.4:micro 档固定不跟随系统字号
      expect(selectedLabel.textScaler, TextScaler.noScaling);

      final otherIcon = tabIcon(tester, 0);
      expect(otherIcon.icon, PhosphorIconsRegular.cards);
      expect(otherIcon.size, tokens.sizeIcon24);
      expect(otherIcon.color, EmberColors.light.textTertiary);
      expect(tabLabel(tester, 0).style!.color, EmberColors.light.textTertiary);
    });

    testWidgets('四个 tab 的图标都来自 phosphor_glyphs(Regular → Fill 成对)', (tester) async {
      await tester.pumpWidget(wrap(EmberNavBar(currentIndex: 0, onTap: (_) {})));
      const expected = [
        (PhosphorIconsRegular.cards, PhosphorIconsFill.cards),
        (PhosphorIconsRegular.broadcast, PhosphorIconsFill.broadcast),
        (PhosphorIconsRegular.chatCircle, PhosphorIconsFill.chatCircle),
        (PhosphorIconsRegular.user, PhosphorIconsFill.user),
      ];
      for (var i = 0; i < expected.length; i++) {
        final (regular, fill) = expected[i];
        expect(tabIcon(tester, i).icon, i == 0 ? fill : regular);
        // 图标字体族必须是 Phosphor,而不是 Material 的 MaterialIcons
        expect(tabIcon(tester, i).icon!.fontFamily, startsWith('Phosphor'));
      }
      // 该文件里不再有 Material `Icons.*`(page spec §6 第 5 条)
      for (var i = 0; i < 4; i++) {
        expect(tabIcon(tester, i).icon!.fontFamily, isNot('MaterialIcons'));
      }
    });

    testWidgets('按压反馈 = 卡片口径 scale .98,颜色不变(page spec §4 假定)', (tester) async {
      await tester.pumpWidget(wrap(EmberNavBar(currentIndex: 0, onTap: (_) {})));
      final item = find.byKey(EmberNavBar.navTabKey(1));

      final gesture = await tester.startGesture(tester.getCenter(item));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 32));
      final scale = tester
          .widget<Transform>(find.descendant(of: item, matching: find.byType(Transform)).first)
          .transform
          .storage[0];
      expect(scale, lessThan(1));

      await gesture.up();
      await tester.pump();
      expect(tabLabel(tester, 1).style!.color, EmberColors.light.textTertiary);
    });
  });

  group('底栏 · 未读角标(§8.3 角标行 / page spec §4)', () {
    testWidgets('0 不显示,3 显示数字,120 显示 99+', (tester) async {
      await tester.pumpWidget(
        wrap(EmberNavBar(currentIndex: 0, onTap: (_) {}, unreadCount: 0)),
      );
      expect(find.byType(EmberBadge), findsNothing);

      await tester.pumpWidget(
        wrap(EmberNavBar(currentIndex: 0, onTap: (_) {}, unreadCount: 3)),
      );
      expect(find.text('3'), findsOneWidget);

      await tester.pumpWidget(
        wrap(EmberNavBar(currentIndex: 0, onTap: (_) {}, unreadCount: 120)),
      );
      expect(find.text('99+'), findsOneWidget);
    });

    testWidgets('角标只挂在「对话」tab(索引 2)', (tester) async {
      await tester.pumpWidget(
        wrap(EmberNavBar(currentIndex: 0, onTap: (_) {}, unreadCount: 5)),
      );
      expect(
        find.descendant(
          of: find.byKey(EmberNavBar.navTabKey(EmberNavBar.unreadTabIndex)),
          matching: find.byType(EmberBadge),
        ),
        findsOneWidget,
      );
      for (final index in [0, 1, 3]) {
        expect(
          find.descendant(
            of: find.byKey(EmberNavBar.navTabKey(index)),
            matching: find.byType(EmberBadge),
          ),
          findsNothing,
        );
      }
    });
  });

  group('底栏 · 无障碍(§8.4 / page spec §6 第 3 条)', () {
    testWidgets('每个 tab 都说出「名字 + 是否选中 + 未读数」', (tester) async {
      final handle = tester.ensureSemantics();
      await tester.pumpWidget(
        wrap(EmberNavBar(currentIndex: 0, onTap: (_) {}, unreadCount: 3)),
      );

      SemanticsNode nodeOf(int index) =>
          tester.getSemantics(find.byKey(EmberNavBar.navTabKey(index)));

      expect(nodeOf(0).label, '遇见 tab，已选中');
      expect(nodeOf(0).getSemanticsData().flagsCollection.isSelected, Tristate.isTrue);
      expect(nodeOf(1).label, '回声 tab');
      expect(nodeOf(1).getSemanticsData().flagsCollection.isButton, isTrue);
      // 「对话」有未读:名字 + 未读数(不是只靠角标的颜色)
      expect(nodeOf(2).label, '对话 tab，3 条未读');
      expect(nodeOf(2).getSemanticsData().flagsCollection.isSelected, Tristate.isFalse);
      expect(nodeOf(3).label, '我 tab');

      handle.dispose();
    });

    testWidgets('读屏能点到 tab(Semantics 带 tap action)', (tester) async {
      final handle = tester.ensureSemantics();
      final taps = <int>[];
      await tester.pumpWidget(wrap(EmberNavBar(currentIndex: 0, onTap: taps.add)));

      final data = tester
          .getSemantics(find.byKey(EmberNavBar.navTabKey(2)))
          .getSemanticsData();
      expect(data.hasAction(SemanticsAction.tap), isTrue);
      handle.dispose();
    });
  });

  group('底栏 · 减弱动态效果(page spec §4 reduced motion)', () {
    testWidgets('胶囊不位移:切换后立刻在新格子,图标不缩放', (tester) async {
      await tester.pumpWidget(
        wrap(EmberNavBar(currentIndex: 0, onTap: (_) {}), disableAnimations: true),
      );
      final container = tester.getRect(
        find.descendant(of: find.byType(EmberNavBar), matching: find.byType(Container)).first,
      );

      await tester.pumpWidget(
        wrap(EmberNavBar(currentIndex: 3, onTap: (_) {}), disableAnimations: true),
      );
      // 只推一帧:弹簧若还在跑,胶囊此刻不可能已经落在第 4 格
      await tester.pump();

      final capsule = tester.getRect(find.byKey(EmberNavBar.capsuleKey));
      expect(
        capsule.center.dx,
        closeTo(container.left + (container.width / 4) * 3.5, 0.5),
      );

      // 图标不缩放:选中项的内层 Transform 停在 1.0
      final scale = tester
          .widget<Transform>(
            find
                .descendant(
                  of: find.byKey(EmberNavBar.navTabKey(3)),
                  matching: find.byType(Transform),
                )
                .last,
          )
          .transform
          .storage[0];
      expect(scale, 1.0);
    });
  });

  group('底栏 · 深色模式', () {
    testWidgets('选中胶囊仍是 brand.default(深色为 #FF9370)+ 深字 brand.on', (tester) async {
      await tester.pumpWidget(
        wrap(EmberNavBar(currentIndex: 0, onTap: (_) {}), brightness: Brightness.dark),
      );
      expect(capsuleDecoration(tester).color, EmberColors.dark.brandDefault);
      expect(tabIcon(tester, 0).color, EmberColors.dark.brandOn);
      expect(tabLabel(tester, 0).style!.color, EmberColors.dark.brandOn);
    });
  });

  group('底栏 · 字号缩放', () {
    testWidgets('系统字号 1.3 时标签仍然不缩放(避免撑破胶囊)', (tester) async {
      await tester.pumpWidget(
        wrap(EmberNavBar(currentIndex: 0, onTap: (_) {}), textScale: 1.3),
      );
      expect(tabLabel(tester, 0).textScaler, TextScaler.noScaling);
      expect(find.text('遇见'), findsOneWidget);
    });
  });
}
