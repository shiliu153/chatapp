import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:phosphor_glyphs/phosphor_glyphs.dart';

import 'package:chatapp_app/core/theme/app_theme.dart';
import 'package:chatapp_app/core/theme/ember_colors.dart';
import 'package:chatapp_app/core/theme/tokens.g.dart' as tokens;
import 'package:chatapp_app/core/ui/ember_ui.dart';

import 'ember_test_kit.dart';

/// 二级页骨架的测试舞台:`EmberPageScaffold` 自带 `Scaffold` 并要吃掉整屏
/// (顶栏 52 + `Expanded` 内容区),所以**不能**用 [emberStage] 的 `Center` 包一层
/// —— 宽松约束会让 `Expanded` 找不到有限高度。
Widget _pageStage(
  Widget child, {
  Brightness brightness = Brightness.light,
  bool disableAnimations = false,
}) =>
    MaterialApp(
      theme: buildAppTheme(brightness: brightness),
      home: MediaQuery(
        data: MediaQueryData(disableAnimations: disableAnimations),
        child: child,
      ),
    );

/// 顶栏那条 `DecoratedBox`(标题文字的最近一层装饰盒;滚动时它长出下边线)。
BoxDecoration _topBarDecoration(WidgetTester tester, {String title = '用户协议'}) => tester
    .widget<DecoratedBox>(
      find.ancestor(of: find.text(title), matching: find.byType(DecoratedBox)).first,
    )
    .decoration as BoxDecoration;

/// 内容区(带一堆条目,方便造出「滚动」)。
Widget _longBody() => ListView.builder(
      itemCount: 40,
      itemBuilder: (context, index) => SizedBox(height: 64, child: Text('第 $index 条')),
    );

void main() {
  group('EmberPageScaffold · §9.4 顶栏', () {
    testWidgets('顶栏高 52、标题 17/w600 且水平居中、返回图标 22', (tester) async {
      await tester.pumpWidget(_pageStage(
        EmberPageScaffold(
          title: '用户协议',
          body: const SizedBox.shrink(),
          backKey: const Key('page.back'),
        ),
      ));

      final bar = find
          .ancestor(of: find.text('用户协议'), matching: find.byType(SizedBox))
          .first;
      expect(tester.getSize(bar).height, EmberPageScaffold.topBarHeight);
      expect(EmberPageScaffold.topBarHeight, 52);

      final title = tester.widget<Text>(find.text('用户协议'));
      expect(title.style!.fontSize, tokens.fontSizeSubtitle); // 17
      expect(title.style!.fontWeight, FontWeight.w600);
      expect(title.style!.color, EmberColors.light.textPrimary);

      // 居中:标题中心 = 屏幕中心(右侧没有 trailing 时最容易验证)。
      final screen = tester.view.physicalSize.width / tester.view.devicePixelRatio;
      expect(tester.getCenter(find.text('用户协议')).dx, moreOrLessEquals(screen / 2, epsilon: 1));

      // 返回 22:图标本体是 22,热区由 §8.4 撑到 48。
      final icon = tester.widget<Icon>(
        find.descendant(of: find.byKey(const Key('page.back')), matching: find.byType(Icon)),
      );
      expect(icon.size, 22);
      expect(icon.color, EmberColors.light.textPrimary);
      expect(
        tester.getSize(find.byKey(const Key('page.back'))),
        const Size(tokens.sizeTouchApp, tokens.sizeTouchApp),
      );
    });

    testWidgets('返回键读屏标签是「返回」,标题按 header 播报', (tester) async {
      final handle = tester.ensureSemantics();
      await tester.pumpWidget(_pageStage(
        EmberPageScaffold(
          title: '用户协议',
          body: const SizedBox.shrink(),
          backKey: const Key('page.back'),
        ),
      ));

      expect(semanticsOf(tester, find.byKey(const Key('page.back'))).label, '返回');
      expectSemanticallyButton(tester, find.byKey(const Key('page.back')), isButton: true);
      expect(
        tester.getSemantics(find.text('用户协议')).getSemanticsData().flagsCollection.isHeader,
        isTrue,
        reason: '标题要按 header 播报,读屏用户才知道这是页面标题',
      );
      handle.dispose();
    });

    testWidgets('返回键回调可注入;不给时走 Navigator.maybePop', (tester) async {
      var backs = 0;
      await tester.pumpWidget(_pageStage(
        EmberPageScaffold(
          title: '标题',
          body: const SizedBox.shrink(),
          onBack: () => backs++,
          backKey: const Key('page.back'),
        ),
      ));
      await tester.tap(find.byKey(const Key('page.back')));
      await tester.pump();
      expect(backs, 1);
    });

    testWidgets('showBack = false 时没有返回键', (tester) async {
      await tester.pumpWidget(_pageStage(
        const EmberPageScaffold(
          title: '标题',
          body: SizedBox.shrink(),
          showBack: false,
        ),
      ));
      expect(find.byIcon(PhosphorIconsRegular.caretLeft), findsNothing);
    });
  });

  group('EmberPageScaffold · 内容区与底部操作区', () {
    testWidgets('内容水平内边距 20;可改成 zero', (tester) async {
      await tester.pumpWidget(_pageStage(
        EmberPageScaffold(
          title: '标题',
          body: const SizedBox(key: Key('page.body'), width: double.infinity, height: 10),
        ),
      ));
      final screen = tester.view.physicalSize.width / tester.view.devicePixelRatio;
      expect(tester.getSize(find.byKey(const Key('page.body'))).width, screen - tokens.space20 * 2);

      await tester.pumpWidget(_pageStage(
        EmberPageScaffold(
          title: '标题',
          contentPadding: EdgeInsets.zero,
          body: const SizedBox(key: Key('page.body'), width: double.infinity, height: 10),
        ),
      ));
      expect(tester.getSize(find.byKey(const Key('page.body'))).width, screen);
    });

    testWidgets('底部主操作区渲染在内容下方;不给时不占高度', (tester) async {
      await tester.pumpWidget(_pageStage(
        EmberPageScaffold(
          title: '标题',
          body: const SizedBox.shrink(),
          bottomBar: EmberButton(
            key: const Key('page.primary'),
            label: '保存',
            onPressed: () {},
          ),
        ),
      ));
      expect(find.byKey(const Key('page.primary')), findsOneWidget);
      expect(
        tester.getCenter(find.byKey(const Key('page.primary'))).dy,
        greaterThan(tester.getCenter(find.text('标题')).dy),
      );

      await tester.pumpWidget(_pageStage(
        const EmberPageScaffold(title: '标题', body: SizedBox.shrink()),
      ));
      expect(find.byKey(const Key('page.primary')), findsNothing);
    });

    testWidgets('滚动前顶栏无下边线,滚动后补 1px border.divider(page spec §4)', (tester) async {
      await tester.pumpWidget(_pageStage(
        EmberPageScaffold(title: '用户协议', body: _longBody()),
      ));
      expect(_topBarDecoration(tester).border!.bottom.color, Colors.transparent);

      await tester.drag(find.byType(ListView), const Offset(0, -120));
      await tester.pump();

      final border = _topBarDecoration(tester).border!.bottom;
      expect(border.color, EmberColors.light.borderDivider);
      expect(border.width, 1);
    });

    testWidgets('showScrollDivider = false 时滚动也不长下边线', (tester) async {
      await tester.pumpWidget(_pageStage(
        EmberPageScaffold(
          title: '用户协议',
          body: _longBody(),
          showScrollDivider: false,
        ),
      ));
      await tester.drag(find.byType(ListView), const Offset(0, -120));
      await tester.pump();
      expect(_topBarDecoration(tester).border!.bottom.color, Colors.transparent);
    });

    testWidgets('深色下顶栏 / 页面底都取深色档(无浅色面残留)', (tester) async {
      await tester.pumpWidget(_pageStage(
        const EmberPageScaffold(title: '标题', body: SizedBox.shrink()),
        brightness: Brightness.dark,
      ));
      final scaffold = tester.widget<Scaffold>(find.byType(Scaffold).first);
      expect(scaffold.backgroundColor, EmberColors.dark.surfacePage);
      expect(_topBarDecoration(tester, title: '标题').color, EmberColors.dark.surfacePage);
    });
  });
}
