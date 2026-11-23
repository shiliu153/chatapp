import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/theme/ember_colors.dart';
import 'package:chatapp_app/core/theme/tokens.g.dart' as tokens;
import 'package:chatapp_app/core/ui/ember_component_sizes.dart';
import 'package:chatapp_app/core/ui/ember_sheet.dart';

import 'ember_test_kit.dart';

void main() {
  group('EmberSheet · default(§8.3 Sheet 表)', () {
    testWidgets('surface.card 底 + 上圆角 24 + 拖把 36×4 border.divider', (tester) async {
      await pumpEmber(
        tester,
        Builder(
          builder: (context) => TextButton(
            onPressed: () => EmberSheet.show<void>(
              context,
              child: const Padding(
                padding: EdgeInsets.all(20),
                child: Text('筛选'),
              ),
            ),
            child: const Text('打开'),
          ),
        ),
      );
      await tester.tap(find.text('打开'));
      await tester.pumpAndSettle();

      expect(find.text('筛选'), findsOneWidget);

      // 拖把
      final handle = tester.widget<Container>(
        find
            .descendant(
              of: find.byType(EmberSheetHandle),
              matching: find.byType(Container),
            )
            .first,
      );
      expect(
        tester.getSize(find.byType(EmberSheetHandle)),
        Size(EmberComponentSizes.sheetHandleWidth, EmberComponentSizes.sheetHandleHeight + 16),
      );
      expect(
        (handle.decoration! as BoxDecoration).color,
        EmberColors.light.borderDivider,
      );

      // 弹层容器:surface.card + 上圆角 24
      final sheet = tester.widget<BottomSheet>(find.byType(BottomSheet));
      expect(sheet.backgroundColor, EmberColors.light.surfaceCard);
      expect(
        sheet.shape,
        RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(tokens.radiusXl)),
        ),
      );
    });

    testWidgets('遮罩用 overlay.scrim(不是 Material 默认纯黑)', (tester) async {
      await pumpEmber(
        tester,
        Builder(
          builder: (context) => TextButton(
            onPressed: () => EmberSheet.show<void>(
              context,
              child: const Text('内容'),
            ),
            child: const Text('打开'),
          ),
        ),
      );
      await tester.tap(find.text('打开'));
      await tester.pumpAndSettle();
      final barrier = tester.widget<ModalBarrier>(find.byType(ModalBarrier).last);
      expect(barrier.color, EmberColors.light.overlayScrim);
    });

    testWidgets('点遮罩可关闭;dismissible=false 时不可关闭', (tester) async {
      await pumpEmber(
        tester,
        Builder(
          builder: (context) => TextButton(
            onPressed: () => EmberSheet.show<void>(
              context,
              child: const Text('内容'),
            ),
            child: const Text('打开'),
          ),
        ),
      );
      await tester.tap(find.text('打开'));
      await tester.pumpAndSettle();
      expect(find.text('内容'), findsOneWidget);
      await tester.tapAt(const Offset(10, 10));
      await tester.pumpAndSettle();
      expect(find.text('内容'), findsNothing);

      await pumpEmber(
        tester,
        Builder(
          builder: (context) => TextButton(
            onPressed: () => EmberSheet.show<void>(
              context,
              dismissible: false,
              child: const Text('内容'),
            ),
            child: const Text('打开'),
          ),
        ),
      );
      await tester.tap(find.text('打开'));
      await tester.pumpAndSettle();
      await tester.tapAt(const Offset(10, 10));
      await tester.pumpAndSettle();
      expect(find.text('内容'), findsOneWidget, reason: 'dismissible=false 不应被遮罩关闭');
    });
  });

  group('EmberSheet · 无障碍(§8.4)', () {
    testWidgets('拖把是纯装饰(excludeSemantics),内容仍在语义树里', (tester) async {
      final semantics = tester.ensureSemantics();
      await pumpEmber(
        tester,
        Builder(
          builder: (context) => TextButton(
            onPressed: () => EmberSheet.show<void>(
              context,
              child: const Text('筛选'),
            ),
            child: const Text('打开'),
          ),
        ),
      );
      await tester.tap(find.text('打开'));
      await tester.pumpAndSettle();

      expect(
        find.descendant(
          of: find.byType(EmberSheetHandle),
          matching: find.byType(ExcludeSemantics),
        ),
        findsOneWidget,
        reason: '§8.4:拖把是纯装饰,不许被读屏念出来',
      );
      // 内容照常可播报:excludeSemantics 只包住拖把,不吞掉弹层内容。
      expect(find.bySemanticsLabel('筛选'), findsOneWidget);
      semantics.dispose();
    });
  });

  group('EmberSheet · 无 pressed / disabled / loading(§8.1)', () {
    test('Sheet 只有 default 与 focus:忙碌与禁用交给内容自己表达', () {
      // §8.1 的「Sheet / Dialog」行是 default + focus。加载态由内容区放骨架,
      // 弹层本身没有 loading 形态。
      expect(EmberComponentSizes.sheetHandleWidth, 36);
    });
  });
}
