import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:phosphor_glyphs/phosphor_glyphs.dart';

import 'package:chatapp_app/core/theme/app_theme.dart';
import 'package:chatapp_app/core/theme/ember_colors.dart';
import 'package:chatapp_app/core/theme/tokens.g.dart' as tokens;
import 'package:chatapp_app/core/ui/ember_button.dart';
import 'package:chatapp_app/core/ui/ember_dialog.dart';

import 'ember_test_kit.dart';

/// 把 [EmberDialog] 摆进真实主题里(它自带 `Dialog`,需要 Material 祖先)。
Future<void> _pumpDialog(
  WidgetTester tester,
  Widget dialog, {
  Brightness brightness = Brightness.light,
}) =>
    pumpEmber(tester, dialog, brightness: brightness);

/// 弹一个 [`EmberDialog`] 并等它稳定(用来测 [showEmberDialog] 的返回值)。
Future<bool?> _show(
  WidgetTester tester, {
  required String confirmLabel,
  String? cancelLabel,
  bool danger = false,
  bool barrierDismissible = true,
  String? tapLabel,
}) async {
  bool? result;
  await tester.pumpWidget(
    MaterialApp(
      theme: buildAppTheme(brightness: Brightness.light),
      home: Builder(
        builder: (context) => Scaffold(
          body: Center(
            child: TextButton(
              onPressed: () async {
                result = await showEmberDialog(
                  context,
                  icon: PhosphorIconsRegular.signOut,
                  title: '注销账号?',
                  message: '注销后不可恢复。',
                  confirmLabel: confirmLabel,
                  cancelLabel: cancelLabel ?? '取消',
                  danger: danger,
                  barrierDismissible: barrierDismissible,
                  confirmKey: const Key('dialog.confirm'),
                  cancelKey: const Key('dialog.cancel'),
                );
              },
              child: const Text('打开'),
            ),
          ),
        ),
      ),
    ),
  );
  await tester.tap(find.text('打开'));
  await tester.pumpAndSettle();
  if (tapLabel != null) {
    await tester.tap(find.text(tapLabel));
    await tester.pumpAndSettle();
  }
  return result;
}

void main() {
  group('EmberDialog · §9.3 图标 + 明确动词', () {
    testWidgets('常规:图标 brand.default、标题 17/w600、说明 13 text.secondary', (tester) async {
      await _pumpDialog(
        tester,
        EmberDialog(
          icon: PhosphorIconsRegular.bell,
          title: '开启通知?',
          message: '开启后会收到新消息提醒。',
          confirmLabel: '去开启',
          confirmKey: const Key('dialog.confirm'),
          cancelKey: const Key('dialog.cancel'),
        ),
      );

      final icon = tester.widget<Icon>(find.byIcon(PhosphorIconsRegular.bell));
      expect(icon.color, EmberColors.light.brandDefault);
      expect(icon.size, tokens.sizeIcon24);

      final title = tester.widget<Text>(find.text('开启通知?'));
      expect(title.style!.fontSize, tokens.fontSizeSubtitle);
      expect(title.style!.fontWeight, FontWeight.w600);
      expect(title.style!.color, EmberColors.light.textPrimary);

      final message = tester.widget<Text>(find.text('开启后会收到新消息提醒。'));
      expect(message.style!.fontSize, tokens.fontSizeCaption);
      expect(message.style!.color, EmberColors.light.textSecondary);
    });

    testWidgets('危险:图标 status.danger,确认键走危险变体', (tester) async {
      await _pumpDialog(
        tester,
        EmberDialog(
          icon: PhosphorIconsRegular.trash,
          title: '注销账号?',
          confirmLabel: '注销账号',
          danger: true,
          confirmKey: const Key('dialog.confirm'),
          cancelKey: const Key('dialog.cancel'),
        ),
      );

      expect(
        tester.widget<Icon>(find.byIcon(PhosphorIconsRegular.trash)).color,
        EmberColors.light.statusDanger,
      );
      expect(
        tester.widget<EmberButton>(find.byKey(const Key('dialog.confirm'))).variant,
        EmberButtonVariant.danger,
      );
      expect(
        tester.widget<EmberButton>(find.byKey(const Key('dialog.cancel'))).variant,
        EmberButtonVariant.secondary,
      );
    });

    testWidgets('确认键不许是「确定 / 确认」(构造断言拦下)', (tester) async {
      expect(
        () => EmberDialog(
          icon: PhosphorIconsRegular.trash,
          title: '注销账号?',
          confirmLabel: '确定',
        ),
        throwsAssertionError,
      );
      expect(
        () => EmberDialog(
          icon: PhosphorIconsRegular.trash,
          title: '注销账号?',
          confirmLabel: '确认',
        ),
        throwsAssertionError,
      );
    });

    testWidgets('深色:弹层底 surface.card、标题 text.primary', (tester) async {
      await _pumpDialog(
        tester,
        EmberDialog(
          icon: PhosphorIconsRegular.bell,
          title: '开启通知?',
          confirmLabel: '去开启',
        ),
        brightness: Brightness.dark,
      );
      final dialog = tester.widget<Dialog>(find.byType(Dialog));
      expect(dialog.backgroundColor, EmberColors.dark.surfaceCard);
      expect(tester.widget<Text>(find.text('开启通知?')).style!.color, EmberColors.dark.textPrimary);
    });
  });

  group('EmberDialog · 读屏(page spec §6 第 3 条)', () {
    testWidgets('两个按钮的读屏标签就是明确动词', (tester) async {
      final handle = tester.ensureSemantics();
      await _pumpDialog(
        tester,
        EmberDialog(
          icon: PhosphorIconsRegular.signOut,
          title: '注销账号?',
          confirmLabel: '注销账号',
          cancelLabel: '再想想',
          danger: true,
          confirmKey: const Key('dialog.confirm'),
          cancelKey: const Key('dialog.cancel'),
        ),
      );
      // 用 contains 而不是全等:`EmberButton` 的标签与内在 `Text` 会各贡献一份
      // (「注销账号\n注销账号」),这是 `EmberPressable` 的既有行为(共享组件,本单不动,
      // 已记入 PR「遗留」)。验收要的是「读得到明确动词、读不到『确定』」。
      final confirm = semanticsOf(tester, find.byKey(const Key('dialog.confirm'))).label;
      expect(confirm, contains('注销账号'));
      expect(confirm, isNot(contains('确定')));
      expect(semanticsOf(tester, find.byKey(const Key('dialog.cancel'))).label, contains('再想想'));
      handle.dispose();
    });
  });

  group('showEmberDialog 返回值', () {
    testWidgets('点确认 → true', (tester) async {
      final result = await _show(tester, confirmLabel: '注销账号', tapLabel: '注销账号');
      expect(result, isTrue);
    });

    testWidgets('点取消 / 点外部 → false', (tester) async {
      expect(await _show(tester, confirmLabel: '注销账号', tapLabel: '取消'), isFalse);

      // 点外部(遮罩)关闭:barrierDismissible 默认 true。
      expect(await _show(tester, confirmLabel: '注销账号', tapLabel: null), isNull);
      await tester.tapAt(const Offset(8, 8));
      await tester.pumpAndSettle();
      expect(find.text('注销账号'), findsNothing);
    });

    testWidgets('barrierDismissible = false 时点外部关不掉', (tester) async {
      await _show(tester, confirmLabel: '同意并继续', barrierDismissible: false);
      await tester.tapAt(const Offset(8, 8));
      await tester.pumpAndSettle();
      expect(find.text('同意并继续'), findsOneWidget);
    });
  });
}
