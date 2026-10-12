import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/widgets/app_button.dart';
import 'package:chatapp_app/core/widgets/app_dialog.dart';

void main() {
  testWidgets('showConfirmDialog:点确认返回 true,点取消返回 false', (tester) async {
    bool? result;
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: Builder(
          builder: (context) => TextButton(
            onPressed: () async {
              result = await showConfirmDialog(
                context,
                title: '删除这条动态?',
                confirmLabel: '删除',
                confirmKey: const Key('d.confirm'),
                danger: true,
              );
            },
            child: const Text('开'),
          ),
        ),
      ),
    ));

    await tester.tap(find.text('开'));
    await tester.pumpAndSettle();
    expect(find.text('删除这条动态?'), findsOneWidget);
    expect(find.byKey(const Key('d.confirm')), findsOneWidget);
    expect(
      tester.widget<AppButton>(find.byKey(const Key('d.confirm'))).variant,
      AppButtonVariant.dangerFilled,
    );

    await tester.tap(find.byKey(const Key('d.confirm')));
    await tester.pumpAndSettle();
    expect(result, isTrue);

    await tester.tap(find.text('开'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('取消'));
    await tester.pumpAndSettle();
    expect(result, isFalse);
  });

  testWidgets('AppDialog:标题 + 正文 + 自定义 content + 两个等宽按钮', (tester) async {
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: AppDialog(
          title: '用户协议与隐私政策',
          message: '请阅读并同意以下文件',
          content: const Text('《用户协议》'),
          actions: [
            AppButton(
                label: '不同意',
                variant: AppButtonVariant.secondary,
                onPressed: () {}),
            AppButton(label: '同意并继续', onPressed: () {}),
          ],
        ),
      ),
    ));

    expect(find.text('用户协议与隐私政策'), findsOneWidget);
    expect(find.text('请阅读并同意以下文件'), findsOneWidget);
    expect(find.text('《用户协议》'), findsOneWidget);

    final a = tester.getSize(find.widgetWithText(AppButton, '不同意'));
    final b = tester.getSize(find.widgetWithText(AppButton, '同意并继续'));
    expect(a.width, closeTo(b.width, 0.5)); // 等宽
  });
}
