import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/theme/ember_colors.dart';
import 'package:chatapp_app/core/theme/tokens.g.dart' as tokens;
import 'package:chatapp_app/core/ui/ember_toast.dart';

import 'ember_test_kit.dart';

BoxDecoration _decoration(WidgetTester tester) => tester
    .widget<Container>(
      find.descendant(
        of: find.byType(ToastPill),
        matching: find.byType(Container),
      ),
    )
    .decoration! as BoxDecoration;

double _opacity(WidgetTester tester) => tester
    .widget<Opacity>(
      find.descendant(
        of: find.byType(ToastPill),
        matching: find.byType(Opacity),
      ),
    )
    .opacity;

/// 触发按钮:只为在测试里拿到带 Overlay 的 context。
class _Trigger extends StatelessWidget {
  const _Trigger({required this.label, required this.onTap});

  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => GestureDetector(
        onTap: onTap,
        child: SizedBox(
          width: 48,
          height: 48,
          child: Center(child: Text(label)),
        ),
      );
}

void main() {
  // Toast 会挂一个 2s 的自动消失 Timer:用例结束前必须 `EmberToast.hide()`,
  // 否则 flutter_test 会以「A Timer is still pending」判红
  // (那个不变式在 tearDown 之前检查,所以不能靠 tearDown)。

  group('ToastPill · default(§8.3 Toast 表)', () {
    testWidgets('overlay.scrim 底 + 白字 13 + radius.md', (tester) async {
      await pumpEmber(tester, const ToastPill(message: '已保存'));
      final decoration = _decoration(tester);
      expect(decoration.color, EmberColors.light.overlayScrim);
      expect(
        decoration.borderRadius,
        BorderRadius.circular(tokens.radiusMd),
      );
      final text = tester.widget<Text>(find.text('已保存'));
      expect(text.style!.fontSize, tokens.fontSizeCaption);
      expect(text.style!.color, Colors.white);
    });

    testWidgets('深色下底色换成深色 scrim(不是固定深灰)', (tester) async {
      await pumpEmber(
        tester,
        const ToastPill(message: '已保存'),
        brightness: Brightness.dark,
      );
      expect(_decoration(tester).color, EmberColors.dark.overlayScrim);
    });

    testWidgets('淡入:第一帧未完全可见,随后到 1', (tester) async {
      await tester.pumpWidget(emberStage(const ToastPill(message: '已保存')));
      expect(_opacity(tester), lessThan(1));
      await tester.pump(const Duration(milliseconds: 300));
      expect(_opacity(tester), 1);
    });

    testWidgets('减弱动态效果时不位移(§8.4)', (tester) async {
      await pumpEmber(
        tester,
        const ToastPill(message: '已保存'),
        disableAnimations: true,
      );
      await tester.pump(const Duration(milliseconds: 120));
      final transform = tester.widget<Transform>(
        find.descendant(
          of: find.byType(ToastPill),
          matching: find.byType(Transform),
        ),
      );
      expect(transform.transform.getTranslation().y, 0);
    });

    testWidgets('读屏播报为 live region(§8.4)', (tester) async {
      await pumpEmber(tester, const ToastPill(message: '已保存'));
      await pumpFrames(tester, frames: 4);
      final nodes = tester.widgetList<Semantics>(
        find.descendant(of: find.byType(ToastPill), matching: find.byType(Semantics)),
      );
      expect(
        nodes.any((s) =>
            s.properties.liveRegion == true &&
            (s.properties.label ?? '').contains('已保存')),
        isTrue,
        reason: 'Toast 必须作为 live region 播报,否则读屏用户完全收不到这条反馈',
      );
    });
  });

  group('ToastPill · error(§8.1 Toast 的第二个状态)', () {
    testWidgets('错误文案同样是一条 scrim 浮层,靠文案而不是底色区分', (tester) async {
      await pumpEmber(tester, const ToastPill(message: '发送失败,请重试'));
      expect(_decoration(tester).color, EmberColors.light.overlayScrim);
      expect(find.text('发送失败,请重试'), findsOneWidget);
    });
  });

  group('EmberToast.show · 定位与不可堆叠(§8.3)', () {
    testWidgets('贴在底栏上方 12(悬浮胶囊 64 + 底距 10 + 12)', (tester) async {
      await pumpEmber(
        tester,
        _Trigger(
          label: 'A',
          onTap: () => EmberToast.show(
            tester.element(find.byType(_Trigger)),
            '已保存',
          ),
        ),
      );
      await tester.tap(find.text('A'));
      await tester.pump();
      expect(find.text('已保存'), findsOneWidget);

      final positioned = tester.widget<Positioned>(
        find.ancestor(
          of: find.byType(ToastPill),
          matching: find.byType(Positioned),
        ).first,
      );
      // 64(底栏) + 10(底距) + 12(规范值)
      expect(positioned.bottom, 64 + 10 + 12);

      EmberToast.hide();
      await tester.pump();
    });

    testWidgets('连续两条只保留最新一条', (tester) async {
      await pumpEmber(
        tester,
        Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            _Trigger(
              label: 'A',
              onTap: () => EmberToast.show(
                tester.element(find.byType(_Trigger).first),
                '第一条',
              ),
            ),
            _Trigger(
              label: 'B',
              onTap: () => EmberToast.show(
                tester.element(find.byType(_Trigger).first),
                '第二条',
              ),
            ),
          ],
        ),
      );

      await tester.tap(find.text('A'));
      await tester.pump();
      expect(find.text('第一条'), findsOneWidget);

      await tester.tap(find.text('B'));
      await tester.pump();
      expect(find.text('第二条'), findsOneWidget);
      expect(find.text('第一条'), findsNothing, reason: '新的必须顶替旧的');

      EmberToast.hide();
      await tester.pump();
    });

    testWidgets('2s 后自动消失', (tester) async {
      await pumpEmber(
        tester,
        _Trigger(
          label: 'A',
          onTap: () => EmberToast.show(
            tester.element(find.byType(_Trigger)),
            '一会儿就没了',
          ),
        ),
      );
      await tester.tap(find.text('A'));
      await tester.pump();
      expect(find.text('一会儿就没了'), findsOneWidget);
      await tester.pump(const Duration(milliseconds: 2100));
      await tester.pump();
      expect(find.text('一会儿就没了'), findsNothing);
    });
  });
}
